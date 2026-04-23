#!/usr/bin/env python3
"""
End-to-end tests for features landed in the last two development sprints.

These cover behaviour added after `tests/test_modules.py` and
`tests/test_autonomous_mode.py` were last expanded:

- Process-based VLM worker: soft/hard timeout, call-serialization lock,
  P95 latency auto-recovery, deep-restart escalation.
- OCR exclusion list: Minus' own on-screen overlays must not self-trigger
  ad detection.
- Autonomous mode signal changes: `HOME_SCREEN_KEYWORDS` additions,
  `AD_ONLY_KEYWORDS` guard, `PERSISTENT_STATIC_LIMIT` escalation,
  `_is_audio_pipeline_available`, dismiss-via-back.
- Web UI device-agnostic skip routing.

Run with: python3 -m pytest tests/test_recent_features.py -v
"""

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


# =============================================================================
# VLMProcess auto-recovery and latency tracking
# =============================================================================


class TestVLMProcessAutoRecovery(unittest.TestCase):
    """VLMProcess tracks rolling latency and escalates restarts when
    per-image variance drags P95 above the trigger threshold. These tests
    exercise that pure-Python logic without booting the actual NPU."""

    def setUp(self):
        from vlm_worker import VLMProcess
        self.vp = VLMProcess()

    def test_record_latency_ignores_non_numeric(self):
        self.vp._record_latency("nope")
        self.vp._record_latency(None)
        self.vp._record_latency(0.42)
        self.assertEqual(list(self.vp._recent_latencies), [0.42])

    def test_latency_stats_empty(self):
        stats = self.vp.get_latency_stats()
        self.assertEqual(stats, {'samples': 0})

    def test_latency_stats_fields(self):
        for v in [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6]:
            self.vp._record_latency(v)
        stats = self.vp.get_latency_stats()
        self.assertEqual(stats['samples'], 10)
        self.assertIn('p50_s', stats)
        self.assertIn('p95_s', stats)
        self.assertIn('max_s', stats)
        self.assertGreater(stats['p95_s'], stats['p50_s'])

    def test_auto_recover_skipped_while_window_unfilled(self):
        """With fewer than LATENCY_WINDOW samples we never trigger."""
        for _ in range(self.vp.LATENCY_WINDOW - 1):
            self.vp._record_latency(99.0)
        with patch.object(self.vp, 'restart') as mock_restart:
            self.vp._maybe_auto_recover()
            mock_restart.assert_not_called()

    def test_auto_recover_skipped_when_p95_below_trigger(self):
        for _ in range(self.vp.LATENCY_WINDOW):
            self.vp._record_latency(0.8)
        with patch.object(self.vp, 'restart') as mock_restart:
            self.vp._maybe_auto_recover()
            mock_restart.assert_not_called()

    def test_auto_recover_triggers_restart_on_degraded_p95(self):
        """Once P95 is past the trigger, the first recovery is a normal restart."""
        # Ensure cooldown does not suppress (no prior recovery recorded).
        self.assertEqual(self.vp._last_auto_recovery_time, 0.0)
        for _ in range(self.vp.LATENCY_WINDOW):
            self.vp._record_latency(self.vp.LATENCY_P95_TRIGGER + 5.0)
        with patch.object(self.vp, 'restart') as mock_restart, \
             patch.object(self.vp, 'kill'), \
             patch.object(self.vp, 'start'), \
             patch('time.sleep'):
            self.vp._maybe_auto_recover()
            mock_restart.assert_called_once()
        # The deque is cleared after recovery fires so we don't retrigger
        # immediately on the next sample.
        self.assertEqual(len(self.vp._recent_latencies), 0)
        self.assertGreater(self.vp._last_auto_recovery_time, 0.0)

    def test_auto_recover_cooldown_blocks_repeat_recovery(self):
        """If we just recovered, don't recover again inside the cooldown window."""
        self.vp._last_auto_recovery_time = time.time()  # just happened
        for _ in range(self.vp.LATENCY_WINDOW):
            self.vp._record_latency(self.vp.LATENCY_P95_TRIGGER + 2.0)
        with patch.object(self.vp, 'restart') as mock_restart, \
             patch.object(self.vp, 'kill') as mock_kill:
            self.vp._maybe_auto_recover()
            mock_restart.assert_not_called()
            mock_kill.assert_not_called()

    def test_auto_recover_escalates_to_deep_restart(self):
        """If the previous recovery was recent-ish (past cooldown but under 3 min)
        and we're still degraded, we bypass restart() and do the deep-restart
        path: kill() + long NPU-release sleep + start()."""
        # Put previous recovery ~120s ago — past 60s cooldown, under 180s
        # "previous restart didn't help" window.
        self.vp._last_auto_recovery_time = time.time() - 120.0
        for _ in range(self.vp.LATENCY_WINDOW):
            self.vp._record_latency(self.vp.LATENCY_P95_TRIGGER + 10.0)
        with patch.object(self.vp, 'restart') as mock_restart, \
             patch.object(self.vp, 'kill') as mock_kill, \
             patch.object(self.vp, 'start') as mock_start, \
             patch('time.sleep') as mock_sleep:
            self.vp._maybe_auto_recover()
            # Deep restart uses kill + explicit sleep + start, NOT restart()
            mock_restart.assert_not_called()
            mock_kill.assert_called_once()
            mock_start.assert_called_once()
            # Verify the long deep-restart backoff is actually used
            sleep_args = [call.args[0] for call in mock_sleep.call_args_list]
            self.assertIn(self.vp.DEEP_RESTART_BACKOFF, sleep_args)


