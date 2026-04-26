"""StatusLEDController — animated state machine driving the WS2812B strip.

Wraps :class:`status_leds.StatusLEDs` with a background animation thread that
renders one of a fixed set of named *states*. State changes are atomic and
thread-safe — call :meth:`set_state` from anywhere (HTTP handler, ad blocker,
health monitor) and the next animation tick picks it up.

Tick rate is 50 ms (20 fps). Per-state renderers receive the tick number so
they can self-pace effects of any period (e.g. the white init pulse advances
1% per ten ticks = 500 ms; the bouncing-red blocking effect advances 1 LED
per three ticks ≈ 150 ms).

State catalogue
---------------
- ``off``           — all LEDs dark
- ``initializing``  — white pulse, 1% → 15% → 1% (1% per 500 ms)
- ``idle``          — solid green (system healthy / running)
- ``blocking``      — bouncing red Cylon eye (ad blocking active)
- ``paused``        — slow yellow breathing (detection paused by the user)
- ``no_signal``     — slow amber breathing (HDMI signal lost)
- ``autonomous``    — slow blue breathing (autonomous-mode driving the box)
- ``wifi_setup``    — cyan alternating sweep (captive portal / AP mode active)
- ``error``         — fast red blink (subsystem failure)

Adding new states is a one-liner: register a renderer in ``_RENDERERS``.

Persistence
-----------
The user-facing on/off toggle (``enabled``) is written to
``~/.minus_status_leds.json`` so the choice survives reboots. State itself is
runtime-only — internal callers re-assert state on every relevant transition.

Hardware availability
---------------------
``StatusLEDController.hardware_available()`` returns ``True`` iff
``/dev/spidev0.0`` exists and is openable. The webui uses this to surface a
"hardware missing" 503 cleanly instead of crashing.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Tick interval. Renderers self-pace through `_to_ticks(seconds)` below
# so their visible cadence is independent of the frame rate; if you
# tweak TICK_S, animations keep the same wall-clock timing. Slower
# ticks reduce the rate of current swings on the strip, which helps
# decode reliability on a marginal 3.3V → 5V data line.
TICK_S = 0.20


def _to_ticks(seconds):
    """Convert wall-clock seconds to an integer tick count for the worker
    loop. Used so renderers can express timing in seconds and survive a
    TICK_S change."""
    return max(1, int(round(seconds / TICK_S)))


# Per-animation cadence, computed once at import. If you change TICK_S
# above, regenerate these to keep the on-the-wire timing the same.
_INIT_STEP_TICKS         = _to_ticks(0.5)   # 1% per 500 ms
_BLOCKING_STEP_TICKS     = _to_ticks(0.15)  # bounce moves 1 LED / 150 ms
_NO_SIGNAL_PERIOD_TICKS  = _to_ticks(4.0)   # amber breath cycle
_PAUSED_PERIOD_TICKS     = _to_ticks(3.0)   # yellow breath cycle
_AUTONOMOUS_PERIOD_TICKS = _to_ticks(4.0)   # blue breath cycle
_ERROR_PHASE_TICKS       = _to_ticks(0.25)  # red blink half-period
_WIFI_PHASE_TICKS        = _to_ticks(0.25)  # cyan sweep half-period

SETTINGS_FILE = Path(os.environ.get(
    "MINUS_STATUS_LEDS_SETTINGS",
    str(Path.home() / ".minus_status_leds.json"),
))

VALID_STATES = (
    "off",
    "initializing",
    "idle",
    "blocking",
    "paused",
    "no_signal",
    "autonomous",
    "wifi_setup",
    "error",
)


class StatusLEDController:
    """State-driven WS2812B animator.

    Construction is hardware-free; :meth:`start` is what touches SPI. That
    matches IRTransmitter's pattern so a missing overlay only fails when
    the user actually toggles the feature on.
    """

    def __init__(self, leds_factory=None):
        # Defer the import so the rest of the app can run on machines
        # without spidev installed (e.g. unit-test hosts).
        if leds_factory is None:
            def leds_factory():
                from status_leds import StatusLEDs
                return StatusLEDs()
        self._leds_factory = leds_factory

        self._lock = threading.Lock()
        self._leds = None
        self._thread = None
        self._stop_event = threading.Event()
        self._frame = 0
        self._state = "off"
        # Last hardware/runtime error message surfaced via status(). Cleared
        # on successful start(); set when factory raises or the render loop
        # trips the consecutive-failure threshold below.
        self._last_error = None
        # Tripwire: how many show()s in a row failed. Reset on every success.
        # Three strikes ⇒ stop the thread (LEDs go dark + UI sees the error)
        # without crashing the rest of the service.
        self._consecutive_render_errors = 0
        # User toggle. Default ON — most users will have the SPI overlay
        # enabled by install.sh, and a missing overlay just leaves the strip
        # gracefully off with last_error set instead of failing loudly.
        self._enabled = self._load_settings().get("enabled", True)

    # ------------------------------------------------------------------ status

    @staticmethod
    def hardware_available():
        """True iff /dev/spidev0.0 exists. Doesn't probe — opening is what
        actually validates, but this is a fast pre-check for the UI gate."""
        return os.path.exists("/dev/spidev0.0")

    @property
    def enabled(self):
        return self._enabled

    @property
    def running(self):
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def state(self):
        with self._lock:
            return self._state

    @property
    def last_error(self):
        with self._lock:
            return self._last_error

    def status(self):
        """Snapshot for the API. Cheap; safe to call frequently."""
        with self._lock:
            return {
                "available": self.hardware_available(),
                "enabled": self._enabled,
                "running": self._thread is not None and self._thread.is_alive(),
                "state": self._state,
                "states": list(VALID_STATES),
                "last_error": self._last_error,
            }

    # ----------------------------------------------------------------- control

    def set_enabled(self, enabled):
        """Toggle the feature on/off. Persists. Starts/stops the thread.

        Disabling resets the in-memory state to ``off`` so the next status()
        snapshot agrees with what's actually on the wire (dark strip).
        """
        enabled = bool(enabled)
        with self._lock:
            self._enabled = enabled
            self._save_settings()
        if enabled:
            self.start()
        else:
            self.stop()
            with self._lock:
                self._state = "off"
                self._frame = 0
        return {"success": True, "enabled": enabled}

    def start(self):
        """Open SPI and start the animation thread. Idempotent.

        On hardware failure the controller stays alive in a "no-op" state —
        ``running`` reports False, ``last_error`` carries the reason, and
        the rest of Minus keeps running. The user can flip the toggle off
        and back on to retry after fixing wiring / installing the overlay.

        Crucially: if a previous thread is still winding down (e.g. a
        rapid disable→enable cycle from the UI), wait for it to fully
        exit before opening a new SPI handle. Two threads writing to
        /dev/spidev0.0 at the same time produces garbled frames that
        the strip renders as "flashing all the colours".
        """
        # Fast path: already running — leave it alone (idempotent).
        if self._thread is not None and self._thread.is_alive():
            return
        # Reap a dead/dying thread (worker that self-exited via the failure
        # tripwire, or a stop() that's already joined). Outside the lock so
        # we don't deadlock with the worker's exit path.
        prior = self._thread
        if prior is not None:
            prior.join(timeout=2.0)
            if prior.is_alive():
                logger.warning(
                    "[StatusLED] previous thread still alive after 2s "
                    "join; refusing to start a second SPI writer")
                return
        with self._lock:
            # Re-check under the lock — another caller may have raced.
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = None
            # Make sure any previous leds handle is closed before we open
            # a new one. Belt-and-suspenders; stop() already does this.
            old = self._leds
            self._leds = None
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            try:
                self._leds = self._leds_factory()
            except Exception as e:
                msg = f"could not open SPI hardware: {e}"
                logger.warning(f"[StatusLED] {msg}")
                self._leds = None
                self._last_error = msg
                return
            self._stop_event.clear()
            self._frame = 0
            self._consecutive_render_errors = 0
            self._last_error = None
            t = threading.Thread(
                target=self._run, name="status-leds", daemon=True)
            self._thread = t
            t.start()
            logger.info(
                f"[StatusLED] started, initial state={self._state!r}")

    def stop(self):
        """Stop the thread and blank + close the strip. Idempotent.

        Keeps ``self._thread`` populated until join() returns so a racing
        ``start()`` cannot spawn a second SPI writer while we're still
        winding down. The thread reference is cleared on the way out.
        """
        # Snapshot the thread reference but DO NOT clear it yet — that
        # was the original bug that let two SPI writers coexist briefly.
        t = self._thread
        if t is None:
            # Still close any lingering leds handle if start() opened one
            # but never spawned the thread (e.g. factory succeeded but
            # something else raised between).
            leds = self._leds
            self._leds = None
            if leds is not None:
                try:
                    leds.close()
                except Exception:
                    pass
            return
        self._stop_event.set()
        t.join(timeout=2.0)
        with self._lock:
            self._thread = None
        leds = self._leds
        self._leds = None
        if leds is not None:
            try:
                leds.close()
            except Exception:
                pass

    def set_state(self, state):
        """Switch to ``state``. Returns True if accepted, False if unknown.

        Safe to call before :meth:`start`. The chosen state is rendered on
        the next tick once the thread is running. Raising on unknown state
        would be friendlier internally but the API endpoint also calls this
        and a False return is easier for the handler to convert to a 400.
        """
        if state not in VALID_STATES:
            return False
        with self._lock:
            if state == self._state:
                return True
            self._state = state
            # Reset frame so animations always start from t=0. Without this,
            # switching from blocking → initializing mid-frame would inherit
            # the blocking frame counter and start the white pulse partway
            # through its cycle.
            self._frame = 0
        return True

    # ----------------------------------------------------------------- internal

    def _run(self):
        # Local copy so the lock isn't grabbed every tick; state changes are
        # picked up via the next-iteration re-read.
        while not self._stop_event.is_set():
            try:
                with self._lock:
                    state = self._state
                    frame = self._frame
                    self._frame += 1
                renderer = _RENDERERS.get(state, _render_off)
                if self._leds is not None:
                    renderer(self._leds, frame)
                    self._leds.show()
                # Successful frame — clear any prior error counter / message.
                if self._consecutive_render_errors:
                    with self._lock:
                        self._consecutive_render_errors = 0
                        self._last_error = None
            except Exception as e:
                # Swallow one bad frame — could be transient. After three
                # consecutive failures we conclude the hardware/wiring is
                # gone and stop driving the strip; the user sees `running=
                # False` + `last_error` in the UI and can fix it without
                # the rest of the service having noticed anything.
                with self._lock:
                    self._consecutive_render_errors += 1
                    failures = self._consecutive_render_errors
                    self._last_error = f"render error: {e}"
                logger.warning(
                    f"[StatusLED] render error #{failures}: {e}")
                if failures >= 3:
                    logger.error(
                        f"[StatusLED] disabling strip after {failures} "
                        f"consecutive errors — fix wiring / SPI overlay "
                        f"and toggle off/on to retry")
                    self._stop_event.set()
                    break
            self._stop_event.wait(TICK_S)
        # Cleanup — try a final blank frame so the strip doesn't sit on
        # whatever it was last rendering, then return. We deliberately
        # don't close the SPI handle here: stop() owns the lifecycle, and
        # closing from two places opens a race where a fresh start() in
        # the meantime is operating on a closed handle.
        try:
            if self._leds is not None:
                self._leds.clear()
                self._leds.show()
        except Exception:
            pass

    def _load_settings(self):
        try:
            if SETTINGS_FILE.exists():
                with open(SETTINGS_FILE) as f:
                    return json.load(f) or {}
        except Exception as e:
            logger.warning(f"[StatusLED] could not load settings: {e}")
        return {}

    def _save_settings(self):
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(SETTINGS_FILE, "w") as f:
                json.dump({"enabled": self._enabled}, f, indent=2)
        except Exception as e:
            logger.warning(f"[StatusLED] could not save settings: {e}")


# =====================================================================
# Per-state renderers.
# Each takes the StatusLEDs instance and the current frame number and
# mutates the framebuffer. Caller calls .show().
# =====================================================================

def _render_off(leds, frame):
    leds.set_all(0, 0, 0)


def _render_initializing(leds, frame):
    """White pulse, advancing one step per 500 ms.

    Triangle wave over 28 positions per cycle (14 s/breath): pos 0..14
    climbs 1..15, pos 15..27 falls 14..2, then wraps. Step 1 → input 17,
    step 15 → input 255. After the brightness cap that's ~floor → max
    of whatever ``BRIGHTNESS`` is set to in :mod:`status_leds`.
    """
    cycle = 28
    pos = (frame // _INIT_STEP_TICKS) % cycle
    step = pos + 1 if pos <= 14 else 29 - pos       # 1..15..2..1
    val = step * 17                                 # 17, 34, …, 255
    val = min(255, val)
    leds.set_all(val, val, val)


def _render_idle(leds, frame):
    leds.set_all(0, 255, 0)


def _render_blocking(leds, frame):
    """Bouncing red Cylon eye with 2-pixel decaying tail (150 ms / step)."""
    n = leds.num_leds
    if n <= 0:
        return
    period = 2 * (n - 1) if n > 1 else 1
    pos_in_cycle = (frame // _BLOCKING_STEP_TICKS) % period
    pos = pos_in_cycle if pos_in_cycle < n else period - pos_in_cycle
    leds.clear()
    leds.set_pixel(pos, 255, 0, 0)
    for offset, intensity in ((1, 80), (2, 25)):
        for sign in (-1, 1):
            tail = pos + sign * offset
            if 0 <= tail < n:
                leds.set_pixel(tail, intensity, 0, 0)


def _render_no_signal(leds, frame):
    """Slow amber breathing — 4 s period."""
    period = _NO_SIGNAL_PERIOD_TICKS
    phase = (frame % period) / period
    amp = phase * 2 if phase < 0.5 else (1 - phase) * 2  # triangle 0..1..0
    r = int(255 * amp)
    g = int(90 * amp)
    leds.set_all(r, g, 0)


def _render_paused(leds, frame):
    """Slow yellow breathing — 3 s period.

    Used when the user has explicitly paused detection / blocking from the
    web UI. Distinct from ``no_signal`` (amber) so a glance can tell whether
    the box is paused on purpose vs. waiting for a signal that's gone.
    """
    period = _PAUSED_PERIOD_TICKS
    phase = (frame % period) / period
    amp = phase * 2 if phase < 0.5 else (1 - phase) * 2
    val = int(255 * amp)
    leds.set_all(val, val, 0)                # equal R + G ⇒ pure yellow


def _render_wifi_setup(leds, frame):
    """Cyan alternating-sweep, swapping every 250 ms.

    Two-step pattern: even-indexed LEDs at full cyan, odd at dim cyan,
    swap each phase. Gives a visibly "attention-needed" pulse without
    the urgency of the red error blink — appropriate for "go connect to
    the Minus AP and finish setup".
    """
    even_phase = (frame // _WIFI_PHASE_TICKS) % 2 == 0
    for i in range(leds.num_leds):
        if (i % 2 == 0) == even_phase:
            leds.set_pixel(i, 0, 255, 255)
        else:
            leds.set_pixel(i, 0, 40, 40)


def _render_autonomous(leds, frame):
    """Slow blue breathing — 4 s period."""
    period = _AUTONOMOUS_PERIOD_TICKS
    phase = (frame % period) / period
    amp = phase * 2 if phase < 0.5 else (1 - phase) * 2
    leds.set_all(0, 0, int(255 * amp))


def _render_error(leds, frame):
    """Fast red blink — 250 ms on, 250 ms off (2 Hz)."""
    on = (frame // _ERROR_PHASE_TICKS) % 2 == 0
    if on:
        leds.set_all(255, 0, 0)
    else:
        leds.set_all(0, 0, 0)


_RENDERERS = {
    "off":           _render_off,
    "initializing":  _render_initializing,
    "idle":          _render_idle,
    "blocking":      _render_blocking,
    "paused":        _render_paused,
    "no_signal":     _render_no_signal,
    "autonomous":    _render_autonomous,
    "wifi_setup":    _render_wifi_setup,
    "error":         _render_error,
}
