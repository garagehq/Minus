"""
V4L2 (Video4Linux2) probing utilities for Minus.

Auto-detects video capture device format and resolution.
"""

import logging
import re
import subprocess

logger = logging.getLogger(__name__)


def probe_v4l2_device(device: str) -> dict:
    """
    Probe a V4L2 device to get its current format and resolution.

    Returns dict with:
        - format: V4L2 pixel format string (e.g., 'NV12', 'BGR3', 'YUYV')
        - width: int
        - height: int
        - ustreamer_format: format string for ustreamer (e.g., 'NV12', 'BGR24')
    """
    result = {
        'format': None,
        'width': 0,
        'height': 0,
        'ustreamer_format': None,
    }

    try:
        # Run v4l2-ctl to get format info
        proc = subprocess.run(
            ['v4l2-ctl', '-d', device, '--get-fmt-video'],
            capture_output=True, text=True, timeout=5
        )

        if proc.returncode != 0:
            logger.warning(f"Failed to probe {device}: {proc.stderr}")
            return result

        output = proc.stdout

        # Parse width/height
        wh_match = re.search(r'Width/Height\s*:\s*(\d+)/(\d+)', output)
        if wh_match:
            result['width'] = int(wh_match.group(1))
            result['height'] = int(wh_match.group(2))

        # Parse pixel format - look for the 4-character code
        # Example: "Pixel Format      : 'NV12' (Y/UV 4:2:0)"
        # Example: "Pixel Format      : 'BGR3' (24-bit BGR 8-8-8)"
        fmt_match = re.search(r"Pixel Format\s*:\s*'(\w+)'", output)
        if fmt_match:
            v4l2_format = fmt_match.group(1)
            result['format'] = v4l2_format

            # Map V4L2 format codes to ustreamer format names
            format_map = {
                'NV12': 'NV12',
                'NV16': 'NV16',
                'NV24': 'NV24',
                'BGR3': 'BGR24',
                'RGB3': 'RGB24',
                'YUYV': 'YUYV',
                'UYVY': 'UYVY',
                'MJPG': 'MJPEG',
                'JPEG': 'MJPEG',
            }
            result['ustreamer_format'] = format_map.get(v4l2_format, v4l2_format)

        logger.info(f"Probed {device}: {result['width']}x{result['height']} format={result['format']} -> {result['ustreamer_format']}")

    except subprocess.TimeoutExpired:
        logger.warning(f"Timeout probing {device}")
    except Exception as e:
        logger.warning(f"Error probing {device}: {e}")

    return result
