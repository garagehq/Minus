"""
Autonomous Mode for Minus - Automated YouTube playback for training data collection.

Configurable schedule with support for 24/7 operation. Keeps YouTube playing
on streaming devices (Fire TV, Roku, Google TV) to collect ad detection training data.
Uses VLM to understand screen state and take intelligent actions.

Device-agnostic design supports any streaming device with remote control capability.
"""

import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable
from zoneinfo import ZoneInfo

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Settings file for persistence (use absolute path to work regardless of running user)
SETTINGS_FILE = Path("/home/radxa/.minus_autonomous_mode.json")

# Eastern timezone (default, but schedule hours are timezone-agnostic for simplicity)
ET = ZoneInfo("America/New_York")

# YouTube package names (Fire TV/Android TV use Android packages)
YOUTUBE_PACKAGES = [
    "com.amazon.firetv.youtube",
    "com.google.android.youtube.tv",
    "com.google.android.youtube",
    "youtube",
]

# Supported device types for autonomous mode
DEVICE_TYPE_FIRE_TV = 'fire_tv'
DEVICE_TYPE_ROKU = 'roku'
DEVICE_TYPE_GOOGLE_TV = 'google_tv'

# Timing constants
CHECK_INTERVAL = 60.0          # Check every minute
KEEPALIVE_INTERVAL = 120.0     # Check screen state every 2 minutes (VLM-guided, only acts if needed)


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


