# MARISOL.md — Pipeline Context

## Project Overview
Minus is an HDMI passthrough system for real-time ML-based ad detection and blocking using dual NPUs on embedded hardware (RK3588 and Axera LLM 8850). The system uses PaddleOCR on RK3588 NPU for text detection (~300ms per frame) and Qwen2.5-VL-2B on Axera NPU for visual language modeling (~1.5s per frame). It integrates with Fire TV devices for control and uses GStreamer for video processing.

## Build & Run
- **Language**: Python 3.x
- **Framework**: none (custom embedded system)
- **Docker image**: python:3.12-slim
- **Install deps**: `pip install -r requirements.txt` (requires `--break-system-packages` on embedded systems)
- **Run**: `python3 minus.py` (main entry point)

## Testing
- **Test framework**: pytest (available via pip), shell scripts in tests/ directory
- **Test command**: `python3 -m pytest test_fire_tv.py -v` or `bash tests/test_*.sh`
- **Hardware mocks needed**: yes — requires RK3588 NPU, Axera LLM 8850 NPU, HDMI-RX hardware, Fire TV device
- **Known test issues**: Tests require embedded hardware; cannot run in standard container environment

## Pipeline History
- Initial project setup with dual NPU architecture
- Integration of PaddleOCR and Qwen2.5-VL-2B models
- Fire TV controller implementation
- Shell test suite for video processing validation

## Known Issues
- Requires external model files at runtime: PaddleOCR models and VLM models in `/home/radxa/axera_models/Qwen2.5-VL-2B/`
- Hardware-dependent: Cannot run without RK3588 and Axera NPUs
- System packages required: `python3-gi`, `gstreamer1.0-tools`, `gstreamer1.0-plugins-good`, `gstreamer1.0-plugins-bad`

## Notes
- Architecture: ustreamer captures HDMI-RX stream, GStreamer processes video, ML models detect ads, overlay system blocks ads
- Web UI available at `/api/status` endpoint
- Shell scripts: `start.sh`, `stop.sh`, `install.sh`, `uninstall.sh` for deployment
- Test scripts in `tests/` directory validate video processing pipelines