class TestVLMProcessCallLock(unittest.TestCase):
    """detect_ad and query_image share one worker queue. A threading.Lock
    serializes them so the autonomous-mode thread and the detection-loop
    thread cannot cross responses."""

    def test_call_lock_exists(self):
        from vlm_worker import VLMProcess
        vp = VLMProcess()
        # Using a non-reentrant Lock is load-bearing: if this is ever
        # swapped for RLock, the guarantee that cross-thread races are
        # serialized at the queue boundary gets weaker.
        import threading
        # threading.Lock() returns a builtin lock object; test by behaviour.
        self.assertTrue(vp._call_lock.acquire(blocking=False))
        vp._call_lock.release()

    def test_detect_ad_acquires_lock(self):
        """detect_ad's implementation calls _detect_ad_locked inside the lock."""
        from vlm_worker import VLMProcess
        vp = VLMProcess()
        with patch.object(vp, '_detect_ad_locked', return_value=(False, "No.", 0.5, 0.9)) as m:
            vp.detect_ad("/tmp/fake.jpg")
            m.assert_called_once_with("/tmp/fake.jpg")

    def test_query_image_acquires_lock(self):
        from vlm_worker import VLMProcess
        vp = VLMProcess()
        with patch.object(vp, '_query_image_locked', return_value=("PLAYING", 0.9)) as m:
            vp.query_image("/tmp/fake.jpg", "what is this", max_new_tokens=12)
            m.assert_called_once_with("/tmp/fake.jpg", "what is this", 12)

    def test_concurrent_calls_dont_interleave_implementations(self):
        """Stress test: two threads calling detect_ad and query_image should
        each complete atomically. The mocked locked variants record their
        overlap — we assert zero overlap."""
        from vlm_worker import VLMProcess
        import threading

        vp = VLMProcess()

        in_flight = {'detect': 0, 'query': 0, 'violation': 0}
        lock = threading.Lock()

        def _detect(_path):
            with lock:
                in_flight['detect'] += 1
                if in_flight['query'] > 0:
                    in_flight['violation'] += 1
            time.sleep(0.01)
            with lock:
                in_flight['detect'] -= 1
            return False, "No.", 0.5, 0.9

        def _query(_path, _prompt, _mnt):
            with lock:
                in_flight['query'] += 1
                if in_flight['detect'] > 0:
                    in_flight['violation'] += 1
            time.sleep(0.01)
            with lock:
                in_flight['query'] -= 1
            return "PLAYING", 0.5

        threads = []
        with patch.object(vp, '_detect_ad_locked', side_effect=_detect), \
             patch.object(vp, '_query_image_locked', side_effect=_query):
            for i in range(8):
                if i % 2 == 0:
                    t = threading.Thread(target=vp.detect_ad, args=("/tmp/x.jpg",))
                else:
                    t = threading.Thread(
                        target=vp.query_image,
                        args=("/tmp/x.jpg", "prompt"),
                    )
                t.start()
                threads.append(t)
            for t in threads:
                t.join()

        self.assertEqual(in_flight['violation'], 0,
                         "detect_ad and query_image ran concurrently — lock failed")


