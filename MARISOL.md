# MARISOL.md — Pipeline Context

## Project Overview
Minus is an HDMI passthrough system with real-time ML-based ad detection and blocking for embedded hardware (RK3588 and Axera LLM 8850). It uses GStreamer for video streaming, PaddleOCR for text detection on RK3588 NPU, and Qwen3-VL-2B vision-language model on Axera LLM 8850 NPU. The system blocks ads by overlaying content and includes Fire TV integration.

## Build & Run
- **Language**: Python 3.x
- **Framework**: GStreamer (video streaming), rknn-toolkit-lite2 (NPU inference), PaddleOCR (text detection), Qwen3-VL-2B (vision-language model)
- **Docker image**: Not applicable — requires embedded hardware (RK3588 or Axera LLM 8850) with NPU support
- **Install deps**: `pip3 install --break-system-packages -r requirements.txt`
- **Run**: `python3 minus.py` (main entry point)
- **System packages**: `sudo apt install python3-gi gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad`
- **Environment variables**: None required, but model paths must be configured

## Testing
- **Test framework**: pytest (if tests exist), manual testing via minus.py
- **Test command**: `python3 -m pytest tests/ -v` (if test files exist)
- **Hardware mocks needed**: yes — requires RK3588 or Axera LLM 8850 hardware with NPU support; no containerized testing possible
- **Known test issues**: 
  - Cannot run tests in standard CI environment without embedded hardware
  - Model files must be present at runtime (PaddleOCR models, Qwen3-VL-2B models)
  - GStreamer pipelines require specific hardware capabilities

## Pipeline History
- No prior automated pipeline runs documented
- Manual testing required on target hardware
- Build process involves: install system packages → install Python deps → configure model paths → run minus.py

## Known Issues
- **Hardware dependency**: Cannot test in standard CI/container environment; requires RK3588 or Axera LLM 8850 hardware
- **Model paths**: Documentation references `/home/radxa/axera_models/Qwen3-VL-2B/` but this path is hardware-specific and may not exist in all environments
- **NPU inference**: rknn-toolkit-lite2 requires specific NPU drivers and firmware
- **GStreamer plugins**: Requires system-level installation of gstreamer plugins

## Notes
- **Architecture**: Dual-NPU setup with PaddleOCR on RK3588 (~300ms/frame) and Qwen3-VL-2B on Axera (~1.5s/frame)
- **Key files**: 
  - Entry point: minus.py
  - OCR module: src/ocr.py
  - VLM module: src/vlm.py
  - Ad blocker: src/ad_blocker.py
  - Fire TV integration: src/fire_tv.py, src/fire_tv_setup.py
  - Web UI: src/templates/index.html, src/static/style.css
  - Service file: minus.service (systemd)
  - Config: config.yaml
- **Dependencies**: GStreamer for video, rknn-toolkit-lite2 for NPU inference, PaddleOCR for text detection
- **Runtime requirements**: External model files must be present; system packages (gstreamer plugins) must be installed
- **No runnable entry point in container**: This is hardware-dependent software; cannot be tested without embedded hardware
