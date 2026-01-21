"""
Screenshot management for Minus.

Handles saving screenshots for ad detection and VLM training data collection.
"""

import logging
from datetime import datetime
from pathlib import Path

import cv2

logger = logging.getLogger(__name__)


class ScreenshotManager:
    """Manages screenshot saving for ad detection and training data collection."""

    def __init__(self, screenshot_dir: Path, non_ad_dir: Path, max_screenshots: int = 50):
        """
        Initialize the screenshot manager.

        Args:
            screenshot_dir: Directory to save ad screenshots
            non_ad_dir: Directory to save non-ad training screenshots
            max_screenshots: Maximum screenshots to keep (0 = unlimited)
        """
        self.screenshot_dir = screenshot_dir
        self.non_ad_dir = non_ad_dir
        self.max_screenshots = max_screenshots

        # Counters
        self.screenshot_count = 0
        self.non_ad_count = 0

        # Deduplication
        self.screenshot_hashes = set()

        # Ensure directories exist
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.non_ad_dir.mkdir(parents=True, exist_ok=True)

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
        """Save screenshot when ad detected (with deduplication)."""
        # Check for duplicate using perceptual hash
        img_hash = self.compute_image_hash(frame)
        if img_hash is not None and img_hash in self.screenshot_hashes:
            return  # Skip duplicate

        # Add hash to set (cap at 1000 entries to prevent unbounded memory growth)
        if img_hash is not None:
            if len(self.screenshot_hashes) >= 1000:
                self.screenshot_hashes.clear()
            self.screenshot_hashes.add(img_hash)

        self.screenshot_count += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"ad_{timestamp}_{self.screenshot_count:04d}.png"
        filepath = self.screenshot_dir / filename

        cv2.imwrite(str(filepath), frame)

        keywords_str = ', '.join([f"'{kw}' in '{txt}'" for kw, txt in matched_keywords])
        logger.info(f"  Screenshot saved: {filename}")
        logger.info(f"  Keywords: {keywords_str}")
        logger.info(f"  All texts: {all_texts}")

        if self.max_screenshots > 0:
            self._truncate_screenshots()

    def save_non_ad_screenshot(self, frame):
        """
        Save screenshot for VLM training (content that should NOT be classified as ads).

        Called when user pauses blocking, indicating a false positive.
        """
        if frame is None:
            logger.warning("[Screenshot] Cannot save non-ad screenshot: no frame")
            return

        try:
            self.non_ad_count += 1
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"non_ad_{timestamp}_{self.non_ad_count:04d}.png"
            filepath = self.non_ad_dir / filename

            cv2.imwrite(str(filepath), frame)
            logger.info(f"[Screenshot] Non-ad screenshot saved: {filename}")

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
            self.non_ad_count += 1
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"static_ad_{timestamp}_{self.non_ad_count:04d}.png"
            filepath = self.non_ad_dir / filename

            cv2.imwrite(str(filepath), frame)
            logger.info(f"[Screenshot] Saved static ad screenshot for training: {filename}")

        except Exception as e:
            logger.error(f"[Screenshot] Failed to save static ad screenshot: {e}")

    def save_vlm_spastic_screenshot(self, frame, consecutive_count):
        """
        Save screenshot when VLM is "spastic" - detected ads 2-5 times then changed its mind.

        This captures potential false positive cases where VLM was uncertain.
        """
        if frame is None:
            return

        try:
            self.non_ad_count += 1
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"vlm_spastic_{consecutive_count}x_{timestamp}_{self.non_ad_count:04d}.png"
            filepath = self.non_ad_dir / filename

            cv2.imwrite(str(filepath), frame)
            logger.info(f"[Screenshot] Saved spastic screenshot ({consecutive_count}x ad then no-ad): {filename}")

        except Exception as e:
            logger.error(f"[Screenshot] Failed to save spastic screenshot: {e}")

    def _truncate_screenshots(self):
        """Remove oldest screenshots if we exceed the max limit."""
        try:
            screenshots = sorted(self.screenshot_dir.glob("*.png"), key=lambda p: p.stat().st_mtime)
            excess = len(screenshots) - self.max_screenshots
            if excess > 0:
                for old_file in screenshots[:excess]:
                    old_file.unlink()
        except Exception as e:
            logger.warning(f"[Screenshot] Failed to truncate screenshots: {e}")
