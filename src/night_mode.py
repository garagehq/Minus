"""
Autonomous Mode for Minus - Automated YouTube playback for training data collection.

Configurable schedule with support for 24/7 operation. Keeps YouTube playing
on Fire TV to collect ad detection training data.
"""

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Settings file for persistence (use absolute path to work regardless of running user)
SETTINGS_FILE = Path("/home/radxa/.minus_autonomous_mode.json")

# Eastern timezone (default, but schedule hours are timezone-agnostic for simplicity)
ET = ZoneInfo("America/New_York")

# YouTube package name
YOUTUBE_PACKAGE = "com.amazon.firetv.youtube"

# Timing constants
CHECK_INTERVAL = 60.0          # Check every minute
KEEPALIVE_INTERVAL = 300.0     # Keep YouTube active every 5 minutes


class AutonomousModeStats:
    """Statistics for autonomous mode session."""

    def __init__(self):
        self.session_start: Optional[datetime] = None
        self.session_end: Optional[datetime] = None
        self.videos_played = 0
        self.ads_detected = 0
        self.ads_skipped = 0
        self.errors = 0
        self.last_activity: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "session_start": self.session_start.isoformat() if self.session_start else None,
            "session_end": self.session_end.isoformat() if self.session_end else None,
            "videos_played": self.videos_played,
            "ads_detected": self.ads_detected,
            "ads_skipped": self.ads_skipped,
            "errors": self.errors,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
            "duration_minutes": self._get_duration_minutes(),
        }

    def _get_duration_minutes(self) -> int:
        if not self.session_start:
            return 0
        end = self.session_end or datetime.now(ET)
        return int((end - self.session_start).total_seconds() / 60)

    def reset(self):
        """Reset stats for new session."""
        self.__init__()