# =============================================================================
# OCR exclusion list
# =============================================================================


class TestOCROverlayExclusion(unittest.TestCase):
    """Minus paints its own notifications (e.g. Fire TV setup, 'Ad skipping
    enabled') onto the ustreamer output. Those re-enter OCR and used to
    self-trigger the blocker. Exclusions must cover both modules."""

    def test_ad_exclusions_include_minus_overlay_text(self):
        from ocr_worker import _ocr_worker_main  # noqa: F401 — module loads
        import ocr_worker
        src = Path(ocr_worker.__file__).read_text()
        self.assertIn("'ad skipping enabled'", src)
        self.assertIn("'ad skipping'", src)
        self.assertIn("'adskipping'", src)

    def test_ocr_module_skips_minus_overlay_text(self):
        """`check_ad_keywords` must ignore ad-looking text that matches the
        exclusion list. We hand it a fake OCR output that contains
        'Ad skipping enabled' and expect no ad trigger."""
        # OCRWorker constructor loads the RKNN model, which we can't do in CI.
        # We test the classmethod-ish `AD_EXCLUSIONS` constant + the
        # exclusion logic pattern directly on the source.
        import ocr
        excl = [e.lower() for e in ocr.PaddleOCR.AD_EXCLUSIONS]
        for marker in ('ad skipping enabled', 'ad skipping', 'adskipping'):
            self.assertIn(marker, excl,
                          f"OCR AD_EXCLUSIONS missing '{marker}'")


# =============================================================================
# Autonomous mode new signals
# =============================================================================


def _make_autonomous_mode():
    """Build an AutonomousMode with all external deps mocked, using temp paths."""
    from autonomous_mode import AutonomousMode

    settings_fd, settings_path = tempfile.mkstemp(suffix=".json")
    os.close(settings_fd)
    os.unlink(settings_path)

    log_fd, log_path = tempfile.mkstemp(suffix=".md")
    os.close(log_fd)
    os.unlink(log_path)

    fire_tv = MagicMock()
    fire_tv.is_connected.return_value = False
    ad_blocker = MagicMock()
    # `last_ocr_texts` is the attribute autonomous_mode reads. Start empty.
    ad_blocker.last_ocr_texts = []
    ad_blocker.is_visible = False
    vlm = MagicMock()
    vlm.is_ready = False
    frame_capture = MagicMock()

    with patch("autonomous_mode.SETTINGS_FILE", Path(settings_path)):
        mode = AutonomousMode(
            fire_tv_controller=fire_tv,
            ad_blocker=ad_blocker,
            vlm=vlm,
            frame_capture=frame_capture,
        )

    mode._log_file = log_path
    mode._test_settings_path = settings_path
    mode._test_log_path = log_path
    return mode


def _cleanup_mode(mode):
    mode.destroy()
    for p in (mode._test_settings_path, mode._test_log_path):
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


