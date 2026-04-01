"""
Configuration classes for Minus.
"""

from dataclasses import dataclass


@dataclass
class MinusConfig:
    """Configuration for the Minus pipeline."""
    device: str = "/dev/video0"
    screenshot_dir: str = "screenshots"
    ocr_timeout: float = 1.5
    ustreamer_port: int = 9090
    max_screenshots: int = 0  # 0 = unlimited (keep all for training)
    drm_connector_id: int = None  # Auto-detect HDMI output connector
    drm_plane_id: int = None  # Auto-detect NV12-capable overlay plane
    output_width: int = None  # Auto-detect from display EDID
    output_height: int = None  # Auto-detect from display EDID
    audio_capture_device: str = "auto"  # HDMI-RX audio input - auto-detected from /proc/asound/cards
    audio_playback_device: str = None  # Auto-detect based on connected HDMI output
    webui_port: int = 8080  # Web UI port
    no_ocr: bool = False  # Disable OCR processing (for testing)
    no_vlm: bool = False  # Disable VLM processing (for testing)
    no_blocking: bool = False  # Disable blocking overlays (for testing)
