"""
Screenshot management for Minus.

Handles saving screenshots for ad detection and VLM training data collection.
Organizes screenshots into separate folders by type for easy training data preparation.

Deduplication uses perceptual difference hashing (dHash):
- Resize to 9x8 grayscale, compare adjacent pixels → 64-bit hash
- Hamming distance < 10 bits = ~85% similar → skip as duplicate
- Also rejects blank/black frames (mean brightness < 15)
"""

import logging
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Dedup: max hamming distance to consider frames as duplicates (out of 64 bits)
# 10 bits = ~84% similar, catches near-identical frames
DHASH_THRESHOLD = 10

# Reject frames with mean brightness below this (0-255)
BLACK_FRAME_THRESHOLD = 15

# Reject frames with std deviation below this (solid color)
SOLID_FRAME_THRESHOLD = 10


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

        # Deduplication for ALL categories (prevents saving same/similar frames)
        # Stores recent dHash values per category for near-duplicate detection
        self._recent_hashes = {
            'ads': [],
            'non_ads': [],
            'vlm_spastic': [],
            'static': [],
        }
        self._max_hashes = 200  # Keep last N hashes per category

        # Rate limiting per category
        self._last_screenshot_time = {
            'ads': 0,
            'non_ads': 0,
            'vlm_spastic': 0,
            'static': 0,
        }
        self._min_screenshot_interval = 5.0  # seconds between saves

        # Ensure directories exist
        self.ads_dir.mkdir(parents=True, exist_ok=True)
        self.non_ads_dir.mkdir(parents=True, exist_ok=True)
        self.vlm_spastic_dir.mkdir(parents=True, exist_ok=True)
        self.static_dir.mkdir(parents=True, exist_ok=True)

    def compute_dhash(self, frame):
        """Compute a perceptual difference hash (dHash) for near-duplicate detection.

        Resizes to 9x8, compares adjacent pixels horizontally → 64-bit hash.
        Similar images have low hamming distance even with minor variations
        (compression artifacts, slight timing differences, UI changes).
        """
        try:
            small = cv2.resize(frame, (9, 8), interpolation=cv2.INTER_AREA)
            if len(small.shape) == 3:
                small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            # Compare adjacent pixels: 1 if left > right, else 0
            diff = small[:, 1:] > small[:, :-1]
            # Pack into integer
            return int(np.packbits(diff.flatten()).tobytes().hex(), 16)
        except Exception:
            return None

    @staticmethod
    def _hamming_distance(h1, h2):
        """Count differing bits between two hashes."""
        return bin(h1 ^ h2).count('1')

    def _is_near_duplicate(self, frame_hash, category):
        """Check if a frame hash is a near-duplicate of any recent hash in this category."""
        if frame_hash is None:
            return False
        for existing_hash in self._recent_hashes[category]:
            if self._hamming_distance(frame_hash, existing_hash) < DHASH_THRESHOLD:
                return True
        return False

    def _record_hash(self, frame_hash, category):
        """Record a hash for future duplicate detection."""
        if frame_hash is None:
            return
        hashes = self._recent_hashes[category]
        hashes.append(frame_hash)
        if len(hashes) > self._max_hashes:
            del hashes[:len(hashes) - self._max_hashes]

    @staticmethod
    def _is_blank_frame(frame):
        """Reject black, near-black, or solid-color frames.

        Returns True if frame should be rejected.
        """
        try:
            gray = frame
            if len(frame.shape) == 3:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            mean_val = np.mean(gray)
            std_val = np.std(gray)
            if mean_val < BLACK_FRAME_THRESHOLD:
                return True  # Near-black
            if std_val < SOLID_FRAME_THRESHOLD:
                return True  # Solid color (including white/gray)
            return False
        except Exception:
            return False

    def _should_save(self, frame, category):
        """Common gate for all screenshot saves: rate limit, blank reject, dedup.

        Returns True if the frame should be saved.
        """
        if frame is None:
            logger.warning(f"[Screenshot] Cannot save {category} screenshot: no frame")
            return False

        # Rate limiting
        now = time.time()
        elapsed = now - self._last_screenshot_time[category]
        if elapsed < self._min_screenshot_interval:
            logger.debug(f"[Screenshot] Rate limited {category} (only {elapsed:.1f}s since last)")
            return False

        # Reject blank/black frames
        if self._is_blank_frame(frame):
            logger.info(f"[Screenshot] Rejected blank/black frame for {category}")
            return False

        # Near-duplicate check
        frame_hash = self.compute_dhash(frame)
        if self._is_near_duplicate(frame_hash, category):
            logger.info(f"[Screenshot] Rejected near-duplicate for {category} (dHash match)")
            return False

        # All checks passed — record state
        self._last_screenshot_time[category] = now
        self._record_hash(frame_hash, category)
        return True

    def save_ad_screenshot(self, frame, matched_keywords, all_texts):
        """Save screenshot when ad detected (with dedup, rate limiting, blank rejection)."""
        if not self._should_save(frame, 'ads'):
            return

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
        if not self._should_save(frame, 'non_ads'):
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
        if not self._should_save(frame, 'static'):
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
        if not self._should_save(frame, 'vlm_spastic'):
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
