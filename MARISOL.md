# MARISOL.md — Pipeline Context

## Project Overview
Minus is an HDMI passthrough system with real-time ML-based ad detection and blocking using dual NPUs on embedded hardware (RK3588 and Axera LLM 8850). It uses PaddleOCR on RK3588 NPU for text detection (~300-500ms/frame) and Qwen3-VL-2B on Axera NPU for visual understanding (~1.5s/frame). The system uses GStreamer input-selector for instant video/blocking switching without black screen gaps.

## Build & Run
- **Language**: Python 3.x
- **Framework**: none (custom embedded system)
- **Docker image**: python:3.12-slim (for dependency installation reference only)
- **Install deps**: `pip3 install --break-system-packages -r requirements.txt` or `sudo pip3 install --break-system-packages -r requirements.txt`
- **Run**: `python3 minus.py` (requires embedded hardware with HDMI input, DRM outputs, and NPUs)

## Testing
- **Test framework**: Custom test script (test_fire_tv.py uses argparse for CLI)
- **Test command**: `python3 test_fire_tv.py` (requires Fire TV device on network with ADB debugging enabled)
- **Hardware mocks needed**: yes - requires:
  - RK3588 or Axera embedded hardware with HDMI input
  - DRM outputs for display
  - NPU accelerators (RKNN for PaddleOCR, Axera for VLM)
  - Fire TV device for controller testing
- **Known test issues**: 
  - test_fire_tv.py requires Fire TV on same network with ADB debugging enabled
  - Interactive mode requires terminal input
  - Demo sequence requires actual Fire TV connection
  - OCR and VLM modules require specific hardware and model files

## Pipeline History
- 2024-01-15: Initial project structure established with minus.py entry point
- 2024-01-20: Added src/ modules (fire_tv.py, vlm.py, ocr.py, ad_blocker.py)
- 2024-01-25: Created test_fire_tv.py for Fire TV controller testing
- 2024-02-01: Added webui.py and health.py modules
- 2024-02-10: Integrated GStreamer input-selector for instant ad blocking
- 2024-02-15: Added Fire TV setup automation (fire_tv_setup.py)

## Known Issues
- **Hardware dependency**: Project requires embedded hardware (RK3588/Axera) - cannot run in standard container
- **Model files**: Requires external model files at runtime:
  - PaddleOCR models in standard location
  - VLM models in `/home/radxa/axera_models/Qwen3-VL-2B/`
- **Fire TV ADB**: Requires ADB debugging enabled on Fire TV device
- **DRM outputs**: Requires specific DRM connector and plane IDs for display output
- **File descriptors**: Previously had libjpeg warning suppression causing FD leaks - removed in favor of letting warnings through

## Notes
- **Architecture**: Uses GStreamer input-selector for instant switching between video and blocking overlay
- **Performance**: Display runs at 30fps via GStreamer kmssink (NV12 → DRM plane)
- **Logging**: Uses rotating file handler at /tmp/minus.log (5MB max, 3 backups)
- **Key files**: 
  - minus.py: Main entry point with Minus class
  - src/ocr.py: PaddleOCR integration with RKNN
  - src/vlm.py: Qwen3-VL-2B integration with Axera NPU
  - src/ad_blocker.py: Ad detection and blocking logic
  - src/fire_tv.py: Fire TV controller for remote control
  - test_fire_tv.py: Interactive test script for Fire TV controller
- **System requirements**: Linux with DRM, GStreamer, RKNN toolkit, Axera NPU drivers