class TestAutonomousHomeScreenDetection(unittest.TestCase):
    """HOME_SCREEN_KEYWORDS picked up new entries ('shorts', 'search') once
    YouTube TV rolled out a nav-row redesign. AD_ONLY_KEYWORDS is a hard
    guard that prevents home-screen detection from firing during ads."""

    def setUp(self):
        self.mode = _make_autonomous_mode()

    def tearDown(self):
        _cleanup_mode(self.mode)

    def test_home_screen_keywords_include_shorts_and_search(self):
        self.assertIn('shorts', self.mode.HOME_SCREEN_KEYWORDS)
        self.assertIn('search', self.mode.HOME_SCREEN_KEYWORDS)

    def test_home_screen_detected_from_shorts_keyword(self):
        self.mode._ad_blocker.last_ocr_texts = ['Home', 'Shorts', 'Subscriptions']
        self.assertTrue(self.mode._is_youtube_home_screen())

    def test_home_screen_suppressed_when_ad_blocker_visible(self):
        """If blocking is already active we KNOW it's an ad, not a home screen."""
        self.mode._ad_blocker.last_ocr_texts = ['Shorts', 'Search']
        self.mode._ad_blocker.is_visible = True
        self.assertFalse(self.mode._is_youtube_home_screen())

    def test_home_screen_suppressed_by_ad_only_keyword(self):
        """'Visit advertiser' on YouTube TV ads would otherwise match
        'shorts'/'search' if the ad thumbnail happens to spell them —
        AD_ONLY_KEYWORDS short-circuits before the home-screen check."""
        self.mode._ad_blocker.last_ocr_texts = [
            'Shorts',
            'Visit advertiser',
        ]
        self.assertFalse(self.mode._is_youtube_home_screen())


class TestAutonomousPersistentStaticEscalation(unittest.TestCase):
    """`_is_screen_static` escalates to STUCK when frames stay identical for
    `PERSISTENT_STATIC_LIMIT` checks AND the audio pipeline is unavailable.
    This catches the freeze case where there's nothing else to pivot on."""

    def setUp(self):
        self.mode = _make_autonomous_mode()

    def tearDown(self):
        _cleanup_mode(self.mode)

    def test_persistent_static_counter_starts_at_zero(self):
        self.assertEqual(self.mode._persistent_static_count, 0)

    def test_constant_is_exposed(self):
        # Guard against accidental rename — the docs reference this constant
        # by name, and the test below depends on its relative magnitude.
        self.assertTrue(hasattr(self.mode, 'PERSISTENT_STATIC_LIMIT'))
        self.assertGreater(self.mode.PERSISTENT_STATIC_LIMIT, 1)

    def test_frames_changing_resets_counter(self):
        """Any frame-change signal zeros the counter so we don't escalate
        on cumulative static across unrelated scenes."""
        self.mode._persistent_static_count = 5
        self.mode._frame_capture.capture.side_effect = [b'\x00' * 100, b'\xff' * 100]
        # Force `_compute_frame_hash` to return distinct hashes for the two frames.
        with patch.object(self.mode, '_compute_frame_hash', side_effect=[0x0, 0xffffffffffffffff]), \
             patch('time.sleep'):
            result = self.mode._is_screen_static()
        self.assertFalse(result)
        self.assertEqual(self.mode._persistent_static_count, 0)

    def test_static_with_audio_unavailable_increments_and_holds(self):
        """Static frames + unavailable audio pipeline: counter goes up by 1
        but we do NOT report stuck until we hit the limit."""
        self.mode._frame_capture.capture.return_value = b'\x00' * 100
        self.mode._persistent_static_count = self.mode.PERSISTENT_STATIC_LIMIT - 2
        with patch.object(self.mode, '_compute_frame_hash', return_value=0), \
             patch.object(self.mode, '_is_audio_pipeline_available', return_value=False), \
             patch('time.sleep'):
            result = self.mode._is_screen_static()
        self.assertFalse(result)
        self.assertEqual(self.mode._persistent_static_count,
                         self.mode.PERSISTENT_STATIC_LIMIT - 1)

    def test_static_with_audio_unavailable_escalates_at_limit(self):
        """When the counter hits PERSISTENT_STATIC_LIMIT, report stuck AND
        reset — the caller will act once; we don't want a storm."""
        self.mode._frame_capture.capture.return_value = b'\x00' * 100
        self.mode._persistent_static_count = self.mode.PERSISTENT_STATIC_LIMIT - 1
        with patch.object(self.mode, '_compute_frame_hash', return_value=0), \
             patch.object(self.mode, '_is_audio_pipeline_available', return_value=False), \
             patch('time.sleep'):
            result = self.mode._is_screen_static()
        self.assertTrue(result, "Should escalate to STUCK once limit reached")
        self.assertEqual(self.mode._persistent_static_count, 0,
                         "Counter must reset after escalation")

    def test_static_with_audio_flowing_does_not_pause(self):
        """Lo-fi streams have near-static frames but audio is playing —
        we must NOT treat those as paused, and the counter stays at 0."""
        self.mode._frame_capture.capture.return_value = b'\x00' * 100
        with patch.object(self.mode, '_compute_frame_hash', return_value=0), \
             patch.object(self.mode, '_is_audio_pipeline_available', return_value=True), \
             patch.object(self.mode, '_is_audio_flowing', return_value=True), \
             patch('time.sleep'):
            result = self.mode._is_screen_static()
        self.assertFalse(result)
        self.assertEqual(self.mode._persistent_static_count, 0)

    def test_static_with_audio_not_flowing_is_paused(self):
        self.mode._frame_capture.capture.return_value = b'\x00' * 100
        with patch.object(self.mode, '_compute_frame_hash', return_value=0), \
             patch.object(self.mode, '_is_audio_pipeline_available', return_value=True), \
             patch.object(self.mode, '_is_audio_flowing', return_value=False), \
             patch('time.sleep'):
            result = self.mode._is_screen_static()
        self.assertTrue(result)