class NightMode:
    """
    Autonomous Mode controller for automated operation.

    Features:
    - Configurable schedule (start/end hours, or 24/7 mode)
    - Manual enable/disable toggle
    - Keeps YouTube playing on Fire TV
    - Tracks statistics
    - Integrates with ad blocking system
    """

    # Default schedule
    DEFAULT_START_HOUR = 0   # Midnight
    DEFAULT_END_HOUR = 8     # 8 AM

    def __init__(self, fire_tv_controller=None, ad_blocker=None):
        """
        Initialize autonomous mode.

        Args:
            fire_tv_controller: FireTVController instance for device control
            ad_blocker: DRMAdBlocker instance for ad detection stats
        """
        self._fire_tv = fire_tv_controller
        self._ad_blocker = ad_blocker

        # State
        self._enabled = False          # User toggle
        self._active = False           # Currently in active window
        self._running = False          # Thread running
        self._manual_override = False  # User manually started outside schedule

        # Schedule (configurable)
        self._start_hour = self.DEFAULT_START_HOUR
        self._end_hour = self.DEFAULT_END_HOUR
        self._always_on = False        # 24/7 mode

        # Thread management
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # Stats
        self.stats = AutonomousModeStats()

        # Callbacks
        self._on_status_change: Optional[Callable[[dict], None]] = None

        # Logging
        self._log_file = "/home/radxa/Minus/autonomous-mode-logs.md"

        # Load persisted settings
        self._load_settings()

    def _load_settings(self):
        """Load persisted autonomous mode settings."""
        try:
            if SETTINGS_FILE.exists():
                with open(SETTINGS_FILE, "r") as f:
                    settings = json.load(f)
                    self._enabled = settings.get("enabled", False)
                    self._start_hour = settings.get("start_hour", self.DEFAULT_START_HOUR)
                    self._end_hour = settings.get("end_hour", self.DEFAULT_END_HOUR)
                    self._always_on = settings.get("always_on", False)
                    logger.info(f"[AutonomousMode] Loaded settings: enabled={self._enabled}, "
                               f"schedule={self._start_hour}:00-{self._end_hour}:00, always_on={self._always_on}")
        except Exception as e:
            logger.warning(f"[AutonomousMode] Could not load settings: {e}")

    def _save_settings(self):
        """Save autonomous mode settings to disk."""
        try:
            settings = {
                "enabled": self._enabled,
                "start_hour": self._start_hour,
                "end_hour": self._end_hour,
                "always_on": self._always_on,
                "last_updated": datetime.now(ET).isoformat(),
            }
            with open(SETTINGS_FILE, "w") as f:
                json.dump(settings, f)
            logger.debug(f"[AutonomousMode] Settings saved")
        except Exception as e:
            logger.warning(f"[AutonomousMode] Could not save settings: {e}")

    def set_fire_tv(self, controller):
        """Set Fire TV controller reference."""
        self._fire_tv = controller

    def set_ad_blocker(self, blocker):
        """Set ad blocker reference."""
        self._ad_blocker = blocker

    def set_status_callback(self, callback: Callable[[dict], None]):
        """Set callback for status changes."""
        self._on_status_change = callback

    def start_if_enabled(self):
        """Start monitoring thread if autonomous mode was enabled (called on startup)."""
        if self._enabled:
            logger.info("[AutonomousMode] Autonomous mode was enabled, starting monitoring thread")
            self._start_thread()

    def set_schedule(self, start_hour: int, end_hour: int, always_on: bool = False) -> dict:
        """
        Set the autonomous mode schedule.

        Args:
            start_hour: Hour to start (0-23)
            end_hour: Hour to end (0-23)
            always_on: If True, run 24/7 regardless of hours

        Returns:
            Status dict
        """
        with self._lock:
            # Validate hours
            start_hour = max(0, min(23, start_hour))
            end_hour = max(0, min(23, end_hour))

            self._start_hour = start_hour
            self._end_hour = end_hour
            self._always_on = always_on

            self._save_settings()

            schedule_desc = "24/7" if always_on else f"{start_hour}:00-{end_hour}:00"
            logger.info(f"[AutonomousMode] Schedule set to {schedule_desc}")
            self._log_event(f"Schedule changed to {schedule_desc}")

            return self.get_status()

    def is_scheduled_time(self) -> bool:
        """Check if current time is within the scheduled window."""
        if self._always_on:
            return True

        now = datetime.now(ET)
        current_hour = now.hour

        if self._start_hour <= self._end_hour:
            # Normal range (e.g., 9:00 to 17:00)
            return self._start_hour <= current_hour < self._end_hour
        else:
            # Overnight range (e.g., 22:00 to 6:00)
            return current_hour >= self._start_hour or current_hour < self._end_hour

    def get_next_window(self) -> tuple[datetime, datetime]:
        """Get the next autonomous mode window (start, end) in ET."""
        now = datetime.now(ET)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if self._always_on:
            # Always on - window is now to forever
            return now, now + timedelta(days=365)

        start_today = today.replace(hour=self._start_hour)
        end_today = today.replace(hour=self._end_hour)

        if self._start_hour <= self._end_hour:
            # Normal range
            if now < start_today:
                return start_today, end_today
            elif now < end_today:
                return start_today, end_today
            else:
                # Next window is tomorrow
                tomorrow = today + timedelta(days=1)
                return tomorrow.replace(hour=self._start_hour), tomorrow.replace(hour=self._end_hour)
        else:
            # Overnight range (e.g., 22:00 to 6:00)
            if now.hour >= self._start_hour:
                # Currently after start, end is tomorrow
                tomorrow = today + timedelta(days=1)
                return start_today, tomorrow.replace(hour=self._end_hour)
            elif now.hour < self._end_hour:
                # Currently before end (early morning)
                yesterday = today - timedelta(days=1)
                return yesterday.replace(hour=self._start_hour), end_today
            else:
                # Between end and start, next window starts today
                return start_today, (today + timedelta(days=1)).replace(hour=self._end_hour)

    def get_time_until_window(self) -> Optional[timedelta]:
        """Get time until next window starts. None if currently in window."""
        if self.is_scheduled_time():
            return None

        start, _ = self.get_next_window()
        now = datetime.now(ET)
        if start > now:
            return start - now
        return None

    def enable(self, manual: bool = False) -> dict:
        """
        Enable autonomous mode.

        Args:
            manual: If True, start immediately regardless of schedule

        Returns:
            Status dict
        """
        with self._lock:
            if self._enabled and not manual:
                return self.get_status()

            self._enabled = True
            self._manual_override = manual

            # Persist setting
            self._save_settings()

            logger.info(f"[AutonomousMode] Enabled (manual={manual})")
            self._log_event("Autonomous mode ENABLED" + (" (manual)" if manual else " (scheduled)"))

            # Start the monitoring thread
            self._start_thread()

            return self.get_status()

    def disable(self) -> dict:
        """Disable autonomous mode."""
        with self._lock:
            if not self._enabled:
                return self.get_status()

            self._enabled = False
            self._manual_override = False

            # Persist setting
            self._save_settings()

            # Stop if running
            if self._active:
                self._deactivate()

            self._stop_thread()

            logger.info("[AutonomousMode] Disabled")
            self._log_event("Autonomous mode DISABLED")

            return self.get_status()

    def toggle(self) -> dict:
        """Toggle autonomous mode on/off."""
        if self._enabled:
            return self.disable()
        else:
            return self.enable()

    def start_now(self) -> dict:
        """Start autonomous mode immediately, regardless of schedule."""
        return self.enable(manual=True)

    def get_status(self) -> dict:
        """Get current autonomous mode status."""
        is_scheduled = self.is_scheduled_time()
        next_start, next_end = self.get_next_window()
        time_until = self.get_time_until_window()

        schedule_str = "24/7" if self._always_on else f"{self._start_hour:02d}:00-{self._end_hour:02d}:00"

        return {
            "enabled": self._enabled,
            "active": self._active,
            "manual_override": self._manual_override,
            "is_scheduled_time": is_scheduled,
            "always_on": self._always_on,
            "start_hour": self._start_hour,
            "end_hour": self._end_hour,
            "schedule": schedule_str,
            "current_time_et": datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S"),
            "next_window_start": next_start.strftime("%Y-%m-%d %H:%M:%S") if not self._always_on else None,
            "next_window_end": next_end.strftime("%Y-%m-%d %H:%M:%S") if not self._always_on else None,
            "time_until_window": str(time_until).split(".")[0] if time_until else None,
            "fire_tv_connected": self._fire_tv.is_connected() if self._fire_tv else False,
            "stats": self.stats.to_dict(),
        }

    def _start_thread(self):
        """Start the autonomous mode monitoring thread."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="AutonomousMode",
            daemon=True
        )
        self._thread.start()

    def _stop_thread(self):
        """Stop the monitoring thread."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _run_loop(self):
        """Main autonomous mode loop."""
        logger.info("[AutonomousMode] Monitoring thread started")

        last_keepalive = 0

        while self._running and not self._stop_event.is_set():
            try:
                should_be_active = self._manual_override or self.is_scheduled_time()

                if should_be_active and not self._active:
                    # Activate autonomous mode
                    self._activate()
                elif not should_be_active and self._active and not self._manual_override:
                    # Deactivate (only if not manual override)
                    self._deactivate()

                if self._active:
                    # Keep YouTube running
                    now = time.time()
                    if now - last_keepalive > KEEPALIVE_INTERVAL:
                        self._ensure_youtube_playing()
                        last_keepalive = now

                # Update stats
                if self._active:
                    self.stats.last_activity = datetime.now(ET)

            except Exception as e:
                logger.error(f"[AutonomousMode] Loop error: {e}")
                self.stats.errors += 1

            # Wait for next check
            self._stop_event.wait(CHECK_INTERVAL)

        logger.info("[AutonomousMode] Monitoring thread stopped")

    def _activate(self):
        """Activate autonomous mode session."""
        with self._lock:
            if self._active:
                return

            self._active = True
            self.stats.reset()
            self.stats.session_start = datetime.now(ET)

            logger.info("[AutonomousMode] Session STARTED")
            self._log_event("Session STARTED")

            # Launch YouTube
            self._launch_youtube()

            # Notify status change
            if self._on_status_change:
                self._on_status_change(self.get_status())

    def _deactivate(self):
        """Deactivate autonomous mode session."""
        with self._lock:
            if not self._active:
                return

            self._active = False
            self.stats.session_end = datetime.now(ET)

            duration = self.stats._get_duration_minutes()
            logger.info(f"[AutonomousMode] Session ENDED after {duration} minutes")
            self._log_event(f"Session ENDED - Duration: {duration}min, Videos: {self.stats.videos_played}, Ads: {self.stats.ads_detected}")

            # Notify status change
            if self._on_status_change:
                self._on_status_change(self.get_status())

    def _launch_youtube(self) -> bool:
        """Launch YouTube app on Fire TV."""
        if not self._fire_tv or not self._fire_tv.is_connected():
            logger.warning("[AutonomousMode] Fire TV not connected, cannot launch YouTube")
            return False

        try:
            # Check current app
            current = self._fire_tv.get_current_app()
            if current and YOUTUBE_PACKAGE in current:
                logger.debug("[AutonomousMode] YouTube already running")
                return True

            # Launch YouTube
            logger.info("[AutonomousMode] Launching YouTube...")

            # Use adb_shell to launch YouTube
            with self._fire_tv._lock:
                if self._fire_tv._device:
                    self._fire_tv._device.adb_shell(
                        f"am start -n {YOUTUBE_PACKAGE}/.MainActivity"
                    )

            time.sleep(3)  # Wait for app to launch

            logger.info("[AutonomousMode] YouTube launched")
            self._log_event("YouTube launched")
            return True

        except Exception as e:
            logger.error(f"[AutonomousMode] Failed to launch YouTube: {e}")
            self.stats.errors += 1
            return False

    def _ensure_youtube_playing(self):
        """Ensure YouTube is running and playing content."""
        if not self._fire_tv or not self._fire_tv.is_connected():
            return

        try:
            # Check if YouTube is active
            current = self._fire_tv.get_current_app()

            if not current or YOUTUBE_PACKAGE not in current:
                # YouTube not active, relaunch
                logger.info("[AutonomousMode] YouTube not active, relaunching...")
                self._launch_youtube()
                time.sleep(2)

                # Navigate to start playing
                self._navigate_to_video()
                return

            # YouTube is active - send occasional keep-alive
            logger.debug("[AutonomousMode] YouTube active, sending keepalive")

        except Exception as e:
            logger.error(f"[AutonomousMode] Error in ensure_youtube_playing: {e}")
            self.stats.errors += 1

    def _navigate_to_video(self):
        """Navigate YouTube to play a video."""
        if not self._fire_tv:
            return

        try:
            # Simple navigation: go to home, then select first video
            time.sleep(1)
            self._fire_tv.send_command("down")  # Move to video row
            time.sleep(0.5)
            self._fire_tv.send_command("select")  # Select first video

            self.stats.videos_played += 1
            logger.info("[AutonomousMode] Started playing video")
            self._log_event("Started playing video")

        except Exception as e:
            logger.error(f"[AutonomousMode] Failed to navigate: {e}")
            self.stats.errors += 1

    def play_next_video(self):
        """Skip to next video in YouTube."""
        if not self._fire_tv or not self._fire_tv.is_connected():
            return False

        try:
            self._fire_tv.send_command("right")
            time.sleep(0.3)
            self._fire_tv.send_command("right")
            time.sleep(0.3)
            self._fire_tv.send_command("select")

            self.stats.videos_played += 1
            return True

        except Exception as e:
            logger.error(f"[AutonomousMode] Failed to play next: {e}")
            return False

    def record_ad_detected(self):
        """Record that an ad was detected."""
        self.stats.ads_detected += 1
        self.stats.last_activity = datetime.now(ET)

    def record_ad_skipped(self):
        """Record that an ad was skipped."""
        self.stats.ads_skipped += 1
        self.stats.last_activity = datetime.now(ET)

    def _log_event(self, message: str):
        """Log event to autonomous mode log file."""
        try:
            timestamp = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
            entry = f"- [{timestamp}] {message}\n"

            with open(self._log_file, "a") as f:
                f.write(entry)

        except Exception as e:
            logger.error(f"[AutonomousMode] Failed to write log: {e}")

    def get_log_tail(self, lines: int = 50) -> str:
        """Get last N lines of autonomous mode log."""
        try:
            with open(self._log_file, "r") as f:
                all_lines = f.readlines()
                return "".join(all_lines[-lines:])
        except FileNotFoundError:
            return "No autonomous mode logs yet."
        except Exception as e:
            return f"Error reading logs: {e}"

    def destroy(self):
        """Clean up resources without changing persisted settings."""
        self._running = False
        self._stop_event.set()
        if self._active:
            self._active = False
            self.stats.session_end = datetime.now(ET)
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
