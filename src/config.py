"""
Configuration classes for Minus.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _get_env_path(env_var: str, default: str) -> str:
    """Get path from environment variable or use default."""
    return os.environ.get(env_var, default)


def _get_env_float(env_var: str, default: float) -> float:
    """Get float from environment variable or use default."""
    val = os.environ.get(env_var)
    if val is not None:
        try:
            return float(val)
        except ValueError:
            pass
    return default


def _get_env_int(env_var: str, default: int) -> int:
    """Get int from environment variable or use default."""
    val = os.environ.get(env_var)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return default


@dataclass
class MinusConfig:
    """Configuration for the Minus pipeline."""
    # Device and paths
    device: str = "/dev/video0"
    screenshot_dir: str = "screenshots"

    # Timeouts and thresholds
    ocr_timeout: float = 1.5
    vlm_timeout: float = 3.0  # Hard timeout for VLM inference (seconds)

    # ustreamer settings
    ustreamer_port: int = 9090

    # Screenshot management
    max_screenshots: int = 0  # 0 = unlimited (keep all for training)

    # DRM output (auto-detected if not specified)
    drm_connector_id: int = None  # Auto-detect HDMI output connector
    drm_plane_id: int = None  # Auto-detect NV12-capable overlay plane
    output_width: int = None  # Auto-detect from display EDID
    output_height: int = None  # Auto-detect from display EDID

    # Audio settings (auto-detected if not specified)
    audio_capture_device: str = "auto"  # HDMI-RX audio input - auto-detected from /proc/asound/cards
    audio_playback_device: str = None  # Auto-detect based on connected HDMI output

    # Web UI
    webui_port: int = 80  # Web UI port (port 80 requires root)

    # Feature toggles
    no_ocr: bool = False  # Disable OCR processing (for testing)
    no_vlm: bool = False  # Disable VLM processing (for testing)
    no_blocking: bool = False  # Disable blocking overlays (for testing)

    # Animation durations (seconds)
    animation_start_duration: float = field(
        default_factory=lambda: _get_env_float('MINUS_ANIMATION_START', 0.3)
    )
    animation_end_duration: float = field(
        default_factory=lambda: _get_env_float('MINUS_ANIMATION_END', 0.25)
    )

    # Health check thresholds
    frame_stale_threshold: float = field(
        default_factory=lambda: _get_env_float('MINUS_FRAME_STALE_THRESHOLD', 5.0)
    )

    # Detection thresholds
    vlm_alone_threshold: int = field(
        default_factory=lambda: _get_env_int('MINUS_VLM_ALONE_THRESHOLD', 5)
    )
    scene_change_threshold: float = field(
        default_factory=lambda: _get_env_float('MINUS_SCENE_CHANGE_THRESHOLD', 0.01)
    )
    dynamic_cooldown: float = field(
        default_factory=lambda: _get_env_float('MINUS_DYNAMIC_COOLDOWN', 0.5)
    )


# External paths (configurable via environment variables)
USTREAMER_PATH = _get_env_path('MINUS_USTREAMER_PATH', '/home/radxa/ustreamer-patched')
VLM_MODEL_DIR = _get_env_path('MINUS_VLM_MODEL_DIR', '/home/radxa/axera_models/FastVLM-1.5B')
OCR_MODEL_DIR = _get_env_path('MINUS_OCR_MODEL_DIR', '/home/radxa/rknn-llm/examples/multimodal_model_demo/deploy/install/demo_Linux_aarch64/models/paddleocr')
