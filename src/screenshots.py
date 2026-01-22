"""
Screenshot management for Minus.

Handles saving screenshots for ad detection and VLM training data collection.
Organizes screenshots into separate folders by type for easy training data preparation.
"""

import logging
import time
from datetime import datetime
from pathlib import Path

import cv2

logger = logging.getLogger(__name__)


class ScreenshotManager:
    """Manages screenshot saving for ad detection and training data collection.

    Screenshots are organized into separate directories:
    - ads/         OCR-detected ads (for training ad detection)
    - non_ads/     User paused = false positives (for training non-ad detection)
    - vlm_spastic/ VLM uncertainty cases (for analyzing VLM behavior)
    - static/      Static screen suppression (still frames with ad text)
    """

    def __init__(self, base_dir: Path, max_screenshots: int = 0):
        """
        Initialize the screenshot manager.

        Args:
            base_dir: Base directory for all screenshots (e.g., screenshots/)
            max_screenshots: Maximum screenshots to keep per folder (0 = unlimited)
        """
        self.base_dir = Path(base_dir)
        self.max_screenshots = max_screenshots

        # Organized subdirectories
        self.ads_dir = self.base_dir / "ads"
        self.non_ads_dir = self.base_dir / "non_ads"
        self.vlm_spastic_dir = self.base_dir / "vlm_spastic"
        self.static_dir = self.base_dir / "static"

        # Counters (per type)
        self.ads_count = 0
        self.non_ads_count = 0
        self.vlm_spastic_count = 0
        self.static_count = 0

        # Deduplication for ads (prevents saving same frame multiple times)
        self.screenshot_hashes = set()

        # Rate limiting - max 1 ad screenshot per 5 seconds to prevent flooding
        self._last_ad_screenshot_time = 0
        self._min_screenshot_interval = 5.0  # seconds

        # Ensure directories exist
        self.ads_dir.mkdir(parents=True, exist_ok=True)
        self.non_ads_dir.mkdir(parents=True, exist_ok=True)
        self.vlm_spastic_dir.mkdir(parents=True, exist_ok=True)
        self.static_dir.mkdir(parents=True, exist_ok=True)

    def compute_image_hash(self, frame):
        """Compute a fast perceptual hash for deduplication.

        Resizes to 8x8 grayscale and hashes the bytes.
        O(1) lookup in hash set, robust to minor variations.
        """
        try:
            small = cv2.resize(frame, (8, 8), interpolation=cv2.INTER_AREA)
            if len(small.shape) == 3:
                small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            return hash(small.tobytes())
        except Exception:
            return None

    def save_ad_screenshot(self, frame, matched_keywords, all_texts):
        """Save screenshot when ad detected (with deduplication and rate limiting)."""
        if frame is None:
            return

        # Rate limiting - prevent flooding during long ads
        now = time.time()
        if now - self._last_ad_screenshot_time < self._min_screenshot_interval:
            return

        # Check for duplicate using perceptual hash
        img_hash = self.compute_image_hash(frame)
        if img_hash is not None and img_hash in self.screenshot_hashes:
            return  # Skip duplicate

        # Add hash to set (cap at 1000 entries to prevent unbounded memory growth)
        if img_hash is not None:
            if len(self.screenshot_hashes) >= 1000:
                self.screenshot_hashes.clear()
            self.screenshot_hashes.add(img_hash)

        self._last_ad_screenshot_time = now
        self.ads_count += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"ad_{timestamp}_{self.ads_count:04d}.png"
        filepath = self.ads_dir / filename

        cv2.imwrite(str(filepath), frame)

        keywords_str = ', '.join([f"'{kw}' in '{txt}'" for kw, txt in matched_keywords])
        logger.info(f"  Screenshot saved: {filename}")
        logger.info(f"  Keywords: {keywords_str}")
        logger.info(f"  All texts: {all_texts}")

        if self.max_screenshots > 0:
            self._truncate_dir(self.ads_dir)

    def save_non_ad_screenshot(self, frame):
        """
        Save screenshot for VLM training (content that should NOT be classified as ads).

        Called when user pauses blocking, indicating a false positive.
        """
        if frame is None:
            logger.warning("[Screenshot] Cannot save non-ad screenshot: no frame")
            return

        try:
            self.non_ads_count += 1
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"non_ad_{timestamp}_{self.non_ads_count:04d}.png"
            filepath = self.non_ads_dir / filename

            cv2.imwrite(str(filepath), frame)
            logger.info(f"[Screenshot] Non-ad screenshot saved: non_ads/{filename}")

            if self.max_screenshots > 0:
                self._truncate_dir(self.non_ads_dir)

        except Exception as e:
            logger.error(f"[Screenshot] Failed to save non-ad screenshot: {e}")

    def save_static_ad_screenshot(self, frame):
        """
        Save screenshot when static screen suppression kicks in (for VLM training).

        These screenshots represent still/static ads that should NOT trigger blocking
        (e.g., paused video with ad overlay, YouTube landing page with sponsored content).
        """
        if frame is None:
            return

        try:
            self.static_count += 1
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"static_{timestamp}_{self.static_count:04d}.png"
            filepath = self.static_dir / filename

            cv2.imwrite(str(filepath), frame)
            logger.info(f"[Screenshot] Saved static screenshot: static/{filename}")

            if self.max_screenshots > 0:
                self._truncate_dir(self.static_dir)

        except Exception as e:
            logger.error(f"[Screenshot] Failed to save static screenshot: {e}")

    def save_vlm_spastic_screenshot(self, frame, consecutive_count):
        """
        Save screenshot when VLM is "spastic" - detected ads 2-5 times then changed its mind.

        This captures potential false positive cases where VLM was uncertain.
        """
        if frame is None:
            return

        try:
            self.vlm_spastic_count += 1
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"vlm_spastic_{consecutive_count}x_{timestamp}_{self.vlm_spastic_count:04d}.png"
            filepath = self.vlm_spastic_dir / filename

            cv2.imwrite(str(filepath), frame)
            logger.info(f"[Screenshot] Saved spastic screenshot ({consecutive_count}x ad then no-ad): vlm_spastic/{filename}")

            if self.max_screenshots > 0:
                self._truncate_dir(self.vlm_spastic_dir)

        except Exception as e:
            logger.error(f"[Screenshot] Failed to save spastic screenshot: {e}")

    def _truncate_dir(self, directory: Path):
        """Remove oldest screenshots in a directory if we exceed the max limit."""
        try:
            screenshots = sorted(directory.glob("*.png"), key=lambda p: p.stat().st_mtime)
            excess = len(screenshots) - self.max_screenshots
            if excess > 0:
                for old_file in screenshots[:excess]:
                    old_file.unlink()
        except Exception as e:
            logger.warning(f"[Screenshot] Failed to truncate {directory}: {e}")

    # Legacy property for backward compatibility
    @property
    def screenshot_dir(self):
        """Backward compatibility: returns ads directory."""
        return self.ads_dir

    @property
    def non_ad_dir(self):
        """Backward compatibility: returns non_ads directory."""
        return self.non_ads_dir
