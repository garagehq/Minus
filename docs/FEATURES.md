# Minus Features

## Overview

Minus is an HDMI passthrough device that detects and blocks advertisements in real-time using dual NPU machine learning.

## Core Features

### Ad Detection

**Dual-NPU ML Pipeline:**
- **PaddleOCR** on RK3588 NPU (~400ms per frame) - Detects text-based ad indicators
- **FastVLM-1.5B** on Axera LLM 8850 NPU (~0.9s per frame) - Visual content analysis

**Detection Methods:**
- OCR keyword matching (Skip, Ad, Advertisement, etc.)
- VLM scene understanding with confidence scoring
- Weighted voting with anti-waffle protection
- Home screen detection to prevent false positives
- Transition frame detection for smoother blocking

### Blocking Overlay

**When ads are detected:**
- Full-screen blocking overlay at 60fps
- Pixelated background from pre-ad content (optional)
- Live preview window showing blocked content
- Spanish vocabulary practice during blocks
- Debug dashboard with stats

**Overlay Features:**
- Smooth animations (0.3s start, 0.25s end)
- Multi-color text rendering via FreeType
- Hardware-accelerated compositing in ustreamer MPP encoder
- Configurable preview window and debug overlay

### Audio Passthrough

**Features:**
- Full HDMI audio passthrough (48kHz stereo)
- Instant mute/unmute during ad blocking
- Automatic A/V sync reset every 45 minutes
- Silent keepalive to prevent pipeline stalls
- Exponential backoff restart on failures

### Fire TV Integration

**Remote Control:**
- Auto-discovery of Fire TV devices on network
- ADB remote control for ad skipping
- Auto-reconnect on connection drops
- Skip button detection via OCR
- Guided setup flow with overlay notifications

**Commands:**
- Navigation: up, down, left, right, select, back, home
- Media: play, pause, fast_forward, rewind
- Volume: volume_up, volume_down, mute
- Power: power, wakeup, sleep

### Web UI

**Remote Monitoring:**
- Live MJPEG video stream
- Status display (blocking state, FPS, HDMI info, uptime)
- Detection history with timestamps
- Log viewer

**Controls:**
- Pause ad blocking (1/2/5/10 minute presets)
- Toggle preview window and debug dashboard
- Test trigger/stop blocking
- Fire TV skip button
- A/V sync reset

**Video Color Controls:**
- Real-time saturation adjustment (0.5-1.5)
- Brightness adjustment (-0.5 to 0.5)
- Contrast adjustment (0.5-1.5)
- Hue adjustment (-0.5 to 0.5)

### Health Monitoring

**Automatic Recovery:**
- HDMI signal detection and recovery
- ustreamer health checks with restart
- Video pipeline watchdog
- Audio pipeline watchdog
- Memory monitoring with cleanup
- VLM degradation to OCR-only mode

**Status Tracking:**
- FPS monitoring (logged every 60s)
- Full status logged every 5 minutes
- Startup grace period for VLM loading

## Spanish Vocabulary Practice

**Content:**
- 500+ intermediate-level words and phrases
- Common verbs, nouns, adjectives, expressions
- False friends and subjunctive triggers
- Pronunciation guides
- Example sentences in context

**Display:**
- Random vocabulary rotation every 11-15 seconds
- Purple Spanish word (IBM Plex Mono Bold)
- White translation (DejaVu Sans Bold)
- Gray pronunciation and example

## Screenshot Collection

**Training Data:**
- `screenshots/ads/` - OCR-detected ads
- `screenshots/non_ads/` - User paused (false positives)
- `screenshots/vlm_spastic/` - VLM uncertainty cases
- `screenshots/static/` - Static screen suppression

**Features:**
- Hash-based deduplication
- Rate limiting
- Configurable max screenshots per folder
- Automatic truncation

## Configuration

**Command Line Options:**
```bash
--device /dev/video1      # Custom capture device
--ocr-timeout 1.5         # OCR timeout in seconds
--max-screenshots 100     # Keep N recent screenshots
--check-signal            # Just check HDMI signal and exit
--connector-id 231        # DRM connector ID
--plane-id 192            # DRM plane ID
--webui-port 80           # Web UI port
```

**Auto-Detection:**
- HDMI output (HDMI-A-1 or HDMI-A-2)
- Display resolution (4K or 1080p)
- NV12-capable DRM plane
- Audio output device

## Systemd Service

**Installation:**
```bash
sudo ./install.sh
```

**Service Features:**
- Starts on boot
- Conflicts with display managers
- Auto-restart on crash
- Journal logging
