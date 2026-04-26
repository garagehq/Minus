"""Unit tests for src/status_led_controller.py.

The hardware (StatusLEDs / spidev) is replaced with a recording fake so we
can assert on every call. Tests target:

- Public API surface (start/stop/set_state/set_enabled/status)
- Renderers (each state produces the expected RGB pattern at known frames)
- Settings persistence (enabled toggle survives a save/load cycle)
- Thread safety (set_state from outside the loop wins on the next tick)
- Idempotence (start/stop can be called repeatedly without crashing)
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

# Make src/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class _FakeLEDs:
    """In-memory replacement for status_leds.StatusLEDs.

    Records the last frame written to .show() so tests can assert on it.
    """

    num_leds = 8

    def __init__(self):
        self.pixels = [(0, 0, 0)] * self.num_leds
        self.shown_frames = []
        self.closed = False

    def set_pixel(self, i, r, g, b):
        self.pixels[i] = (r, g, b)

    def set_all(self, r, g, b):
        for i in range(self.num_leds):
            self.pixels[i] = (r, g, b)

    def clear(self):
        self.pixels = [(0, 0, 0)] * self.num_leds

    def show(self):
        self.shown_frames.append(list(self.pixels))

    def close(self):
        self.closed = True


class StatusLEDControllerTests(unittest.TestCase):

    def setUp(self):
        # Isolate per-test settings file
        self.tmpdir = tempfile.mkdtemp()
        self.settings_path = os.path.join(self.tmpdir, "settings.json")
        os.environ["MINUS_STATUS_LEDS_SETTINGS"] = self.settings_path

        # Reload module so SETTINGS_FILE picks up the env var
        import importlib
        if "status_led_controller" in sys.modules:
            del sys.modules["status_led_controller"]
        import status_led_controller
        importlib.reload(status_led_controller)
        self.module = status_led_controller

    def tearDown(self):
        # Clean up settings dir
        try:
            if os.path.exists(self.settings_path):
                os.remove(self.settings_path)
            os.rmdir(self.tmpdir)
        except OSError:
            pass
        os.environ.pop("MINUS_STATUS_LEDS_SETTINGS", None)

    # ----------------------------------------------------------- API surface

    def test_initial_state_is_off(self):
        ctrl = self.module.StatusLEDController(leds_factory=_FakeLEDs)
        self.assertEqual(ctrl.state, "off")
        self.assertFalse(ctrl.running)
        # Fresh install (no settings file) should default the toggle ON.
        self.assertTrue(ctrl.enabled)

    def test_disabled_persistence_overrides_default(self):
        with open(self.settings_path, "w") as f:
            json.dump({"enabled": False}, f)
        ctrl = self.module.StatusLEDController(leds_factory=_FakeLEDs)
        self.assertFalse(ctrl.enabled)

    def test_status_returns_full_dict(self):
        ctrl = self.module.StatusLEDController(leds_factory=_FakeLEDs)
        s = ctrl.status()
        self.assertIn("available", s)
        self.assertIn("enabled", s)
        self.assertIn("running", s)
        self.assertIn("state", s)
        self.assertIn("states", s)
        self.assertEqual(set(s["states"]), set(self.module.VALID_STATES))

    def test_set_state_accepts_known_states(self):
        ctrl = self.module.StatusLEDController(leds_factory=_FakeLEDs)
        for name in self.module.VALID_STATES:
            self.assertTrue(ctrl.set_state(name), f"rejected valid state {name}")
            self.assertEqual(ctrl.state, name)

    def test_set_state_rejects_unknown_state(self):
        ctrl = self.module.StatusLEDController(leds_factory=_FakeLEDs)
        ctrl.set_state("idle")
        self.assertFalse(ctrl.set_state("rainbow_explosion"))
        # Rejected state must not change the current state
        self.assertEqual(ctrl.state, "idle")

    def test_set_state_resets_frame_counter(self):
        """Switching state must reset the per-state frame counter so
        animations always start from t=0."""
        ctrl = self.module.StatusLEDController(leds_factory=_FakeLEDs)
        ctrl.start()
        time.sleep(0.15)              # accumulate ~3 ticks
        ctrl.set_state("idle")        # counter should reset to 0
        # internal frame is 0 right after set_state
        with ctrl._lock:
            self.assertEqual(ctrl._frame, 0)
        ctrl.stop()

    def test_set_state_same_state_is_noop(self):
        """Switching to the already-current state must not reset the frame
        counter — otherwise a no-op call could stall mid-animation."""
        ctrl = self.module.StatusLEDController(leds_factory=_FakeLEDs)
        ctrl.set_state("blocking")
        with ctrl._lock:
            ctrl._frame = 42
        self.assertTrue(ctrl.set_state("blocking"))
        with ctrl._lock:
            self.assertEqual(ctrl._frame, 42)

    # ----------------------------------------------------- start/stop lifecycle

    def test_start_creates_thread_stop_joins(self):
        ctrl = self.module.StatusLEDController(leds_factory=_FakeLEDs)
        ctrl.start()
        self.assertTrue(ctrl.running)
        ctrl.stop()
        self.assertFalse(ctrl.running)

    def test_start_is_idempotent(self):
        ctrl = self.module.StatusLEDController(leds_factory=_FakeLEDs)
        ctrl.start()
        first = ctrl._thread
        ctrl.start()  # must not spawn a second thread
        self.assertIs(ctrl._thread, first)
        ctrl.stop()

    def test_stop_is_idempotent(self):
        ctrl = self.module.StatusLEDController(leds_factory=_FakeLEDs)
        ctrl.stop()  # before start
        ctrl.start()
        ctrl.stop()
        ctrl.stop()  # after stop
        self.assertFalse(ctrl.running)

    def test_factory_failure_is_swallowed(self):
        """If hardware is missing, start() must not raise — it just leaves
        the controller unstarted. Critical for headless dev hosts."""
        def boom():
            raise RuntimeError("no /dev/spidev0.0")
        ctrl = self.module.StatusLEDController(leds_factory=boom)
        ctrl.start()
        self.assertFalse(ctrl.running)
        # last_error should carry the reason so the UI can show it.
        self.assertIsNotNone(ctrl.last_error)
        self.assertIn("no /dev/spidev0.0", ctrl.last_error)

    def test_render_failures_trip_after_three(self):
        """Three consecutive show() exceptions disable the strip without
        raising. Status should reflect ``running=False`` and a ``last_error``
        the UI can surface."""
        class BrokenLEDs(_FakeLEDs):
            def show(self):
                raise IOError("SPI gone")
        ctrl = self.module.StatusLEDController(leds_factory=BrokenLEDs)
        ctrl.start()
        # Wait long enough for >3 ticks (50 ms each + cleanup)
        time.sleep(0.5)
        self.assertFalse(ctrl.running)
        self.assertIsNotNone(ctrl.last_error)
        self.assertIn("SPI gone", ctrl.last_error)
        # Toggle survives — user's preference, not auto-changed
        self.assertTrue(ctrl.enabled)

    def test_drive_predicate_false_renders_zeros(self):
        """When the gate predicate returns False, the strip should be
        rendered as all-zero frames regardless of the active state. The
        state machine itself must keep ticking so animations resume
        correctly when the gate returns True later."""
        leds = _FakeLEDs()
        ctrl = self.module.StatusLEDController(leds_factory=lambda: leds)
        gate = {"on": False}
        ctrl.set_drive_predicate(lambda: gate["on"])
        ctrl.set_state("idle")  # would render solid green
        ctrl.start()
        time.sleep(0.5)  # let several ticks happen while gated
        ctrl.stop()
        # Every shown frame must be all-zero — never green.
        for f in leds.shown_frames:
            self.assertTrue(
                all(p == (0, 0, 0) for p in f),
                f"gated frame leaked non-zero pixels: {f}",
            )

    def test_drive_predicate_true_renders_state(self):
        leds = _FakeLEDs()
        ctrl = self.module.StatusLEDController(leds_factory=lambda: leds)
        ctrl.set_drive_predicate(lambda: True)
        ctrl.set_state("idle")
        ctrl.start()
        time.sleep(0.4)
        ctrl.stop()
        green = [p for f in leds.shown_frames for p in f if p == (0, 255, 0)]
        self.assertTrue(green, "no green frames in gated=True history")

    def test_drive_predicate_can_flip_at_runtime(self):
        leds = _FakeLEDs()
        ctrl = self.module.StatusLEDController(leds_factory=lambda: leds)
        gate = {"on": True}
        ctrl.set_drive_predicate(lambda: gate["on"])
        ctrl.set_state("idle")
        ctrl.start()
        time.sleep(0.3)
        # Snapshot how many frames we drove while ungated.
        ungated_frame_count = len(leds.shown_frames)
        gate["on"] = False
        time.sleep(0.4)
        ctrl.stop()
        # Frames after the flip must all be dark.
        post_flip = leds.shown_frames[ungated_frame_count:]
        self.assertTrue(post_flip, "no frames captured after flip")
        for f in post_flip:
            self.assertTrue(all(p == (0, 0, 0) for p in f))

    def test_drive_predicate_raising_falls_back_to_true(self):
        """A predicate that raises must not leave the strip stuck dark."""
        leds = _FakeLEDs()
        ctrl = self.module.StatusLEDController(leds_factory=lambda: leds)
        def _bad():
            raise RuntimeError("oops")
        ctrl.set_drive_predicate(_bad)
        ctrl.set_state("idle")
        ctrl.start()
        time.sleep(0.4)
        ctrl.stop()
        green = [p for f in leds.shown_frames for p in f if p == (0, 255, 0)]
        self.assertTrue(
            green,
            "raising predicate should fall back to drive=True, but no green",
        )

    def test_status_reports_gated_flag(self):
        ctrl = self.module.StatusLEDController(leds_factory=_FakeLEDs)
        ctrl.set_drive_predicate(lambda: False)
        self.assertTrue(ctrl.status()["gated"])
        ctrl.set_drive_predicate(lambda: True)
        self.assertFalse(ctrl.status()["gated"])
        ctrl.set_drive_predicate(None)
        self.assertFalse(ctrl.status()["gated"])

    def test_render_recovery_clears_error(self):
        """A successful frame after a transient error clears the counter
        so a single bad frame doesn't haunt status() forever."""
        flake = {"count": 0}
        class FlakeyLEDs(_FakeLEDs):
            def show(self):
                flake["count"] += 1
                if flake["count"] == 1:
                    raise IOError("blip")
                # subsequent frames succeed
                super().show()
        ctrl = self.module.StatusLEDController(leds_factory=FlakeyLEDs)
        ctrl.start()
        time.sleep(0.3)
        self.assertTrue(ctrl.running)
        self.assertIsNone(ctrl.last_error)
        ctrl.stop()

    def test_close_called_on_stop(self):
        leds_holder = {}
        def factory():
            leds_holder["leds"] = _FakeLEDs()
            return leds_holder["leds"]
        ctrl = self.module.StatusLEDController(leds_factory=factory)
        ctrl.start()
        time.sleep(0.1)
        ctrl.stop()
        self.assertTrue(leds_holder["leds"].closed)

    # ------------------------------------------------------------ persistence

    def test_set_enabled_persists(self):
        ctrl = self.module.StatusLEDController(leds_factory=_FakeLEDs)
        ctrl.set_enabled(True)
        with open(self.settings_path) as f:
            data = json.load(f)
        self.assertTrue(data["enabled"])
        ctrl.stop()

    def test_persisted_enabled_loads_on_construct(self):
        with open(self.settings_path, "w") as f:
            json.dump({"enabled": True}, f)
        ctrl = self.module.StatusLEDController(leds_factory=_FakeLEDs)
        self.assertTrue(ctrl.enabled)

    def test_set_enabled_starts_and_stops_thread(self):
        ctrl = self.module.StatusLEDController(leds_factory=_FakeLEDs)
        ctrl.set_enabled(True)
        self.assertTrue(ctrl.running)
        ctrl.set_enabled(False)
        self.assertFalse(ctrl.running)

    # -------------------------------------------------------------- renderers

    def test_render_off_is_all_dark(self):
        leds = _FakeLEDs()
        self.module._render_off(leds, 0)
        self.assertTrue(all(p == (0, 0, 0) for p in leds.pixels))

    def test_render_idle_is_solid_green(self):
        leds = _FakeLEDs()
        self.module._render_idle(leds, 0)
        self.assertTrue(all(p == (0, 255, 0) for p in leds.pixels))

    def test_render_initializing_step_one(self):
        """At frame 0 every LED should be at step-1 white = (17,17,17),
        the bottom of the ramp."""
        leds = _FakeLEDs()
        self.module._render_initializing(leds, 0)
        self.assertEqual(leds.pixels[0], (17, 17, 17))

    def test_render_initializing_peak(self):
        """At the apex of the triangle wave (14 steps in) we should be
        at step 15 — input 255 (pre-cap)."""
        leds = _FakeLEDs()
        peak_frame = 14 * self.module._INIT_STEP_TICKS
        self.module._render_initializing(leds, peak_frame)
        self.assertEqual(leds.pixels[0], (255, 255, 255))

    def test_render_initializing_loops(self):
        """A full 28-step cycle should produce the same frame as t=0."""
        leds_a, leds_b = _FakeLEDs(), _FakeLEDs()
        cycle_frames = 28 * self.module._INIT_STEP_TICKS
        self.module._render_initializing(leds_a, 0)
        self.module._render_initializing(leds_b, cycle_frames)
        self.assertEqual(leds_a.pixels, leds_b.pixels)

    def test_render_blocking_has_one_bright_pixel(self):
        leds = _FakeLEDs()
        self.module._render_blocking(leds, 0)
        # Exactly one pixel at (255,0,0); the rest should be dimmer red or dark
        bright = [p for p in leds.pixels if p == (255, 0, 0)]
        self.assertEqual(len(bright), 1)

    def test_render_blocking_moves_with_frame(self):
        """The bright pixel should advance one LED per blocking step."""
        step = self.module._BLOCKING_STEP_TICKS
        positions = []
        for k in (0, 1, 2, 3):
            f = k * step
            leds = _FakeLEDs()
            self.module._render_blocking(leds, f)
            for i, p in enumerate(leds.pixels):
                if p == (255, 0, 0):
                    positions.append(i)
                    break
        # Expect strictly increasing for the first half of the cycle
        self.assertEqual(positions, sorted(positions))
        self.assertGreater(positions[-1], positions[0])

    def test_render_no_signal_is_amber(self):
        leds = _FakeLEDs()
        # Quarter-cycle = mid-ramp where amber should be at half-brightness
        self.module._render_no_signal(
            leds, self.module._NO_SIGNAL_PERIOD_TICKS // 4)
        r, g, b = leds.pixels[0]
        self.assertGreater(r, 0)
        self.assertGreater(g, 0)
        self.assertEqual(b, 0)
        self.assertGreater(r, g)  # red > green ⇒ amber, not yellow

    def test_render_paused_is_yellow(self):
        leds = _FakeLEDs()
        # Quarter-cycle ⇒ mid-ramp brightness
        self.module._render_paused(
            leds, self.module._PAUSED_PERIOD_TICKS // 4)
        r, g, b = leds.pixels[0]
        self.assertGreater(r, 0)
        self.assertEqual(r, g)        # equal R + G ⇒ pure yellow
        self.assertEqual(b, 0)

    def test_render_wifi_setup_alternates(self):
        """Even/odd LEDs should be at different brightnesses, swapping
        once per phase tick."""
        leds = _FakeLEDs()
        self.module._render_wifi_setup(leds, 0)
        a = leds.pixels[0]
        b = leds.pixels[1]
        self.assertNotEqual(a, b, "even and odd LEDs must differ")
        self.module._render_wifi_setup(leds, self.module._WIFI_PHASE_TICKS)
        # After the swap, what was bright should now be dim and vice versa.
        a2 = leds.pixels[0]
        b2 = leds.pixels[1]
        self.assertEqual(a, b2)
        self.assertEqual(b, a2)

    def test_render_autonomous_is_blue_only(self):
        leds = _FakeLEDs()
        self.module._render_autonomous(
            leds, self.module._AUTONOMOUS_PERIOD_TICKS // 4)
        r, g, b = leds.pixels[0]
        self.assertEqual(r, 0)
        self.assertEqual(g, 0)
        self.assertGreater(b, 0)

    def test_render_error_blinks(self):
        leds_on = _FakeLEDs()
        leds_off = _FakeLEDs()
        self.module._render_error(leds_on, 0)
        self.module._render_error(
            leds_off, self.module._ERROR_PHASE_TICKS)  # one half-period later
        self.assertEqual(leds_on.pixels[0], (255, 0, 0))
        self.assertEqual(leds_off.pixels[0], (0, 0, 0))

    # ------------------------------------------------------- thread integration

    def test_thread_renders_current_state(self):
        """Background thread should pick up state changes between ticks."""
        leds = _FakeLEDs()
        ctrl = self.module.StatusLEDController(leds_factory=lambda: leds)
        ctrl.set_state("idle")
        ctrl.start()
        time.sleep(0.2)  # ≥3 ticks
        ctrl.stop()
        # On exit the worker pushes a final blank frame, so the *current*
        # buffer is dark — but the per-frame history should contain the
        # green frames it rendered before stop fired.
        green = [p for f in leds.shown_frames for p in f if p == (0, 255, 0)]
        self.assertTrue(green, "no green frames in shown_frames history")

    def test_thread_picks_up_state_change(self):
        leds = _FakeLEDs()
        ctrl = self.module.StatusLEDController(leds_factory=lambda: leds)
        ctrl.start()
        ctrl.set_state("idle")
        time.sleep(0.15)
        ctrl.set_state("error")
        time.sleep(0.1)
        ctrl.stop()
        # We should have seen both green frames AND red frames
        all_pixels = {tuple(p) for f in leds.shown_frames for p in f}
        self.assertIn((0, 255, 0), all_pixels)
        self.assertIn((255, 0, 0), all_pixels)


if __name__ == "__main__":
    unittest.main(verbosity=2)