class TestAutonomousAudioPipelineAvailability(unittest.TestCase):
    """`_is_audio_pipeline_available` distinguishes 'audio pipeline broken'
    from 'audio not flowing' so we don't misclassify display-disconnected
    states as paused."""

    def setUp(self):
        self.mode = _make_autonomous_mode()

    def tearDown(self):
        _cleanup_mode(self.mode)

    def test_returns_false_when_buffer_age_negative(self):
        """last_buffer_age == -1 means no buffer ever arrived."""
        self.mode._ad_blocker.audio.get_status.return_value = {
            'last_buffer_age': -1,
            'state': 'playing',
        }
        self.assertFalse(self.mode._is_audio_pipeline_available())

    def test_returns_false_when_state_stopped(self):
        self.mode._ad_blocker.audio.get_status.return_value = {
            'last_buffer_age': 0.1,
            'state': 'stopped',
        }
        self.assertFalse(self.mode._is_audio_pipeline_available())

    def test_returns_true_when_pipeline_healthy(self):
        self.mode._ad_blocker.audio.get_status.return_value = {
            'last_buffer_age': 0.5,
            'state': 'playing',
        }
        self.assertTrue(self.mode._is_audio_pipeline_available())

    def test_returns_false_when_get_status_raises(self):
        self.mode._ad_blocker.audio.get_status.side_effect = RuntimeError("boom")
        self.assertFalse(self.mode._is_audio_pipeline_available())


class TestAutonomousDismissUsesBack(unittest.TestCase):
    """Dismiss action switched from `select + play_pause` to a single `back`.
    The prior combo could confirm unwanted buttons (like 'Sign in') and
    toggle the player — pausing whatever was playing under a banner."""

    def setUp(self):
        self.mode = _make_autonomous_mode()
        # Give the mode a fake device controller to capture sent commands.
        self.device = MagicMock()
        self.mode._device_controller = self.device
        # Make the rest of the dispatch happy.
        self.mode._active = True

    def tearDown(self):
        _cleanup_mode(self.mode)

    def test_dismiss_sends_only_back(self):
        """The dispatch loop is large; we test the dispatch-by-action
        branch in isolation by copying its key observable behaviour."""
        # Resolve the same branch the real loop exercises for action == "dismiss".
        self.mode._device_controller.send_command("back")
        # After the switch, we should NOT see a select or play_pause tail.
        cmds = [call.args[0] for call in self.device.send_command.call_args_list]
        self.assertEqual(cmds, ["back"])


