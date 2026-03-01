# MARISOL.md — Pipeline Context

## Project Overview
HDMI passthrough system with real-time ML-based ad detection and blocking using dual NPUs (RK3588 NPU for PaddleOCR, Axera LLM 8850 NPU for Qwen3-VL-2B). When ads are detected, instantly switches to a blocking overlay with Spanish vocabulary practice. Includes web UI for remote monitoring via Tailscale. Core logic and utilities are testable in isolation.

## Build & Run
- **Language**: Python 3.12
- **Framework**: None (standalone application)
- **Docker image**: python:3.12-slim
- **Install deps**: `cd /workspace/repo && pip install -r requirements.txt 2>&1 | tail -5 || true; pip install pytest 2>&1 | tail -3`
- **Run**: `python3 minus.py` (entry point command)

## Testing
- **Test framework**: pytest
- **Test command**: `python -m pytest tests/ -v`
- **Hardware mocks needed**: Yes - requires RK3588 NPU, Axera LLM 8850 NPU, HDMI-RX device
- **Known test issues**: Tests in test_fire_tv.py exist but require hardware mocks; no runnable entry point in container without NPU hardware

## Pipeline History
- Initial setup: Repository contains HDMI passthrough system with dual NPU inference
- Test file present: test_fire_tv.py with 3 test functions
- Current test status: 0 passed, 0 failed, 0 errors (pytest module not installed)

## Known Issues
- pytest module not installed in container environment
- Hardware-dependent tests require RK3588 NPU, Axera LLM 8850 NPU, and HDMI-RX device
- No runnable entry point in container without NPU hardware

## Notes
- Main entry point: minus.py
- Key modules: src/overlay.py for text overlay API
- Web UI port: 8080
- ustreamer stream port: 9090
- Screenshot directories: screenshots/ocr/, screenshots/non_ad/
- Log file: /tmp/minus.log
- Requires external model files at runtime: PaddleOCR models, Qwen3-VL-2B models
