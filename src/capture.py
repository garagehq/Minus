"""
Frame capture utilities for Minus.

Provides capture from ustreamer's HTTP snapshot endpoint.
"""

import logging
import os
import subprocess
from pathlib import Path

import cv2

logger = logging.getLogger(__name__)


class UstreamerCapture:
    """Frame capture using ustreamer's HTTP snapshot endpoint.

    Uses /snapshot/raw which:
    - Returns raw video when blocking is active (for OCR to see ad content)
    - Redirects to /snapshot when not blocking (normal operation)
    """

    def __init__(self, port=9090):
        self.port = port
        # Use /snapshot/raw to always get raw video, even during blocking
        # This is critical for OCR to detect when ads end
        self.snapshot_url = f'http://localhost:{port}/snapshot/raw'
        # Use PID-based filename to avoid conflicts with root-owned stale files
        self.screenshot_path = f'/dev/shm/minus_frame_{os.getpid()}.jpg'

    def cleanup(self):
        """Remove the temporary screenshot file."""
        try:
            Path(self.screenshot_path).unlink(missing_ok=True)
        except Exception:
            pass

    def capture(self):
        """Capture frame via HTTP snapshot and return as numpy array."""
        try:
            # Use -L to follow redirects (when not blocking, /snapshot/raw redirects to /snapshot)
            result = subprocess.run(
                ['curl', '-s', '-L', '-o', self.screenshot_path, self.snapshot_url],
                capture_output=True, timeout=3
            )

            if result.returncode == 0:
                img = cv2.imread(self.screenshot_path)
                if img is not None:
                    # Scale to 960x540 for OCR - model uses 960x960 anyway
                    # Using INTER_AREA for best quality downscaling, fast on 4K->540p
                    h, w = img.shape[:2]
                    if h > 540 or w > 960:
                        img = cv2.resize(img, (960, 540), interpolation=cv2.INTER_AREA)
                    return img

            return None
        except Exception as e:
            logger.error(f"Snapshot capture error: {e}")
            return None