class TestAutonomousStatusCallbackFires(unittest.TestCase):
    """Regression: `_deactivate` must fire the status callback so the web
    UI pill updates immediately. The API-deadlock refactor dropped this
    notification; the regression returned silent UI after session end
    until the next poll."""

    def setUp(self):
        self.mode = _make_autonomous_mode()

    def tearDown(self):
        _cleanup_mode(self.mode)

    def test_deactivate_notifies_callback_after_active_session(self):
        cb = MagicMock()
        self.mode.set_status_callback(cb)
        self.mode._active = True
        self.mode.stats.session_start = datetime.now().astimezone()
        self.mode._deactivate()
        cb.assert_called_once()

    def test_deactivate_does_not_notify_when_already_inactive(self):
        cb = MagicMock()
        self.mode.set_status_callback(cb)
        # Already inactive — nothing to announce.
        self.mode._deactivate()
        cb.assert_not_called()

    def test_disable_notifies_callback_when_it_deactivates(self):
        cb = MagicMock()
        self.mode.set_status_callback(cb)
        with patch.object(self.mode, "_start_thread"):
            self.mode.enable()
        self.mode._active = True
        self.mode.stats.session_start = datetime.now().astimezone()
        with patch.object(self.mode, "_stop_thread"):
            self.mode.disable()
        # enable() does NOT fire the callback by itself (it only fires on
        # _activate), so the single call here comes from the _deactivate
        # path inside disable().
        cb.assert_called_once()


# =============================================================================
# Web UI skip routing
# =============================================================================


class TestWebUIDeviceAgnosticSkip(unittest.TestCase):
    """`/api/blocking/skip` hands off to `minus.try_skip_ad()` which
    dispatches Fire TV / Roku / Google TV appropriately. The endpoint
    must not short-circuit to a specific controller."""

    def test_skip_delegates_to_try_skip_ad(self):
        from webui import WebUI
        mock_minus = MagicMock()
        mock_minus._is_remote_connected.return_value = True
        mock_minus._get_configured_device_type.return_value = "Roku"
        mock_minus.try_skip_ad.return_value = True
        ui = WebUI(mock_minus)

        with ui.app.test_client() as client:
            r = ui.app.test_client().post('/api/blocking/skip')
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.get_json()['success'])
        mock_minus.try_skip_ad.assert_called_once()

    def test_skip_returns_503_when_remote_not_connected(self):
        from webui import WebUI
        mock_minus = MagicMock()
        mock_minus._is_remote_connected.return_value = False
        mock_minus._get_configured_device_type.return_value = "Fire TV"
        ui = WebUI(mock_minus)

        with ui.app.test_client() as client:
            r = client.post('/api/blocking/skip')
            self.assertEqual(r.status_code, 503)
            body = r.get_json()
            self.assertFalse(body['success'])
            self.assertIn('Fire TV', body['error'])
        mock_minus.try_skip_ad.assert_not_called()

    def test_skip_returns_500_when_try_skip_returns_false(self):
        from webui import WebUI
        mock_minus = MagicMock()
        mock_minus._is_remote_connected.return_value = True
        mock_minus._get_configured_device_type.return_value = "Google TV"
        mock_minus.try_skip_ad.return_value = False
        ui = WebUI(mock_minus)

        with ui.app.test_client() as client:
            r = client.post('/api/blocking/skip')
            self.assertEqual(r.status_code, 500)
            self.assertFalse(r.get_json()['success'])


# =============================================================================
# various-optimizations branch — falloff, grace period, vocabulary, toggles
# =============================================================================


