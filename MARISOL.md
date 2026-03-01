# MARISOL.md — Pipeline Context for Minus

## Project Overview
HDMI passthrough system with ML-based ad detection on embedded hardware (RK3588/Axera NPUs), Spanish vocabulary practice during ads, and web UI — but core logic and utilities are testable in isolation.

## Build & Run
- **Language**: python
- **Framework**: none
- **Docker image**: python:3.12-slim
- **Install deps**: `cd /workspace/repo && pip install  -r requirements.txt 2>&1 | tail -5 || true; pip install  pytest 2>&1 | tail -3`
- **Run**: (see source code)

## Testing
- **Test framework**: pytest
- **Test command**: (auto-detected)
- **Hardware mocks needed**: no
- **Last result**: 7/7 passed

