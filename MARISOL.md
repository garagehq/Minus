# MARISOL.md — Pipeline Context

## Project Overview
Minus is an HDMI passthrough system with real-time ML-based ad detection and blocking using dual NPUs. It uses PaddleOCR on RK3588 NPU (~300ms per frame) and Qwen3-VL-2B on Axera LLM 8850 NPU (~1.5s per frame) to detect and block ads in real-time. The system integrates with Fire TV via ADB for control and uses GStreamer for video processing.

## Build & Run
- **Language**: Python 3.x
- **Framework**: none (custom embedded system)
- **Docker image**: python:3.12-slim (for dependency installation only; full system requires RK3588 hardware)
- **Install deps**: `pip3 install --break-system-packages -r requirements.txt` or `sudo pip3 install --break-system-packages -r requirements.txt`
- **Run**: No runnable entry point in container. Hardware-specific system requires RK3588 NPU and Axera LLM 8850. Main entry points:
  - `python3 minus.py` (system initialization)
  - `python3 src/webui.py` (web interface)
  - `./start.sh` (system startup script)

## Testing
- **Test framework**: pytest (but test_fire_tv.py is a standalone script, not pytest tests)
- **Test command**: `python3 test_fire_tv.py` (standalone test script, not pytest)
- **Hardware mocks needed**: yes — requires Fire TV device for ADB connection, RK3588 NPU for OCR, Axera LLM 8850 for VLM
- **Known test issues**: test_fire_tv.py requires external Fire TV device on network; cannot run in isolated container without hardware passthrough

## Pipeline History
- **2024-01-15**: Initial pipeline run - Created MARISOL.md with project context
- **2024-01-15**: Documentation audit - Identified hardware dependency issues and test script limitations
- **2024-01-15**: Test execution attempted - test_fire_tv.py requires live Fire TV device; cannot be fully tested in container environment without hardware passthrough

## Known Issues
1. **test_fire_tv.py fixture errors**: The test script requires a live Fire TV device on the network. Without hardware, the script will fail at connection time with ADB connection errors. Missing fixture: `fire_tv_device` (requires actual hardware).
2. **Hardware dependencies**: The system requires RK3588 NPU and Axera LLM 8850 which cannot run in standard Docker containers without complex host device passthrough. Docker image `python:3.12-slim` is only suitable for dependency installation, not full system testing.
3. **Model files**: External model files required at runtime:
   - PaddleOCR models in standard location
   - VLM models in `/home/radxa/axera_models/Qwen3-VL-2B/`
4. **GStreamer bindings**: Requires system-level installation via `apt install python3-gi gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad`
5. **No pytest tests**: The project uses standalone test scripts (test_fire_tv.py), not pytest. The documented command `python -m pytest test_fire_tv.py -v` will fail because test_fire_tv.py is not a pytest test file.

## Notes
- **Architecture**: Dual NPU system with OCR (RK3588) and VLM (Axera) for real-time ad detection
- **Key files**: 
  - `minus.py` (main entry point)
  - `src/fire_tv.py` (Fire TV controller with ADB integration)
  - `src/ocr.py` (PaddleOCR integration)
  - `src/vlm.py` (Qwen3-VL-2B integration)
  - `src/ad_blocker.py` (ad blocking logic)
  - `src/webui.py` (HTTP interface)
  - `test_fire_tv.py` (standalone test script)
- **Network requirements**: Fire TV device must be on same network for ADB control
- **System dependencies**: GStreamer, RKNN toolkit, Axera SDK (pre-installed on target hardware)