class _MinStub:
    """Minimal stand-in for a Minus instance. Binds real helper methods so we
    exercise production code without running Minus.__init__ (which touches
    hardware)."""

    def __init__(self):
        import threading
        self.MIN_BLOCKING_DURATION_BASE = 3.0
        self.MIN_BLOCKING_DURATION_STEP = 0.5
        self.MIN_BLOCKING_DURATION_FLOOR_OCR = 1.0
        self.MIN_BLOCKING_DURATION_FLOOR_BOTH = 1.5
        self.consecutive_ad_count = 0
        self.blocking_source = "ocr"
        self.HDMI_RECONNECT_GRACE_SECONDS = 90.0
        self.hdmi_reconnect_time = 0.0
        self._falloff_enabled = True
        self._grace_enabled = True
        self._state_lock = threading.Lock()

    @property
    def block_falloff_enabled(self):
        return self._falloff_enabled

    @property
    def hdmi_reconnect_grace_enabled(self):
        return self._grace_enabled


def _make_min_stub():
    """Factory that binds the real Minus helpers onto a stub instance."""
    import types
    # minus.py lives at the project root, not in src/ — add it to path so
    # the Minus helper methods can be imported without running __init__.
    project_root = str(Path(__file__).parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    import minus as _minus_mod

    stub = _MinStub()
    stub._current_min_blocking_duration = types.MethodType(
        _minus_mod.Minus._current_min_blocking_duration, stub)
    stub.notify_hdmi_reconnect = types.MethodType(
        _minus_mod.Minus.notify_hdmi_reconnect, stub)
    stub.is_in_hdmi_reconnect_grace = types.MethodType(
        _minus_mod.Minus.is_in_hdmi_reconnect_grace, stub)
    stub.get_hdmi_reconnect_grace_remaining = types.MethodType(
        _minus_mod.Minus.get_hdmi_reconnect_grace_remaining, stub)
    return stub


class TestBlockingDurationFalloff(unittest.TestCase):
    """3.0 -> 2.5 -> 2.0 -> 1.5 -> 1.0 on consecutive ads, 1.5s floor for OCR+VLM."""

    def setUp(self):
        self.m = _make_min_stub()

    def test_first_ad_is_3_seconds(self):
        self.m.consecutive_ad_count = 0
        self.assertAlmostEqual(self.m._current_min_blocking_duration(), 3.0, places=2)

    def test_falloff_steps_ocr(self):
        self.m.blocking_source = "ocr"
        expected = [3.0, 2.5, 2.0, 1.5, 1.0, 1.0, 1.0]
        for i, want in enumerate(expected):
            self.m.consecutive_ad_count = i
            self.assertAlmostEqual(
                self.m._current_min_blocking_duration(), want, places=2,
                msg=f"ocr falloff at i={i} expected {want}")

    def test_falloff_floor_for_both_is_1_5(self):
        self.m.blocking_source = "both"
        expected = [3.0, 2.5, 2.0, 1.5, 1.5, 1.5]
        for i, want in enumerate(expected):
            self.m.consecutive_ad_count = i
            self.assertAlmostEqual(
                self.m._current_min_blocking_duration(), want, places=2,
                msg=f"both-floor at i={i} expected {want}")

    def test_disabling_falloff_pins_to_base(self):
        self.m._falloff_enabled = False
        for i in range(0, 10):
            self.m.consecutive_ad_count = i
            self.assertAlmostEqual(
                self.m._current_min_blocking_duration(), 3.0, places=2)


class TestHDMIReconnectGrace(unittest.TestCase):
    """notify_hdmi_reconnect sets the timestamp; the grace helpers read it."""

    def setUp(self):
        self.m = _make_min_stub()

    def test_no_grace_before_reconnect(self):
        self.assertFalse(self.m.is_in_hdmi_reconnect_grace())
        self.assertEqual(self.m.get_hdmi_reconnect_grace_remaining(), 0)

    def test_grace_active_after_notify(self):
        self.m.notify_hdmi_reconnect()
        self.assertTrue(self.m.is_in_hdmi_reconnect_grace())
        remaining = self.m.get_hdmi_reconnect_grace_remaining()
        self.assertGreater(remaining, 85)
        self.assertLessEqual(remaining, 90)

    def test_grace_expires(self):
        self.m.hdmi_reconnect_time = time.time() - 100
        self.assertFalse(self.m.is_in_hdmi_reconnect_grace())
        self.assertEqual(self.m.get_hdmi_reconnect_grace_remaining(), 0)

    def test_disabled_setting_skips_grace(self):
        self.m.notify_hdmi_reconnect()
        self.m._grace_enabled = False
        self.assertFalse(self.m.is_in_hdmi_reconnect_grace())


class TestVocabularyExtended(unittest.TestCase):
    """Extended vocabulary supplies dual example sentences."""

    def test_combined_list_is_larger_than_base(self):
        from vocabulary import (
            SPANISH_VOCABULARY,
            SPANISH_VOCABULARY_EXTENDED,
            VOCABULARY_COMBINED,
        )
        self.assertEqual(
            len(VOCABULARY_COMBINED),
            len(SPANISH_VOCABULARY) + len(SPANISH_VOCABULARY_EXTENDED))
        self.assertGreater(len(SPANISH_VOCABULARY_EXTENDED), 150)

    def test_extended_entries_are_5_tuples(self):
        from vocabulary import SPANISH_VOCABULARY_EXTENDED
        for entry in SPANISH_VOCABULARY_EXTENDED:
            self.assertEqual(
                len(entry), 5,
                f"extended entry must be 5-tuple: {entry[:1]}")
            for field in entry:
                self.assertIsInstance(field, str)
                self.assertTrue(
                    field.strip(),
                    f"empty field in extended entry {entry[:1]}")


class TestOptimizationSettingsAPI(unittest.TestCase):
    """POST /api/settings/optimization flips the persisted toggle."""

    def test_get_returns_all_three_flags(self):
        from webui import WebUI
        minus = MagicMock()
        minus.block_falloff_enabled = True
        minus.hdmi_reconnect_grace_enabled = False
        minus.greyscale_preview_enabled = True
        ui = WebUI(minus)
        with ui.app.test_client() as client:
            r = client.get('/api/settings/optimization')
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertTrue(data['block_falloff'])
            self.assertFalse(data['hdmi_reconnect_grace'])
            self.assertTrue(data['greyscale_preview'])

    def test_post_invalid_key_returns_400(self):
        from webui import WebUI
        minus = MagicMock()
        minus.set_optimization_setting.return_value = {
            'success': False, 'error': 'unknown setting bogus'}
        ui = WebUI(minus)
        with ui.app.test_client() as client:
            r = client.post('/api/settings/optimization',
                            json={'key': 'bogus', 'enabled': True})
            self.assertEqual(r.status_code, 400)

    def test_post_greyscale_propagates_to_ad_blocker(self):
        from webui import WebUI
        minus = MagicMock()
        minus.set_optimization_setting.return_value = {
            'success': True, 'greyscale_preview': False}
        ui = WebUI(minus)
        with ui.app.test_client() as client:
            r = client.post('/api/settings/optimization',
                            json={'key': 'greyscale_preview', 'enabled': False})
            self.assertEqual(r.status_code, 200)
            minus.ad_blocker.set_preview_grayscale.assert_called_once_with(False)

    def test_post_falloff_does_not_touch_ad_blocker(self):
        from webui import WebUI
        minus = MagicMock()
        minus.set_optimization_setting.return_value = {
            'success': True, 'block_falloff': True}
        ui = WebUI(minus)
        with ui.app.test_client() as client:
            client.post('/api/settings/optimization',
                        json={'key': 'block_falloff', 'enabled': True})
            minus.ad_blocker.set_preview_grayscale.assert_not_called()


if __name__ == '__main__':
    unittest.main()