class AutonomousMode:
    """
    Autonomous Mode controller for automated operation.

    Features:
    - Configurable schedule (start/end hours, or 24/7 mode)
    - Manual enable/disable toggle
    - Keeps YouTube playing on streaming device (Fire TV, Roku, Google TV)
    - Uses VLM for intelligent screen understanding
    - Tracks statistics
    - Integrates with ad blocking system

    Device-agnostic: works with any controller that has is_connected() and send_command().
    """

    # Default schedule
    DEFAULT_START_HOUR = 0   # Midnight
    DEFAULT_END_HOUR = 8     # 8 AM

    def __init__(self, device_controller=None, ad_blocker=None, vlm=None, frame_capture=None,
                 fire_tv_controller=None):
        """
        Initialize autonomous mode.

        Args:
            device_controller: Generic device controller (FireTV, Roku, GoogleTV)
            ad_blocker: DRMAdBlocker instance for ad detection stats
            vlm: VLMManager instance for screen understanding
            frame_capture: UstreamerCapture instance for grabbing frames
            fire_tv_controller: Deprecated, use device_controller instead
        """
        # Support both new device_controller and legacy fire_tv_controller param
        self._device_controller = device_controller or fire_tv_controller
        self._device_type: Optional[str] = None  # Detected at runtime
        self._ad_blocker = ad_blocker
        self._vlm = vlm
        self._frame_capture = frame_capture

        # Legacy alias for backwards compatibility
        self._fire_tv = self._device_controller

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

        # Frame change detection for pause verification
        self._prev_frame_hash: Optional[int] = None
        self._consecutive_static: int = 0
        self._STATIC_PAUSE_THRESHOLD = 2  # Consecutive static checks before forcing play

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

    def set_device_controller(self, controller, device_type: Optional[str] = None):
        """Set device controller reference.

        Args:
            controller: Device controller (FireTV, Roku, GoogleTV)
            device_type: Optional device type hint ('fire_tv', 'roku', 'google_tv')
                        If not provided, will be detected from controller class name.
        """
        self._device_controller = controller
        self._fire_tv = controller  # Legacy alias

        if device_type:
            self._device_type = device_type
        else:
            # Auto-detect device type from controller class name
            self._device_type = self._detect_device_type(controller)

        logger.info(f"[AutonomousMode] Device controller set: {self._device_type}")

    def set_fire_tv(self, controller):
        """Set Fire TV controller reference (legacy, use set_device_controller)."""
        self.set_device_controller(controller, DEVICE_TYPE_FIRE_TV)

    def set_roku(self, controller):
        """Set Roku controller reference."""
        self.set_device_controller(controller, DEVICE_TYPE_ROKU)

    def _detect_device_type(self, controller) -> str:
        """Detect device type from controller class name."""
        if controller is None:
            return DEVICE_TYPE_FIRE_TV  # Default

        class_name = controller.__class__.__name__.lower()
        if 'roku' in class_name:
            return DEVICE_TYPE_ROKU
        elif 'google' in class_name or 'android' in class_name:
            return DEVICE_TYPE_GOOGLE_TV
        else:
            return DEVICE_TYPE_FIRE_TV  # Default to Fire TV for backwards compatibility

    def set_ad_blocker(self, blocker):
        """Set ad blocker reference."""
        self._ad_blocker = blocker

    def set_vlm(self, vlm):
        """Set VLM reference for screen understanding."""
        self._vlm = vlm

    def set_frame_capture(self, capture):
        """Set frame capture reference."""
        self._frame_capture = capture

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

        # Return status OUTSIDE lock (get_status may be slow due to device checks)
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
                pass  # Will return status outside lock
            else:
                self._enabled = True
                self._manual_override = manual

                # Persist setting
                self._save_settings()

                logger.info(f"[AutonomousMode] Enabled (manual={manual})")
                self._log_event("Autonomous mode ENABLED" + (" (manual)" if manual else " (scheduled)"))

                # Start the monitoring thread
                self._start_thread()

        # Return status OUTSIDE lock (get_status may be slow due to device checks)
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

            # Stop if running (use unlocked version since we hold the lock)
            if self._active:
                self._deactivate_unlocked()

            self._stop_thread()

            logger.info("[AutonomousMode] Disabled")
            self._log_event("Autonomous mode DISABLED")

        # Return status OUTSIDE lock (get_status may be slow due to device checks)
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

        # Check device connection (works for any device type)
        device_connected = False
        if self._device_controller:
            try:
                device_connected = self._device_controller.is_connected()
            except Exception:
                device_connected = False

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
            "device_type": self._device_type,
            "device_connected": device_connected,
            # Legacy field for backwards compatibility
            "fire_tv_connected": device_connected if self._device_type == DEVICE_TYPE_FIRE_TV else False,
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
        # Quick state update inside lock
        with self._lock:
            if self._active:
                return

            self._active = True
            self.stats.reset()
            self.stats.session_start = datetime.now(ET)

            logger.info("[AutonomousMode] Session STARTED")
            self._log_event("Session STARTED")

        # Slow operations OUTSIDE lock to prevent blocking API calls
        self._launch_youtube()

        # Notify status change (also outside lock)
        if self._on_status_change:
            self._on_status_change(self.get_status())

    def _deactivate(self):
        """Deactivate autonomous mode session (acquires lock)."""
        with self._lock:
            self._deactivate_unlocked()

    def _deactivate_unlocked(self):
        """Deactivate autonomous mode session (caller must hold lock)."""
        if not self._active:
            return

        self._active = False
        self.stats.session_end = datetime.now(ET)

        duration = self.stats._get_duration_minutes()
        logger.info(f"[AutonomousMode] Session ENDED after {duration} minutes")
        self._log_event(f"Session ENDED - Duration: {duration}min, Videos: {self.stats.videos_played}, Ads: {self.stats.ads_detected}")

    def _is_youtube_app(self, app_name: str) -> bool:
        """Check if the app name matches any known YouTube package."""
        if not app_name:
            return False
        app_lower = app_name.lower()
        return any(pkg in app_lower for pkg in YOUTUBE_PACKAGES)

    # VLM prompt that returns a structured, single-word answer for reliable parsing
    SCREEN_QUERY_PROMPT = (
        "Look at this TV screen and classify it into exactly one category. "
        "Answer with ONLY one of these words:\n"
        "PLAYING - a video is actively playing\n"
        "PAUSED - a video is paused (play bar visible, frozen frame)\n"
        "DIALOG - a popup or dialog is showing (like 'Are you still watching?')\n"
        "MENU - a home screen, browse screen, or video selection menu\n"
        "SCREENSAVER - a screensaver or blank/black screen\n"
        "Answer with one word only."
    )

    def _query_screen(self) -> Optional[str]:
        """Use VLM to understand what's currently on screen.

        Returns:
            VLM response (should be one of: PLAYING, PAUSED, DIALOG, MENU, SCREENSAVER),
            or None if unavailable.
        """
        if not self._vlm or not self._vlm.is_ready or not self._frame_capture:
            return None

        try:
            frame = self._frame_capture.capture()
            if frame is None:
                return None

            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                tmp_path = tmp.name
                cv2.imwrite(tmp_path, frame)

            try:
                response, elapsed = self._vlm.query_image(tmp_path, self.SCREEN_QUERY_PROMPT)
                logger.info(f"[AutonomousMode] VLM screen query ({elapsed:.1f}s): {response}")
                return response
            finally:
                os.unlink(tmp_path)

        except Exception as e:
            logger.error(f"[AutonomousMode] VLM screen query failed: {e}")
            return None

    def _determine_action(self, screen_desc: str) -> str:
        """Determine what action to take based on VLM screen classification.

        Expects structured response (PLAYING/PAUSED/DIALOG/MENU/SCREENSAVER).
        Falls back to keyword matching if VLM gives a longer response.

        Returns one of: 'none', 'play', 'dismiss', 'select', 'launch'
        """
        if not screen_desc:
            return "none"

        desc = screen_desc.strip().upper()

        # Check for structured single-word responses first
        if desc.startswith("PLAYING"):
            return "none"
        if desc.startswith("DIALOG"):
            return "dismiss"
        if desc.startswith("SCREENSAVER"):
            return "launch"
        if desc.startswith("MENU"):
            return "select"
        if desc.startswith("PAUSED"):
            return "play"

        # Fallback: keyword matching on longer responses
        desc_lower = screen_desc.lower()

        # "still watching" is a strong signal for dialog regardless of context
        if "still watching" in desc_lower or "still there" in desc_lower:
            return "dismiss"

        if "screensaver" in desc_lower or "black screen" in desc_lower:
            return "launch"

        if "home screen" in desc_lower or "browse" in desc_lower or "thumbnail" in desc_lower:
            return "select"

        # Only match "paused" as a positive statement, not "not paused"
        if "paused" in desc_lower and "not paused" not in desc_lower:
            return "play"

        if "playing" in desc_lower:
            return "none"

        # Unknown state - do nothing to avoid disruption
        return "none"

    def _launch_youtube(self) -> bool:
        """Launch YouTube app on the connected streaming device."""
        if not self._device_controller or not self._device_controller.is_connected():
            logger.warning(f"[AutonomousMode] {self._device_type or 'Device'} not connected, cannot launch YouTube")
            return False

        try:
            # Device-specific YouTube launch
            if self._device_type == DEVICE_TYPE_ROKU:
                return self._launch_youtube_roku()
            elif self._device_type in (DEVICE_TYPE_FIRE_TV, DEVICE_TYPE_GOOGLE_TV):
                return self._launch_youtube_android()
            else:
                # Fallback: try Android method
                return self._launch_youtube_android()

        except Exception as e:
            logger.error(f"[AutonomousMode] Failed to launch YouTube: {e}")
            self.stats.errors += 1
            return False

    def _launch_youtube_roku(self) -> bool:
        """Launch YouTube on Roku using ECP launch API."""
        try:
            logger.info("[AutonomousMode] Launching YouTube on Roku...")

            # Roku controller has launch_app method
            if hasattr(self._device_controller, 'launch_app'):
                result = self._device_controller.launch_app('youtube')
                if result:
                    time.sleep(3)
                    logger.info("[AutonomousMode] YouTube launched on Roku")
                    self._log_event("YouTube launched (Roku)")
                    return True
                else:
                    logger.error("[AutonomousMode] Roku launch_app returned False")
                    return False
            else:
                logger.error("[AutonomousMode] Roku controller missing launch_app method")
                return False

        except Exception as e:
            logger.error(f"[AutonomousMode] Roku YouTube launch error: {e}")
            return False

    def _launch_youtube_android(self) -> bool:
        """Launch YouTube on Fire TV / Android TV / Google TV using ADB."""
        try:
            # Check current app if the controller supports it
            if hasattr(self._device_controller, 'get_current_app'):
                current = self._device_controller.get_current_app()
                logger.debug(f"[AutonomousMode] Current app: {current}")
                if self._is_youtube_app(current):
                    logger.debug("[AutonomousMode] YouTube already running")
                    return True

            # Launch YouTube via ADB intent
            logger.info(f"[AutonomousMode] Launching YouTube on {self._device_type}...")

            # Access internal _device for ADB shell command
            if hasattr(self._device_controller, '_lock') and hasattr(self._device_controller, '_device'):
                with self._device_controller._lock:
                    if self._device_controller._device:
                        # Try multiple package names
                        for pkg in YOUTUBE_PACKAGES:
                            try:
                                self._device_controller._device.adb_shell(
                                    f"am start -a android.intent.action.MAIN -c android.intent.category.LEANBACK_LAUNCHER {pkg}"
                                )
                                break
                            except Exception:
                                continue

            time.sleep(3)
            logger.info("[AutonomousMode] YouTube launched")
            self._log_event(f"YouTube launched ({self._device_type})")
            return True

        except Exception as e:
            logger.error(f"[AutonomousMode] Android YouTube launch error: {e}")
            return False

    def _compute_frame_hash(self, frame) -> int:
        """Compute a perceptual hash (dHash) of a frame for change detection.

        Returns a 64-bit integer hash. Frames that look similar will have
        hashes with low Hamming distance.
        """
        small = cv2.resize(frame, (9, 8), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if len(small.shape) == 3 else small
        diff = gray[:, 1:] > gray[:, :-1]
        return int(np.packbits(diff.flatten())[:8].view(np.uint64)[0])

    def _is_audio_flowing(self) -> bool:
        """Check if audio is currently flowing (music/sound playing).

        Uses the ad_blocker's audio module if available, otherwise checks
        ALSA capture device status directly via /proc/asound.

        Returns True if audio buffers are actively flowing.
        """
        # Method 1: Check via ad_blocker's audio module
        if self._ad_blocker and hasattr(self._ad_blocker, 'audio') and self._ad_blocker.audio:
            try:
                status = self._ad_blocker.audio.get_status()
                buffer_age = status.get('last_buffer_age', 999)
                # -1 means no buffer ever received, so NOT flowing
                is_flowing = 0 <= buffer_age < 3.0  # Buffer received within last 3 seconds
                logger.debug(f"[AutonomousMode] Audio buffer age: {buffer_age:.1f}s, flowing={is_flowing}")
                return is_flowing
            except Exception:
                pass

        # Method 2: Check ALSA capture device status directly
        try:
            alsa_status_path = "/proc/asound/card4/pcm0c/sub0/status"
            with open(alsa_status_path, 'r') as f:
                content = f.read()
            is_running = 'state: RUNNING' in content
            logger.debug(f"[AutonomousMode] ALSA capture: {'RUNNING' if is_running else 'not running'}")
            return is_running
        except Exception:
            return False

    # Keywords that indicate YouTube login/account selection screen
    # Includes variants to handle OCR noise (missing/merged spaces)
    # NOTE: "sign in" removed - too common, appears on home page
    LOGIN_SCREEN_KEYWORDS = [
        'watch as guest',
        'watchas guest',     # OCR sometimes merges "watch as"
        'add a kid account',
        'add akid account',  # OCR sometimes merges "a kid"
        'kid account',       # Specific to account selection
        'choose account',
        'switch account',
    ]

    # Keywords that indicate YouTube home/browse screen (need to select a video)
    # These appear when showing video recommendations/thumbnails
    HOME_SCREEN_KEYWORDS = [
        'new to you',
        'newtoyou',          # OCR sometimes merges spaces
        'trending',
        'subscriptions',
        'library',
        'views',             # "3.3M views" indicates video thumbnails
        'year ago',
        'month ago',
        'day ago',
        'hour ago',
    ]

    def _is_youtube_login_screen(self) -> bool:
        """Check if we're on the YouTube login/account selection screen using OCR keywords.

        The login screen shows:
        - "Watch as guest"
        - "Add account"
        - "Add a kid account"
        - User profile names

        VLM often misclassifies this static screen as PLAYING.
        Uses the last_ocr_texts from the ad_blocker (most recent OCR results).
        """
        try:
            # Check the most recent OCR texts from ad_blocker
            if self._ad_blocker and hasattr(self._ad_blocker, 'last_ocr_texts'):
                texts = self._ad_blocker.last_ocr_texts
                if texts:
                    combined = ' '.join(str(t) for t in texts).lower()

                    for keyword in self.LOGIN_SCREEN_KEYWORDS:
                        if keyword in combined:
                            logger.info(f"[AutonomousMode] YouTube login screen detected: '{keyword}'")
                            return True

            # Fallback: High consecutive static count suggests stuck on login screen
            if self._consecutive_static >= 4:
                logger.info("[AutonomousMode] High static count - might be login screen")
                return True

            return False

        except Exception as e:
            logger.debug(f"[AutonomousMode] Login screen check failed: {e}")
            return False

    def _is_youtube_home_screen(self) -> bool:
        """Check if we're on YouTube home/browse screen showing video thumbnails.

        The home screen shows video recommendations with:
        - "New to you", "Trending", "Subscriptions", "Library" tabs
        - Video thumbnails with view counts ("3.3M views · 1 year ago")

        When VLM misclassifies this as PLAYING, we need to select a video
        instead of sending play_pause.
        """
        try:
            if self._ad_blocker and hasattr(self._ad_blocker, 'last_ocr_texts'):
                texts = self._ad_blocker.last_ocr_texts
                if texts:
                    combined = ' '.join(str(t) for t in texts).lower()

                    for keyword in self.HOME_SCREEN_KEYWORDS:
                        if keyword in combined:
                            logger.info(f"[AutonomousMode] YouTube home screen detected: '{keyword}'")
                            return True

            return False

        except Exception as e:
            logger.debug(f"[AutonomousMode] Home screen check failed: {e}")
            return False

    def _is_screen_static(self) -> bool:
        """Check if screen is truly paused by combining frame analysis with audio state.

        A truly paused screen has:
        - Static frames (identical between captures)
        - No audio flowing (music stopped)

        A music stream with a static image has:
        - Static or near-static frames
        - Audio still flowing (music playing)

        Returns True only if screen is static AND audio is not flowing (truly paused).
        """
        if not self._frame_capture:
            return False

        try:
            frame1 = self._frame_capture.capture()
            if frame1 is None:
                return False

            time.sleep(3)

            frame2 = self._frame_capture.capture()
            if frame2 is None:
                return False

            hash1 = self._compute_frame_hash(frame1)
            hash2 = self._compute_frame_hash(frame2)

            # Hamming distance - low distance means nearly identical frames
            # Truly paused screens: hamming = 0 (identical JPEG captures)
            # Slow animations (lo-fi streams): hamming = 3-10 (subtle changes)
            # Active video: hamming = 15-40 (clear changes)
            hamming = bin(hash1 ^ hash2).count('1')
            frames_static = hamming < 3  # Only truly frozen screens

            if not frames_static:
                logger.info(f"[AutonomousMode] Frame change check: hamming={hamming}, video is changing")
                return False

            # Frames are static - check if audio is still playing
            audio_flowing = self._is_audio_flowing()

            if audio_flowing:
                # Static image but audio playing = music stream (lo-fi, etc.) - NOT paused
                logger.info(f"[AutonomousMode] Frame change check: hamming={hamming}, "
                           f"frames static but audio flowing (music stream, not paused)")
                return False
            else:
                # Static image AND no audio = truly paused
                logger.info(f"[AutonomousMode] Frame change check: hamming={hamming}, "
                           f"frames static + no audio = PAUSED")
                return True

        except Exception as e:
            logger.debug(f"[AutonomousMode] Frame change check error: {e}")
            return False

    def _check_roku_active_app(self) -> bool:
        """For Roku devices, check if YouTube is the active app via ECP.

        This is more reliable than VLM because the Roku ECP definitively
        reports which app is running. VLM can confuse the Roku City screensaver
        with a playing video.

        Returns True if YouTube is running (or if not a Roku device).
        Returns False if Roku is on home/screensaver (YouTube needs relaunch).
        """
        if self._device_type != DEVICE_TYPE_ROKU:
            return True  # Not a Roku, skip this check

        if not hasattr(self._device_controller, 'get_active_app_id'):
            return True  # Controller doesn't support active app query

        try:
            # Check for screensaver overlay first — this can happen even when
            # YouTube is the "active" app (screensaver overlays it)
            if hasattr(self._device_controller, 'is_screensaver_active'):
                if self._device_controller.is_screensaver_active():
                    logger.info("[AutonomousMode] Roku screensaver active — dismissing")
                    self._device_controller.send_command('select')  # Wake from screensaver
                    self._log_event("Roku screensaver dismissed")
                    time.sleep(1)
                    return True  # Screensaver dismissed, YouTube should resume

            app_id = self._device_controller.get_active_app_id()
            if app_id is None:
                return True  # Query failed, don't interfere

            youtube_app_id = '837'  # Roku YouTube app ID
            if app_id == youtube_app_id:
                return True

            # Not YouTube — check what's running
            app_name = self._device_controller.get_active_app() or f"app_id={app_id}"
            logger.info(f"[AutonomousMode] Roku active app is '{app_name}' (not YouTube) — relaunching")
            self._log_event(f"Roku not on YouTube (active: {app_name}), relaunching")
            return False

        except Exception as e:
            logger.debug(f"[AutonomousMode] Roku active app check error: {e}")
            return True  # On error, don't interfere

    def _ensure_youtube_playing(self):
        """Use VLM to understand screen state and take appropriate action.

        For Roku: first checks active app via ECP (definitive) before VLM.
        VLM can confuse the Roku City screensaver with a playing video.

        Includes frame-change verification: if VLM says PLAYING but the screen
        is actually static (not changing), the video is likely paused. VLM is
        unreliable at distinguishing paused from playing states.
        """
        if not self._device_controller or not self._device_controller.is_connected():
            return

        try:
            # For Roku: check active app via ECP before VLM
            # This catches the case where Roku exits YouTube to screensaver/home
            # and VLM misclassifies the animated screensaver as "PLAYING"
            if not self._check_roku_active_app():
                self._launch_youtube()
                self._consecutive_static = 0
                return

            # OCR-based login screen detection (VLM often misclassifies this as PLAYING)
            # Check for YouTube account selection / login screen
            if self._is_youtube_login_screen():
                logger.info("[AutonomousMode] YouTube login screen detected via OCR - selecting account")
                self._log_event("YouTube login screen detected - selecting account")
                # Navigate down to highlight an account and select it
                self._device_controller.send_command("down")
                time.sleep(0.5)
                self._device_controller.send_command("select")
                self._consecutive_static = 0
                return

            # Use VLM to understand what's on screen
            screen_desc = self._query_screen()
            action = self._determine_action(screen_desc)

            if action == "none":
                # VLM says PLAYING - verify with frame change detection
                if self._is_screen_static():
                    self._consecutive_static += 1
                    logger.info(f"[AutonomousMode] VLM says PLAYING but screen is static "
                               f"({self._consecutive_static}/{self._STATIC_PAUSE_THRESHOLD})")

                    if self._consecutive_static >= self._STATIC_PAUSE_THRESHOLD:
                        # Screen hasn't changed for multiple checks
                        # Check if we're on home screen (need to select a video)
                        if self._is_youtube_home_screen():
                            logger.info("[AutonomousMode] Home screen detected - selecting a video")
                            self._device_controller.send_command("down")
                            time.sleep(0.5)
                            self._device_controller.send_command("select")
                            self._log_event("Home screen: selected video (VLM said PLAYING)")
                            self.stats.videos_played += 1
                        else:
                            # Not home screen - try play_pause for paused video
                            logger.info("[AutonomousMode] Static screen detected - sending play_pause")
                            self._device_controller.send_command("play_pause")
                            self._log_event("Static screen override: sent play_pause (VLM said PLAYING)")
                        self._consecutive_static = 0
                else:
                    # Screen is changing - truly playing
                    self._consecutive_static = 0
                    logger.debug("[AutonomousMode] Screen looks good, video is playing")
                return

            # Taking an action - reset static counter
            self._consecutive_static = 0

            logger.info(f"[AutonomousMode] Action needed: {action} (screen: {screen_desc})")
            self._log_event(f"VLM action: {action}")

            if action == "play":
                # Video is paused - use play_pause (works on all devices)
                self._device_controller.send_command("play_pause")
                logger.info("[AutonomousMode] Sent play_pause command (video was paused)")

            elif action == "dismiss":
                # Dialog like "Are you still watching?" - press select to dismiss
                self._device_controller.send_command("select")
                time.sleep(1.5)
                # After dismissing, send play_pause to ensure playback resumes
                self._device_controller.send_command("play_pause")
                logger.info("[AutonomousMode] Dismissed dialog and sent play_pause")

            elif action == "select":
                # On home/menu screen - navigate to a video
                self._device_controller.send_command("down")
                time.sleep(0.5)
                self._device_controller.send_command("select")
                self.stats.videos_played += 1
                logger.info("[AutonomousMode] Selected video from menu")
                self._log_event("Selected video from menu")

            elif action == "launch":
                # Screensaver/sleep - wake up and launch YouTube
                self._wake_device()
                time.sleep(2)
                self._launch_youtube()
                time.sleep(2)
                self._device_controller.send_command("down")
                time.sleep(0.5)
                self._device_controller.send_command("select")
                self.stats.videos_played += 1
                logger.info("[AutonomousMode] Woke up and launched YouTube")
                self._log_event("Woke up device and launched YouTube")

            elif action == "back":
                self._device_controller.send_command("back")
                time.sleep(1)
                self._device_controller.send_command("play")

        except Exception as e:
            logger.error(f"[AutonomousMode] Error in ensure_youtube_playing: {e}")
            self.stats.errors += 1

    def _wake_device(self):
        """Wake up the device from screensaver/sleep."""
        try:
            if self._device_type == DEVICE_TYPE_ROKU:
                # Roku: power on or home button
                if hasattr(self._device_controller, 'send_command'):
                    # Try power first, then home as fallback
                    self._device_controller.send_command("power")
                    time.sleep(0.5)
                    self._device_controller.send_command("home")
            else:
                # Fire TV / Android TV: wakeup command
                if hasattr(self._device_controller, 'send_command'):
                    self._device_controller.send_command("wakeup")
        except Exception as e:
            logger.warning(f"[AutonomousMode] Wake device error: {e}")

    def play_next_video(self):
        """Skip to next video in YouTube."""
        if not self._device_controller or not self._device_controller.is_connected():
            return False

        try:
            self._device_controller.send_command("right")
            time.sleep(0.3)
            self._device_controller.send_command("right")
            time.sleep(0.3)
            self._device_controller.send_command("select")

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
