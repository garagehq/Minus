# Minus

HDMI passthrough with real-time ML-based ad detection and blocking using dual NPUs:
- **PaddleOCR** on RK3588 NPU (~300ms per frame)
- **Qwen3-VL-2B** on Axera LLM 8850 NPU (~1.5s per frame)

## Architecture

Minus uses a custom pipeline:

1. **ustreamer** captures HDMI input and serves MJPEG stream + HTTP snapshots
2. **GStreamer** with input-selector for instant video/blocking switching
3. **PaddleOCR** (RKNN) detects ad-related text on RK3588 NPU
4. **Qwen3-VL-2B** (Axera) provides visual understanding on Axera LLM 8850 NPU
5. **Spanish vocabulary practice** during ad blocks!

### Key Insight

Using GStreamer input-selector allows instant switching between video and blocking overlay without any process restart or black screen gap.

## Hardware Requirements

- **RK3588** or **Axera LLM 8850** embedded hardware
- HDMI input source (Fire TV, cable box, etc.)
- HDMI output display (via DRM)
- Linux with GStreamer, RKNN toolkit, and Axera NPU drivers

## Installation

### Prerequisites

```bash
# Install system dependencies
sudo apt install python3-pip python3-gi gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad

# Install Python dependencies
pip3 install --break-system-packages -r requirements.txt
# Or with sudo: sudo pip3 install --break-system-packages -r requirements.txt
```

### Model Setup

The executable requires external model files at runtime:
- PaddleOCR models in standard location
- VLM models in `/home/radxa/axera_models/Qwen3-VL-2B/`

## Usage

### Basic Run

```bash
python3 minus.py
```

### Command Line Options

```bash
python3 minus.py --help
```

Options include:
- `--device`: Video device path (default: /dev/video0)
- `--screenshot-dir`: Directory to save screenshots (default: screenshots)
- `--check-signal`: Just check HDMI signal and exit
- `--ocr-timeout`: Skip OCR frames taking longer than this (seconds, default: 1.5)
- `--max-screenshots`: Keep only this many recent screenshots (0=unlimited, default: 50)
- `--connector-id`: DRM connector ID for HDMI output (auto-detected if not specified)
- `--plane-id`: DRM plane ID for video overlay (auto-detected if not specified)
- `--webui-port`: Web UI port (default: 8080)

### Web UI

Access the web interface at `http://localhost:8080` for:
- Real-time video stream
- Manual ad blocking controls
- System health monitoring
- Fire TV setup automation

### Fire TV Controller

Use the Fire TV controller for remote interaction:

```bash
python3 test_fire_tv.py
```

Options:
- `--ip`: Connect to specific Fire TV IP address
- `--interactive`: Interactive mode for remote control
- `--demo`: Run a demo sequence

## Testing

### Fire TV Controller Tests

```bash
python3 test_fire_tv.py --help
```

The test script provides:
- Auto-discovery of Fire TV devices on network
- Interactive mode for manual control
- Demo sequence for testing

### Hardware Testing

Note: Full testing requires embedded hardware. The following checks can be run:

```bash
# Check HDMI signal
python3 minus.py --check-signal

# Verify DRM outputs
modetest -M rockchip -c

# Check GStreamer pipeline
gst-launch-1.0 --help
```

## Architecture Details

### Video Pipeline

```
HDMI Input → ustreamer → MJPEG Stream → GStreamer → DRM Output
                                    ↓
                            OCR/VLM Analysis
                                    ↓
                            Ad Detection → Instant Block
```

### Key Components

- **Minus class** (minus.py): Main orchestrator managing all components
- **PaddleOCR** (src/ocr.py): Text detection using RKNN NPU
- **VLMManager** (src/vlm.py): Visual language model using Axera NPU
- **AdBlocker** (src/ad_blocker.py): Ad detection and blocking logic
- **AudioPassthrough** (src/audio.py): Audio routing to display
- **HealthMonitor** (src/health.py): System health monitoring
- **WebUI** (src/webui.py): Web interface for control
- **FireTVController** (src/fire_tv.py): Fire TV remote control
- **FireTVSetupManager** (src/fire_tv_setup.py): Automated Fire TV setup

### Performance Metrics

- **Display**: 30fps via GStreamer kmssink (NV12 → DRM plane 72)
- **Snapshot**: ~150ms non-blocking HTTP capture
- **OCR**: ~400-500ms per frame on RKNN NPU
- **VLM**: ~1.5s per frame on Axera NPU
- **Ad blocking**: INSTANT switching via input-selector

## Logging

Logs are written to `/tmp/minus.log` with rotation (5MB max, 3 backups).

View logs:
```bash
tail -f /tmp/minus.log
```

## Troubleshooting

### Common Issues

1. **No HDMI signal detected**
   - Check cable connections
   - Verify HDMI source is powered on
   - Run `python3 minus.py --check-signal` to diagnose

2. **DRM output not found**
   - Run `modetest -M rockchip -c` to list available outputs
   - Specify connector ID with `--connector-id`

3. **Web UI not accessible**
   - Check port is not in use: `netstat -tlnp | grep 8080`
   - Verify firewall allows port 8080

4. **Fire TV not discovered**
   - Ensure Fire TV is on same network
   - Enable ADB debugging in Fire TV settings
   - Check ADB connection: `adb devices`

### File Descriptor Leaks

Previously, libjpeg warning suppression caused FD leaks (~500k calls over 13hrs). This was fixed by letting warnings through instead of suppressing them.

## Contributing

This project is designed for embedded hardware. To contribute:

1. Fork the repository
2. Test on target hardware (RK3588 or Axera)
3. Submit pull requests with:
   - Hardware test results
   - Performance benchmarks
   - Documentation updates

## License

MIT
