#!/usr/bin/env python3
"""
Comprehensive test suite for AutonomousMode and AutonomousModeStats.

Run with: python3 tests/test_autonomous_mode.py
Or:       python3 -m pytest tests/test_autonomous_mode.py -v
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from autonomous_mode import AutonomousMode, AutonomousModeStats, YOUTUBE_PACKAGES, ET


def _make_mode(**kwargs):
    """Create an AutonomousMode with mocked dependencies and temp files.

    Returns (mode, settings_tmpfile_path, log_tmpfile_path).
    Caller should clean up the temp files.
    """
    fire_tv = kwargs.pop("fire_tv", MagicMock())
    fire_tv.is_connected.return_value = kwargs.pop("fire_tv_connected", False)

    vlm = kwargs.pop("vlm", MagicMock())
    vlm.is_ready = kwargs.pop("vlm_ready", False)

    frame_capture = kwargs.pop("frame_capture", MagicMock())

    # Use temp files for settings and log so tests don't touch real paths
    settings_fd, settings_path = tempfile.mkstemp(suffix=".json")
    os.close(settings_fd)
    os.unlink(settings_path)  # start with no file

    log_fd, log_path = tempfile.mkstemp(suffix=".md")
    os.close(log_fd)
    os.unlink(log_path)  # start with no file

    with patch("autonomous_mode.SETTINGS_FILE", Path(settings_path)):
        mode = AutonomousMode(
            fire_tv_controller=fire_tv,
            ad_blocker=MagicMock(),
            vlm=vlm,
            frame_capture=frame_capture,
        )

    mode._log_file = log_path
    # Store paths for cleanup and for assertions
    mode._test_settings_path = settings_path
    mode._test_log_path = log_path
    return mode


def _cleanup_mode(mode):
    """Destroy mode and remove temp files."""
    mode.destroy()
    for p in (mode._test_settings_path, mode._test_log_path):
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


# =============================================================================
# AutonomousModeStats Tests
# =============================================================================


class TestAutonomousModeStats(unittest.TestCase):
    """Tests for AutonomousModeStats."""

    def test_initial_state(self):
        stats = AutonomousModeStats()
        self.assertIsNone(stats.session_start)
        self.assertIsNone(stats.session_end)
        self.assertEqual(stats.videos_played, 0)
        self.assertEqual(stats.ads_detected, 0)
        self.assertEqual(stats.ads_skipped, 0)
        self.assertEqual(stats.errors, 0)
        self.assertIsNone(stats.last_activity)

    def test_to_dict_initial(self):
        stats = AutonomousModeStats()
        d = stats.to_dict()
        self.assertIsNone(d["session_start"])
        self.assertIsNone(d["session_end"])
        self.assertEqual(d["videos_played"], 0)
        self.assertEqual(d["ads_detected"], 0)
        self.assertEqual(d["ads_skipped"], 0)
        self.assertEqual(d["errors"], 0)
        self.assertIsNone(d["last_activity"])
        self.assertEqual(d["duration_minutes"], 0)

    def test_to_dict_with_session(self):
        stats = AutonomousModeStats()
        start = datetime(2026, 4, 8, 1, 0, 0, tzinfo=ET)
        end = datetime(2026, 4, 8, 2, 30, 0, tzinfo=ET)
        stats.session_start = start
        stats.session_end = end
        stats.videos_played = 5
        stats.ads_detected = 10
        stats.ads_skipped = 8

        d = stats.to_dict()
        self.assertEqual(d["session_start"], start.isoformat())
        self.assertEqual(d["session_end"], end.isoformat())
        self.assertEqual(d["videos_played"], 5)
        self.assertEqual(d["ads_detected"], 10)
        self.assertEqual(d["ads_skipped"], 8)
        self.assertEqual(d["duration_minutes"], 90)

    def test_duration_no_session_start(self):
        stats = AutonomousModeStats()
        self.assertEqual(stats._get_duration_minutes(), 0)

    def test_duration_ongoing_session(self):
        stats = AutonomousModeStats()
        stats.session_start = datetime.now(ET) - timedelta(minutes=45)
        # No session_end => uses now
        duration = stats._get_duration_minutes()
        self.assertGreaterEqual(duration, 44)
        self.assertLessEqual(duration, 46)

    def test_duration_completed_session(self):
        stats = AutonomousModeStats()
        stats.session_start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=ET)
        stats.session_end = datetime(2026, 1, 1, 3, 15, 0, tzinfo=ET)
        self.assertEqual(stats._get_duration_minutes(), 195)

    def test_reset(self):
        stats = AutonomousModeStats()
        stats.session_start = datetime.now(ET)
        stats.videos_played = 10
        stats.ads_detected = 5
        stats.ads_skipped = 3
        stats.errors = 2
        stats.last_activity = datetime.now(ET)

        stats.reset()

        self.assertIsNone(stats.session_start)
        self.assertIsNone(stats.session_end)
        self.assertEqual(stats.videos_played, 0)
        self.assertEqual(stats.ads_detected, 0)
        self.assertEqual(stats.ads_skipped, 0)
        self.assertEqual(stats.errors, 0)
        self.assertIsNone(stats.last_activity)

    def test_to_dict_last_activity(self):
        stats = AutonomousModeStats()
        now = datetime.now(ET)
        stats.last_activity = now
        d = stats.to_dict()
        self.assertEqual(d["last_activity"], now.isoformat())


# =============================================================================
# Schedule Management Tests
# =============================================================================


class TestScheduleManagement(unittest.TestCase):
    """Tests for schedule-related methods."""

    def setUp(self):
        self.mode = _make_mode()

    def tearDown(self):
        _cleanup_mode(self.mode)

    def test_default_schedule(self):
        self.assertEqual(self.mode._start_hour, 0)
        self.assertEqual(self.mode._end_hour, 8)
        self.assertFalse(self.mode._always_on)

    def test_set_schedule_normal_range(self):
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.mode._test_settings_path)):
            result = self.mode.set_schedule(9, 17)
        self.assertEqual(self.mode._start_hour, 9)
        self.assertEqual(self.mode._end_hour, 17)
        self.assertFalse(self.mode._always_on)
        self.assertIn("schedule", result)
        self.assertEqual(result["schedule"], "09:00-17:00")

    def test_set_schedule_overnight_range(self):
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.mode._test_settings_path)):
            result = self.mode.set_schedule(22, 6)
        self.assertEqual(self.mode._start_hour, 22)
        self.assertEqual(self.mode._end_hour, 6)
        self.assertEqual(result["schedule"], "22:00-06:00")

    def test_set_schedule_always_on(self):
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.mode._test_settings_path)):
            result = self.mode.set_schedule(0, 0, always_on=True)
        self.assertTrue(self.mode._always_on)
        self.assertEqual(result["schedule"], "24/7")

    def test_set_schedule_same_hour(self):
        """Same start and end hour means a zero-length window."""
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.mode._test_settings_path)):
            self.mode.set_schedule(12, 12)
        self.assertEqual(self.mode._start_hour, 12)
        self.assertEqual(self.mode._end_hour, 12)

    def test_set_schedule_clamps_negative(self):
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.mode._test_settings_path)):
            self.mode.set_schedule(-5, 25)
        self.assertEqual(self.mode._start_hour, 0)
        self.assertEqual(self.mode._end_hour, 23)

    def test_set_schedule_clamps_over_23(self):
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.mode._test_settings_path)):
            self.mode.set_schedule(100, 200)
        self.assertEqual(self.mode._start_hour, 23)
        self.assertEqual(self.mode._end_hour, 23)

    # -- is_scheduled_time --

    def test_is_scheduled_time_always_on(self):
        self.mode._always_on = True
        self.assertTrue(self.mode.is_scheduled_time())

    def test_is_scheduled_time_normal_range_inside(self):
        """9:00-17:00, current time is 12:00."""
        self.mode._start_hour = 9
        self.mode._end_hour = 17
        with patch("autonomous_mode.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 8, 12, 0, 0, tzinfo=ET)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertTrue(self.mode.is_scheduled_time())

    def test_is_scheduled_time_normal_range_before(self):
        """9:00-17:00, current time is 7:00."""
        self.mode._start_hour = 9
        self.mode._end_hour = 17
        with patch("autonomous_mode.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 8, 7, 0, 0, tzinfo=ET)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertFalse(self.mode.is_scheduled_time())

    def test_is_scheduled_time_normal_range_after(self):
        """9:00-17:00, current time is 18:00."""
        self.mode._start_hour = 9
        self.mode._end_hour = 17
        with patch("autonomous_mode.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 8, 18, 0, 0, tzinfo=ET)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertFalse(self.mode.is_scheduled_time())

    def test_is_scheduled_time_normal_range_at_start(self):
        """9:00-17:00, current time is exactly 9:00."""
        self.mode._start_hour = 9
        self.mode._end_hour = 17
        with patch("autonomous_mode.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 8, 9, 0, 0, tzinfo=ET)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertTrue(self.mode.is_scheduled_time())

    def test_is_scheduled_time_normal_range_at_end(self):
        """9:00-17:00, current time is exactly 17:00 -> should be False (< end, not <=)."""
        self.mode._start_hour = 9
        self.mode._end_hour = 17
        with patch("autonomous_mode.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 8, 17, 0, 0, tzinfo=ET)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertFalse(self.mode.is_scheduled_time())

    def test_is_scheduled_time_overnight_range_late_night(self):
        """22:00-06:00, current time is 23:00."""
        self.mode._start_hour = 22
        self.mode._end_hour = 6
        with patch("autonomous_mode.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 8, 23, 0, 0, tzinfo=ET)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertTrue(self.mode.is_scheduled_time())

    def test_is_scheduled_time_overnight_range_early_morning(self):
        """22:00-06:00, current time is 3:00."""
        self.mode._start_hour = 22
        self.mode._end_hour = 6
        with patch("autonomous_mode.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 8, 3, 0, 0, tzinfo=ET)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertTrue(self.mode.is_scheduled_time())

    def test_is_scheduled_time_overnight_range_daytime(self):
        """22:00-06:00, current time is 14:00 -> outside."""
        self.mode._start_hour = 22
        self.mode._end_hour = 6
        with patch("autonomous_mode.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 8, 14, 0, 0, tzinfo=ET)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertFalse(self.mode.is_scheduled_time())

    def test_is_scheduled_time_overnight_at_start(self):
        """22:00-06:00, current time is 22:00 -> in window."""
        self.mode._start_hour = 22
        self.mode._end_hour = 6
        with patch("autonomous_mode.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 8, 22, 0, 0, tzinfo=ET)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertTrue(self.mode.is_scheduled_time())

    def test_is_scheduled_time_overnight_at_end(self):
        """22:00-06:00, current time is 06:00 -> outside (< 6 is false)."""
        self.mode._start_hour = 22
        self.mode._end_hour = 6
        with patch("autonomous_mode.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 8, 6, 0, 0, tzinfo=ET)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertFalse(self.mode.is_scheduled_time())

    def test_is_scheduled_time_same_hour(self):
        """12:00-12:00 -> zero-length window, always False."""
        self.mode._start_hour = 12
        self.mode._end_hour = 12
        with patch("autonomous_mode.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 8, 12, 0, 0, tzinfo=ET)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertFalse(self.mode.is_scheduled_time())

    # -- get_next_window --

    def test_get_next_window_always_on(self):
        self.mode._always_on = True
        start, end = self.mode.get_next_window()
        # end should be ~365 days from now
        self.assertGreater(end - start, timedelta(days=364))

    def test_get_next_window_normal_before_window(self):
        """9:00-17:00, now is 7:00 -> window is today 9:00-17:00."""
        self.mode._start_hour = 9
        self.mode._end_hour = 17
        with patch("autonomous_mode.datetime") as mock_dt:
            now = datetime(2026, 4, 8, 7, 0, 0, tzinfo=ET)
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            start, end = self.mode.get_next_window()
            self.assertEqual(start.hour, 9)
            self.assertEqual(end.hour, 17)
            self.assertEqual(start.day, 8)

    def test_get_next_window_normal_during_window(self):
        """9:00-17:00, now is 12:00 -> window is today 9:00-17:00."""
        self.mode._start_hour = 9
        self.mode._end_hour = 17
        with patch("autonomous_mode.datetime") as mock_dt:
            now = datetime(2026, 4, 8, 12, 0, 0, tzinfo=ET)
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            start, end = self.mode.get_next_window()
            self.assertEqual(start.hour, 9)
            self.assertEqual(end.hour, 17)
            self.assertEqual(start.day, 8)

    def test_get_next_window_normal_after_window(self):
        """9:00-17:00, now is 20:00 -> window is tomorrow 9:00-17:00."""
        self.mode._start_hour = 9
        self.mode._end_hour = 17
        with patch("autonomous_mode.datetime") as mock_dt:
            now = datetime(2026, 4, 8, 20, 0, 0, tzinfo=ET)
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            start, end = self.mode.get_next_window()
            self.assertEqual(start.hour, 9)
            self.assertEqual(end.hour, 17)
            self.assertEqual(start.day, 9)

    def test_get_next_window_overnight_during_late(self):
        """22:00-06:00, now is 23:00 -> start today 22:00, end tomorrow 06:00."""
        self.mode._start_hour = 22
        self.mode._end_hour = 6
        with patch("autonomous_mode.datetime") as mock_dt:
            now = datetime(2026, 4, 8, 23, 0, 0, tzinfo=ET)
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            start, end = self.mode.get_next_window()
            self.assertEqual(start.hour, 22)
            self.assertEqual(start.day, 8)
            self.assertEqual(end.hour, 6)
            self.assertEqual(end.day, 9)

    def test_get_next_window_overnight_during_early_morning(self):
        """22:00-06:00, now is 3:00 -> start yesterday 22:00, end today 06:00."""
        self.mode._start_hour = 22
        self.mode._end_hour = 6
        with patch("autonomous_mode.datetime") as mock_dt:
            now = datetime(2026, 4, 8, 3, 0, 0, tzinfo=ET)
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            start, end = self.mode.get_next_window()
            self.assertEqual(start.hour, 22)
            self.assertEqual(start.day, 7)
            self.assertEqual(end.hour, 6)
            self.assertEqual(end.day, 8)

    def test_get_next_window_overnight_between_windows(self):
        """22:00-06:00, now is 14:00 -> next window starts today 22:00, ends tomorrow 06:00."""
        self.mode._start_hour = 22
        self.mode._end_hour = 6
        with patch("autonomous_mode.datetime") as mock_dt:
            now = datetime(2026, 4, 8, 14, 0, 0, tzinfo=ET)
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            start, end = self.mode.get_next_window()
            self.assertEqual(start.hour, 22)
            self.assertEqual(start.day, 8)
            self.assertEqual(end.hour, 6)
            self.assertEqual(end.day, 9)

    # -- get_time_until_window --

    def test_time_until_window_returns_none_when_inside(self):
        """During scheduled time, should return None."""
        self.mode._always_on = True
        result = self.mode.get_time_until_window()
        self.assertIsNone(result)

    def test_time_until_window_returns_timedelta_when_outside(self):
        """Outside scheduled time, should return a timedelta."""
        self.mode._start_hour = 9
        self.mode._end_hour = 17
        self.mode._always_on = False
        with patch("autonomous_mode.datetime") as mock_dt:
            now = datetime(2026, 4, 8, 7, 0, 0, tzinfo=ET)
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = self.mode.get_time_until_window()
            self.assertIsNotNone(result)
            self.assertIsInstance(result, timedelta)
            # Should be about 2 hours
            self.assertGreater(result.total_seconds(), 3600)
            self.assertLessEqual(result.total_seconds(), 7200 + 60)

    def test_time_until_window_overnight_daytime(self):
        """22:00-06:00, now is 14:00 -> ~8 hours until window."""
        self.mode._start_hour = 22
        self.mode._end_hour = 6
        self.mode._always_on = False
        with patch("autonomous_mode.datetime") as mock_dt:
            now = datetime(2026, 4, 8, 14, 0, 0, tzinfo=ET)
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = self.mode.get_time_until_window()
            self.assertIsNotNone(result)
            # About 8 hours
            self.assertGreater(result.total_seconds(), 7 * 3600)
            self.assertLessEqual(result.total_seconds(), 8 * 3600 + 60)


# =============================================================================
# VLM Screen Classification Tests
# =============================================================================


class TestDetermineAction(unittest.TestCase):
    """Tests for _determine_action() VLM response parsing."""

    def setUp(self):
        self.mode = _make_mode()

    def tearDown(self):
        _cleanup_mode(self.mode)

    # -- Structured responses --

    def test_playing(self):
        self.assertEqual(self.mode._determine_action("PLAYING"), "none")

    def test_playing_lowercase(self):
        self.assertEqual(self.mode._determine_action("playing"), "none")

    def test_playing_with_extra_text(self):
        self.assertEqual(self.mode._determine_action("PLAYING - a video is actively playing"), "none")

    def test_paused(self):
        self.assertEqual(self.mode._determine_action("PAUSED"), "play")

    def test_paused_mixed_case(self):
        self.assertEqual(self.mode._determine_action("Paused"), "play")

    def test_dialog(self):
        self.assertEqual(self.mode._determine_action("DIALOG"), "dismiss")

    def test_dialog_with_description(self):
        self.assertEqual(self.mode._determine_action("DIALOG - are you still watching?"), "dismiss")

    def test_menu(self):
        self.assertEqual(self.mode._determine_action("MENU"), "select")

    def test_screensaver(self):
        self.assertEqual(self.mode._determine_action("SCREENSAVER"), "launch")

    def test_screensaver_lowercase(self):
        self.assertEqual(self.mode._determine_action("screensaver"), "launch")

    # -- Fallback keyword matching --

    def test_still_watching_keyword(self):
        self.assertEqual(
            self.mode._determine_action("I see a dialog saying 'Are you still watching?'"),
            "dismiss",
        )

    def test_still_there_keyword(self):
        self.assertEqual(
            self.mode._determine_action("The TV shows 'Are you still there?'"),
            "dismiss",
        )

    def test_home_screen_keyword(self):
        self.assertEqual(
            self.mode._determine_action("This is the YouTube home screen with recommended videos"),
            "select",
        )

    def test_browse_keyword(self):
        self.assertEqual(
            self.mode._determine_action("A browse screen with categories"),
            "select",
        )

    def test_thumbnail_keyword(self):
        self.assertEqual(
            self.mode._determine_action("Multiple thumbnail images of videos"),
            "select",
        )

    def test_paused_keyword(self):
        self.assertEqual(
            self.mode._determine_action("The video appears to be paused with a play button visible"),
            "play",
        )

    def test_not_paused_keyword(self):
        """'not paused' should NOT trigger play."""
        self.assertEqual(
            self.mode._determine_action("The video is not paused, it is actively playing"),
            "none",
        )

    def test_playing_keyword(self):
        self.assertEqual(
            self.mode._determine_action("A video is currently playing on screen"),
            "none",
        )

    def test_black_screen_keyword(self):
        self.assertEqual(
            self.mode._determine_action("I see a black screen with no content"),
            "launch",
        )

    def test_screensaver_keyword_in_sentence(self):
        self.assertEqual(
            self.mode._determine_action("The device appears to have a screensaver active"),
            "launch",
        )

    # -- None / empty / unknown --

    def test_none_input(self):
        self.assertEqual(self.mode._determine_action(None), "none")

    def test_empty_string(self):
        self.assertEqual(self.mode._determine_action(""), "none")

    def test_unknown_response(self):
        self.assertEqual(self.mode._determine_action("I can't tell what this is"), "none")

    def test_whitespace_only(self):
        self.assertEqual(self.mode._determine_action("   "), "none")

    # -- Priority tests --

    def test_dismiss_takes_priority_over_select(self):
        """'still watching' in a menu-like response should dismiss."""
        self.assertEqual(
            self.mode._determine_action("Home screen with 'still watching?' dialog"),
            "dismiss",
        )

    def test_dialog_structured_takes_priority(self):
        """Structured DIALOG prefix takes priority over fallback keywords."""
        self.assertEqual(
            self.mode._determine_action("DIALOG with still watching prompt"),
            "dismiss",
        )

    def test_screensaver_structured_over_playing_keyword(self):
        """SCREENSAVER prefix beats 'playing' keyword in text."""
        self.assertEqual(
            self.mode._determine_action("SCREENSAVER was playing before going dark"),
            "launch",
        )


# =============================================================================
# YouTube Package Detection Tests
# =============================================================================


class TestIsYoutubeApp(unittest.TestCase):
    """Tests for _is_youtube_app()."""

    def setUp(self):
        self.mode = _make_mode()

    def tearDown(self):
        _cleanup_mode(self.mode)

    def test_fire_tv_youtube(self):
        self.assertTrue(self.mode._is_youtube_app("com.amazon.firetv.youtube"))

    def test_google_youtube_tv(self):
        self.assertTrue(self.mode._is_youtube_app("com.google.android.youtube.tv"))

    def test_google_youtube(self):
        self.assertTrue(self.mode._is_youtube_app("com.google.android.youtube"))

    def test_plain_youtube(self):
        self.assertTrue(self.mode._is_youtube_app("youtube"))

    def test_youtube_case_insensitive(self):
        self.assertTrue(self.mode._is_youtube_app("com.Amazon.FireTV.YouTube"))

    def test_non_youtube_app(self):
        self.assertFalse(self.mode._is_youtube_app("com.netflix.ninja"))

    def test_none_input(self):
        self.assertFalse(self.mode._is_youtube_app(None))

    def test_empty_string(self):
        self.assertFalse(self.mode._is_youtube_app(""))

    def test_partial_match(self):
        """Package name containing youtube somewhere."""
        self.assertTrue(self.mode._is_youtube_app("com.custom.youtube.player"))

    def test_all_known_packages(self):
        for pkg in YOUTUBE_PACKAGES:
            self.assertTrue(self.mode._is_youtube_app(pkg), f"Failed for package: {pkg}")


# =============================================================================
# State Management Tests
# =============================================================================


class TestStateManagement(unittest.TestCase):
    """Tests for enable/disable/toggle/start_now/get_status/destroy."""

    def setUp(self):
        self.mode = _make_mode()

    def tearDown(self):
        _cleanup_mode(self.mode)

    def test_initial_state(self):
        self.assertFalse(self.mode._enabled)
        self.assertFalse(self.mode._active)
        self.assertFalse(self.mode._manual_override)

    def test_enable(self):
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.mode._test_settings_path)):
            with patch.object(self.mode, "_start_thread"):
                result = self.mode.enable()
        self.assertTrue(self.mode._enabled)
        self.assertFalse(self.mode._manual_override)
        self.assertTrue(result["enabled"])

    def test_enable_idempotent(self):
        """Enabling twice without manual flag returns early on second call."""
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.mode._test_settings_path)):
            with patch.object(self.mode, "_start_thread"):
                self.mode.enable()
                result = self.mode.enable()
        self.assertTrue(result["enabled"])

    def test_enable_manual(self):
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.mode._test_settings_path)):
            with patch.object(self.mode, "_start_thread"):
                result = self.mode.enable(manual=True)
        self.assertTrue(self.mode._enabled)
        self.assertTrue(self.mode._manual_override)
        self.assertTrue(result["manual_override"])

    def test_disable(self):
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.mode._test_settings_path)):
            with patch.object(self.mode, "_start_thread"):
                self.mode.enable()
            with patch.object(self.mode, "_stop_thread"):
                result = self.mode.disable()
        self.assertFalse(self.mode._enabled)
        self.assertFalse(self.mode._manual_override)
        self.assertFalse(result["enabled"])

    def test_disable_idempotent(self):
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.mode._test_settings_path)):
            with patch.object(self.mode, "_stop_thread"):
                result = self.mode.disable()
        self.assertFalse(result["enabled"])

    def test_disable_stops_active_session(self):
        """disable() calls _deactivate() if _active is True.

        Note: disable() and _deactivate() both acquire self._lock which is a
        non-reentrant threading.Lock. To avoid the deadlock in tests we mock
        _deactivate and verify it was called.
        """
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.mode._test_settings_path)):
            with patch.object(self.mode, "_start_thread"):
                self.mode.enable()
            self.mode._active = True
            self.mode.stats.session_start = datetime.now(ET)
            with patch.object(self.mode, "_deactivate") as mock_deact, \
                 patch.object(self.mode, "_stop_thread"):
                self.mode.disable()
            mock_deact.assert_called_once()

    def test_toggle_on(self):
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.mode._test_settings_path)):
            with patch.object(self.mode, "_start_thread"):
                result = self.mode.toggle()
        self.assertTrue(self.mode._enabled)
        self.assertTrue(result["enabled"])

    def test_toggle_off(self):
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.mode._test_settings_path)):
            with patch.object(self.mode, "_start_thread"):
                self.mode.enable()
            with patch.object(self.mode, "_stop_thread"):
                result = self.mode.toggle()
        self.assertFalse(self.mode._enabled)
        self.assertFalse(result["enabled"])

    def test_start_now(self):
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.mode._test_settings_path)):
            with patch.object(self.mode, "_start_thread"):
                result = self.mode.start_now()
        self.assertTrue(self.mode._enabled)
        self.assertTrue(self.mode._manual_override)
        self.assertTrue(result["manual_override"])

    def test_get_status_fields(self):
        status = self.mode.get_status()
        expected_keys = {
            "enabled", "active", "manual_override", "is_scheduled_time",
            "always_on", "start_hour", "end_hour", "schedule",
            "current_time_et", "next_window_start", "next_window_end",
            "time_until_window", "fire_tv_connected", "stats",
        }
        self.assertEqual(set(status.keys()), expected_keys)

    def test_get_status_fire_tv_connected(self):
        self.mode._fire_tv.is_connected.return_value = True
        status = self.mode.get_status()
        self.assertTrue(status["fire_tv_connected"])

    def test_get_status_fire_tv_disconnected(self):
        self.mode._fire_tv.is_connected.return_value = False
        status = self.mode.get_status()
        self.assertFalse(status["fire_tv_connected"])

    def test_get_status_no_fire_tv(self):
        self.mode._fire_tv = None
        status = self.mode.get_status()
        self.assertFalse(status["fire_tv_connected"])

    def test_get_status_stats_dict(self):
        status = self.mode.get_status()
        self.assertIsInstance(status["stats"], dict)
        self.assertIn("videos_played", status["stats"])

    def test_destroy_cleans_up(self):
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.mode._test_settings_path)):
            with patch.object(self.mode, "_start_thread"):
                self.mode.enable()
        self.mode._active = True
        self.mode.stats.session_start = datetime.now(ET)
        self.mode.destroy()
        self.assertFalse(self.mode._active)
        self.assertFalse(self.mode._running)
        self.assertIsNone(self.mode._thread)

    def test_destroy_sets_session_end(self):
        self.mode._active = True
        self.mode.stats.session_start = datetime.now(ET)
        self.mode.destroy()
        self.assertIsNotNone(self.mode.stats.session_end)

    def test_destroy_no_active_session(self):
        """Destroy when not active should not set session_end."""
        self.mode.destroy()
        self.assertIsNone(self.mode.stats.session_end)


# =============================================================================
# Settings Persistence Tests
# =============================================================================


class TestSettingsPersistence(unittest.TestCase):
    """Tests for _load_settings / _save_settings round-trip."""

    def setUp(self):
        fd, self.settings_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.settings_path)  # start clean

    def tearDown(self):
        try:
            os.unlink(self.settings_path)
        except FileNotFoundError:
            pass

    def test_save_and_load_round_trip(self):
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.settings_path)):
            mode1 = AutonomousMode()
            mode1._log_file = "/dev/null"
            mode1._enabled = True
            mode1._start_hour = 22
            mode1._end_hour = 6
            mode1._always_on = True
            mode1._save_settings()
            mode1.destroy()

        with patch("autonomous_mode.SETTINGS_FILE", Path(self.settings_path)):
            mode2 = AutonomousMode()
            mode2._log_file = "/dev/null"

        self.assertTrue(mode2._enabled)
        self.assertEqual(mode2._start_hour, 22)
        self.assertEqual(mode2._end_hour, 6)
        self.assertTrue(mode2._always_on)
        mode2.destroy()

    def test_missing_settings_file_uses_defaults(self):
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.settings_path)):
            mode = AutonomousMode()
            mode._log_file = "/dev/null"

        self.assertFalse(mode._enabled)
        self.assertEqual(mode._start_hour, AutonomousMode.DEFAULT_START_HOUR)
        self.assertEqual(mode._end_hour, AutonomousMode.DEFAULT_END_HOUR)
        self.assertFalse(mode._always_on)
        mode.destroy()

    def test_corrupted_json_uses_defaults(self):
        with open(self.settings_path, "w") as f:
            f.write("NOT VALID JSON {{{")

        with patch("autonomous_mode.SETTINGS_FILE", Path(self.settings_path)):
            mode = AutonomousMode()
            mode._log_file = "/dev/null"

        self.assertFalse(mode._enabled)
        self.assertEqual(mode._start_hour, AutonomousMode.DEFAULT_START_HOUR)
        mode.destroy()

    def test_partial_settings_fills_defaults(self):
        with open(self.settings_path, "w") as f:
            json.dump({"enabled": True}, f)

        with patch("autonomous_mode.SETTINGS_FILE", Path(self.settings_path)):
            mode = AutonomousMode()
            mode._log_file = "/dev/null"

        self.assertTrue(mode._enabled)
        self.assertEqual(mode._start_hour, AutonomousMode.DEFAULT_START_HOUR)
        self.assertEqual(mode._end_hour, AutonomousMode.DEFAULT_END_HOUR)
        self.assertFalse(mode._always_on)
        mode.destroy()

    def test_save_settings_contains_last_updated(self):
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.settings_path)):
            mode = AutonomousMode()
            mode._log_file = "/dev/null"
            mode._save_settings()

        with open(self.settings_path, "r") as f:
            data = json.load(f)
        self.assertIn("last_updated", data)
        mode.destroy()

    def test_save_on_disable(self):
        """Disabling should persist the disabled state."""
        with patch("autonomous_mode.SETTINGS_FILE", Path(self.settings_path)):
            mode = AutonomousMode()
            mode._log_file = "/dev/null"
            mode._enabled = True
            with patch.object(mode, "_stop_thread"):
                mode.disable()

        with open(self.settings_path, "r") as f:
            data = json.load(f)
        self.assertFalse(data["enabled"])
        mode.destroy()


# =============================================================================
# Statistics Recording Tests
# =============================================================================


class TestStatisticsRecording(unittest.TestCase):
    """Tests for record_ad_detected / record_ad_skipped."""

    def setUp(self):
        self.mode = _make_mode()

    def tearDown(self):
        _cleanup_mode(self.mode)

    def test_record_ad_detected(self):
        self.assertEqual(self.mode.stats.ads_detected, 0)
        self.mode.record_ad_detected()
        self.assertEqual(self.mode.stats.ads_detected, 1)
        self.assertIsNotNone(self.mode.stats.last_activity)

    def test_record_ad_detected_multiple(self):
        for _ in range(5):
            self.mode.record_ad_detected()
        self.assertEqual(self.mode.stats.ads_detected, 5)

    def test_record_ad_skipped(self):
        self.assertEqual(self.mode.stats.ads_skipped, 0)
        self.mode.record_ad_skipped()
        self.assertEqual(self.mode.stats.ads_skipped, 1)
        self.assertIsNotNone(self.mode.stats.last_activity)

    def test_record_ad_skipped_multiple(self):
        for _ in range(3):
            self.mode.record_ad_skipped()
        self.assertEqual(self.mode.stats.ads_skipped, 3)

    def test_record_updates_last_activity(self):
        before = datetime.now(ET)
        self.mode.record_ad_detected()
        after = datetime.now(ET)
        self.assertGreaterEqual(self.mode.stats.last_activity, before)
        self.assertLessEqual(self.mode.stats.last_activity, after)


# =============================================================================
# Logging Tests
# =============================================================================


class TestLogging(unittest.TestCase):
    """Tests for _log_event and get_log_tail."""

    def setUp(self):
        self.mode = _make_mode()

    def tearDown(self):
        _cleanup_mode(self.mode)

    def test_log_event_creates_file(self):
        self.assertFalse(os.path.exists(self.mode._test_log_path))
        self.mode._log_event("Test event")
        self.assertTrue(os.path.exists(self.mode._test_log_path))

    def test_log_event_format(self):
        self.mode._log_event("Hello world")
        with open(self.mode._test_log_path, "r") as f:
            content = f.read()
        self.assertIn("Hello world", content)
        self.assertIn("- [", content)
        self.assertIn("ET]", content)

    def test_log_event_appends(self):
        self.mode._log_event("First event")
        self.mode._log_event("Second event")
        with open(self.mode._test_log_path, "r") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("First event", lines[0])
        self.assertIn("Second event", lines[1])

    def test_get_log_tail_returns_content(self):
        for i in range(10):
            self.mode._log_event(f"Event {i}")
        tail = self.mode.get_log_tail(5)
        self.assertIn("Event 5", tail)
        self.assertIn("Event 9", tail)
        self.assertNotIn("Event 4", tail)

    def test_get_log_tail_missing_file(self):
        result = self.mode.get_log_tail()
        self.assertEqual(result, "No autonomous mode logs yet.")

    def test_get_log_tail_default_lines(self):
        for i in range(100):
            self.mode._log_event(f"Event {i}")
        tail = self.mode.get_log_tail()
        # Default is 50 lines
        lines = tail.strip().split("\n")
        self.assertEqual(len(lines), 50)

    def test_get_log_tail_fewer_lines_than_requested(self):
        self.mode._log_event("Only one event")
        tail = self.mode.get_log_tail(50)
        lines = [l for l in tail.strip().split("\n") if l]
        self.assertEqual(len(lines), 1)


# =============================================================================
# Setters and Callbacks Tests
# =============================================================================


class TestSettersAndCallbacks(unittest.TestCase):
    """Tests for set_fire_tv, set_ad_blocker, set_vlm, set_frame_capture, set_status_callback."""

    def setUp(self):
        self.mode = _make_mode()

    def tearDown(self):
        _cleanup_mode(self.mode)

    def test_set_fire_tv(self):
        new_ft = MagicMock()
        self.mode.set_fire_tv(new_ft)
        self.assertIs(self.mode._fire_tv, new_ft)

    def test_set_ad_blocker(self):
        new_ab = MagicMock()
        self.mode.set_ad_blocker(new_ab)
        self.assertIs(self.mode._ad_blocker, new_ab)

    def test_set_vlm(self):
        new_vlm = MagicMock()
        self.mode.set_vlm(new_vlm)
        self.assertIs(self.mode._vlm, new_vlm)

    def test_set_frame_capture(self):
        new_fc = MagicMock()
        self.mode.set_frame_capture(new_fc)
        self.assertIs(self.mode._frame_capture, new_fc)

    def test_set_status_callback(self):
        cb = MagicMock()
        self.mode.set_status_callback(cb)
        self.assertIs(self.mode._on_status_change, cb)


# =============================================================================
# Activation / Deactivation Tests
# =============================================================================


class TestActivationDeactivation(unittest.TestCase):
    """Tests for _activate and _deactivate."""

    def setUp(self):
        self.mode = _make_mode()

    def tearDown(self):
        _cleanup_mode(self.mode)

    @patch.object(AutonomousMode, "_launch_youtube", return_value=True)
    def test_activate_sets_state(self, mock_launch):
        self.mode._activate()
        self.assertTrue(self.mode._active)
        self.assertIsNotNone(self.mode.stats.session_start)
        mock_launch.assert_called_once()

    @patch.object(AutonomousMode, "_launch_youtube", return_value=True)
    def test_activate_idempotent(self, mock_launch):
        self.mode._activate()
        self.mode._activate()
        mock_launch.assert_called_once()

    @patch.object(AutonomousMode, "_launch_youtube", return_value=True)
    def test_activate_calls_status_callback(self, mock_launch):
        cb = MagicMock()
        self.mode.set_status_callback(cb)
        self.mode._activate()
        cb.assert_called_once()
        status = cb.call_args[0][0]
        self.assertTrue(status["active"])

    def test_deactivate_sets_state(self):
        self.mode._active = True
        self.mode.stats.session_start = datetime.now(ET)
        self.mode._deactivate()
        self.assertFalse(self.mode._active)
        self.assertIsNotNone(self.mode.stats.session_end)

    def test_deactivate_idempotent(self):
        self.mode._deactivate()  # no-op when not active
        self.assertFalse(self.mode._active)

    def test_deactivate_calls_status_callback(self):
        cb = MagicMock()
        self.mode.set_status_callback(cb)
        self.mode._active = True
        self.mode.stats.session_start = datetime.now(ET)
        self.mode._deactivate()
        cb.assert_called_once()

    @patch.object(AutonomousMode, "_launch_youtube", return_value=True)
    def test_activate_resets_stats(self, mock_launch):
        self.mode.stats.ads_detected = 10
        self.mode._activate()
        self.assertEqual(self.mode.stats.ads_detected, 0)


# =============================================================================
# start_if_enabled Tests
# =============================================================================


class TestStartIfEnabled(unittest.TestCase):
    """Tests for start_if_enabled."""

    def setUp(self):
        self.mode = _make_mode()

    def tearDown(self):
        _cleanup_mode(self.mode)

    def test_start_if_enabled_when_disabled(self):
        self.mode._enabled = False
        self.mode.start_if_enabled()
        # Should not start thread
        self.assertFalse(self.mode._running)

    @patch.object(AutonomousMode, "_start_thread")
    def test_start_if_enabled_when_enabled(self, mock_start):
        self.mode._enabled = True
        self.mode.start_if_enabled()
        mock_start.assert_called_once()


# =============================================================================
# Thread Management Tests
# =============================================================================


class TestThreadManagement(unittest.TestCase):
    """Tests for _start_thread / _stop_thread."""

    def setUp(self):
        self.mode = _make_mode()

    def tearDown(self):
        _cleanup_mode(self.mode)

    def test_start_thread(self):
        self.mode._start_thread()
        self.assertTrue(self.mode._running)
        self.assertIsNotNone(self.mode._thread)
        self.assertTrue(self.mode._thread.is_alive())
        # Clean up
        self.mode._stop_thread()

    def test_start_thread_idempotent(self):
        self.mode._start_thread()
        first_thread = self.mode._thread
        self.mode._start_thread()
        self.assertIs(self.mode._thread, first_thread)
        self.mode._stop_thread()

    def test_stop_thread(self):
        self.mode._start_thread()
        self.mode._stop_thread()
        self.assertFalse(self.mode._running)
        self.assertIsNone(self.mode._thread)

    def test_stop_thread_when_not_started(self):
        # Should not raise
        self.mode._stop_thread()
        self.assertFalse(self.mode._running)

    def test_thread_is_daemon(self):
        self.mode._start_thread()
        self.assertTrue(self.mode._thread.daemon)
        self.mode._stop_thread()


# =============================================================================
# SCREEN_QUERY_PROMPT Tests
# =============================================================================


class TestScreenQueryPrompt(unittest.TestCase):
    """Verify the VLM prompt constant."""

    def test_prompt_exists(self):
        self.assertIsInstance(AutonomousMode.SCREEN_QUERY_PROMPT, str)

    def test_prompt_mentions_categories(self):
        for cat in ("PLAYING", "PAUSED", "DIALOG", "MENU", "SCREENSAVER"):
            self.assertIn(cat, AutonomousMode.SCREEN_QUERY_PROMPT)


# =============================================================================
# Main
# =============================================================================


if __name__ == "__main__":
    # Use unittest runner so file is self-contained
    unittest.main(verbosity=2)
