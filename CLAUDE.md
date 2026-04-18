# Minus - Development Notes

## Overview

HDMI passthrough with real-time ML-based ad detection and blocking using dual NPUs:
- **PaddleOCR** on RK3588 NPU (~400ms per frame)
- **FastVLM-1.5B** on Axera LLM 8850 NPU (~0.7s per frame, 1.5s hard timeout)
- **Spanish vocabulary practice** during ad blocks!

## Documentation

| Document | Description |
|----------|-------------|
| [docs/FEATURES.md](docs/FEATURES.md) | Complete feature list and capabilities |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture and data flow |
| [docs/AESTHETICS.md](docs/AESTHETICS.md) | Visual design guide for UI/overlays |
| [MARISOL.md](MARISOL.md) | AI agent context guide |
| [docs/DEBUG_GLITCHES.md](docs/DEBUG_GLITCHES.md) | Video glitch debugging notes |
| [docs/FPS_DEBUGGING.md](docs/FPS_DEBUGGING.md) | FPS tracking and optimization |
| [docs/AUDIO.md](docs/AUDIO.md) | Audio passthrough documentation |

## Visual Design

See **[docs/AESTHETICS.md](docs/AESTHETICS.md)** for the complete visual design guide including:
- Color palette (black background, matrix green, danger red, purple accents)
- Typography (VT323 for display, IBM Plex Mono for body, DejaVu for TV overlays)
- Component styling and animations
- TV overlay layout specifications

## Architecture

```
┌──────────────┐     ┌────────────────────┐     ┌─────────────────────┐
│   HDMI-RX    │────▶│     ustreamer      │────▶│  GStreamer Pipeline │
│ /dev/video0  │     │ (MJPEG encoding)   │     │  (queue + kmssink)  │
│  4K@30fps    │     │                    │     │                     │
│              │     │   :9090/stream     │     │                     │
│              │     │   :9090/snapshot   │     │                     │
└──────────────┘     └────────┬───────────┘     └─────────────────────┘
                              │
                              ▼ HTTP snapshot (~150ms, non-blocking)
              ┌───────────────┴───────────────┐
              │                               │
     ┌────────┴────────┐           ┌──────────┴──────────┐
     │   OCR Worker    │           │    VLM Worker       │
     │  ┌───────────┐  │           │  ┌───────────────┐  │
     │  │ PaddleOCR │  │           │  │ FastVLM-1.5B  │  │
     │  │ RK3588 NPU│  │           │  │ Axera LLM 8850│  │
     │  │ ~400ms    │  │           │  │ ~0.9s         │  │
     │  └───────────┘  │           │  └───────────────┘  │
     └────────┬────────┘           └──────────┬──────────┘
              │                               │
              └───────────────┬───────────────┘
                              │
                     ┌────────┴────────┐
                     │ Blocking Mode   │
                     │ (ustreamer API) │
                     └─────────────────┘
```

**Key Architecture Points:**
- Simple GStreamer pipeline with `queue max-size-buffers=3 leaky=downstream`
- All blocking overlay rendering done in ustreamer's MPP encoder at 60fps
- No X11 required - uses DRM/KMS directly via kmssink
- **Auto-detects HDMI output, resolution, and DRM plane** at startup
- Works with both 4K and 1080p displays (uses display's preferred resolution)
- Both ML workers run concurrently on separate NPUs
- Display runs independently at 30fps without any stutter

## Key Files

| File | Purpose |
|------|---------|
| `minus.py` | Main entry point - orchestrates everything |
| `minus.spec` | PyInstaller spec for building executable |
| `src/ad_blocker.py` | GStreamer video pipeline, blocking API client |
| `src/audio.py` | GStreamer audio passthrough with mute control |
| `src/ocr.py` | PaddleOCR on RKNN NPU, keyword detection |
| `src/ocr_worker.py` | Process-based OCR with hard timeout, warmup, and keepalive |
| `src/vlm.py` | FastVLM-1.5B on Axera NPU (ad detection + custom queries) |
| `src/vlm_worker.py` | Process-based VLM with hard timeout, warmup, and keepalive |
| `src/autonomous_mode.py` | Autonomous mode - VLM-guided YouTube playback |
| `src/health.py` | Unified health monitor for all subsystems |
| `src/webui.py` | Flask web UI for remote monitoring/control |
| `src/fire_tv.py` | Fire TV ADB remote control for ad skipping |
| `src/roku.py` | Roku ECP remote control |
| `src/device_config.py` | Streaming device type configuration and persistence |
| `src/fire_tv_setup.py` | Fire TV auto-setup flow with overlay notifications |
| `src/wifi_manager.py` | WiFi captive portal and AP mode management |
| `src/overlay.py` | Notification overlay via ustreamer API |
| `src/vocabulary.py` | Spanish vocabulary list (120+ words) |
| `src/console.py` | Console blanking/restore functions |
| `src/drm.py` | DRM output probing, adaptive bandwidth fallback |
| `src/v4l2.py` | V4L2 device probing (format, resolution) |
| `src/config.py` | MinusConfig dataclass |
| `src/capture.py` | UstreamerCapture class for snapshot capture |
| `src/screenshots.py` | ScreenshotManager with dHash dedup + blank rejection |
| `src/skip_detection.py` | Skip button detection (regex patterns) |
| `test_fire_tv.py` | Fire TV controller test and interactive remote |
| `tests/test_modules.py` | Comprehensive test suite (300+ tests) |
| `tests/test_autonomous_mode.py` | Autonomous mode unit tests |
| `tests/test_review_ui.py` | Playwright UI tests for screenshot review |
| `tests/test_ocr_ad_detection.py` | OCR ad pattern detection tests (143+ cases) |
| `src/templates/index.html` | Web UI single-page app |
| `src/static/style.css` | Web UI dark theme styles |
| `install.sh` | Install as systemd service |
| `uninstall.sh` | Remove systemd service |
| `stop.sh` | Graceful shutdown script |
| `minus.service` | systemd service file |
| `screenshots/ads/` | OCR-detected ads (for training) |
| `screenshots/non_ads/` | User paused = false positives (for training) |
| `screenshots/vlm_spastic/` | VLM uncertainty cases (for analysis) |
| `screenshots/static/` | Static screen suppression (still frames) |

## Running

```bash
python3 minus.py
```

**Command-line options:**
```bash
--device /dev/video1      # Custom capture device
--ocr-timeout 1.5         # OCR timeout in seconds (default: 1.5)
--max-screenshots 100     # Keep N recent screenshots (default: 50, 0=unlimited)
--check-signal            # Just check HDMI signal and exit
--connector-id 231        # DRM connector ID (auto-detected if not specified)
--plane-id 192            # DRM plane ID (auto-detected if not specified)
--webui-port 80         # Web UI port (default: 80)
```

**Auto-detection at startup:**
- **Connected HDMI output** - Works with either HDMI-A-1 (connector 215) or HDMI-A-2 (connector 231)
- **Preferred resolution** - Reads EDID to get the display's preferred mode (e.g., 4K@60Hz or 1080p@60Hz)
- **NV12-capable overlay plane** - Finds a suitable DRM plane that supports NV12 format for video output
- **Audio output device** - Matches ALSA device to the connected HDMI output (hw:0,0 for HDMI-A-1, hw:1,0 for HDMI-A-2)

This allows Minus to work with different displays without manual configuration.

**Adaptive HDMI Bandwidth Fallback:**

4K@60Hz RGB/YCbCr 4:4:4 requires 18 Gbps HDMI bandwidth. Some cables, adapters, or display paths can't handle this, resulting in "No Signal" on the TV even though the kernel reports success.

Minus includes adaptive bandwidth detection via `src/drm.py`:

| Function | Purpose |
|----------|---------|
| `get_color_format(connector_id)` | Read current color format (RGB, YCbCr 4:4:4, 4:2:2, 4:2:0) |
| `set_color_format(connector_id, format)` | Set color format with retry logic |
| `check_hdmi_i2c_errors(threshold, window)` | Detect signal problems via dmesg |

**Detection heuristic:** When HDMI signal fails at high bandwidth, the dwhdmi driver floods dmesg with `i2c read err!` messages. This is more reliable than kernel connector status (which shows "connected" even when signal fails).

**Color format values:**
- `COLOR_FORMAT_RGB` (0) - Full bandwidth
- `COLOR_FORMAT_YCBCR444` (1) - Full bandwidth
- `COLOR_FORMAT_YCBCR422` (2) - Reduced bandwidth
- `COLOR_FORMAT_YCBCR420` (3) - **Half bandwidth (9 Gbps)** - use for problematic cables

**Manual fallback:**
```bash
# Stop minus first (it holds DRM master lock)
sudo systemctl stop minus

# Set YCbCr 4:2:0 for half bandwidth
sudo modetest -M rockchip -w 215:color_format:3

# Restart minus
sudo systemctl start minus
```

**Environment variables:**
```bash
# Paths (override defaults for different installations)
MINUS_USTREAMER_PATH=/path/to/ustreamer     # Default: /home/radxa/ustreamer-patched
MINUS_VLM_MODEL_DIR=/path/to/vlm/models     # Default: /home/radxa/axera_models/FastVLM-1.5B
MINUS_OCR_MODEL_DIR=/path/to/ocr/models     # Default: /home/radxa/rknn-llm/.../paddleocr

# Timing thresholds
MINUS_ANIMATION_START=0.3        # Blocking animation duration (seconds)
MINUS_ANIMATION_END=0.25         # Unblocking animation duration (seconds)
MINUS_FRAME_STALE_THRESHOLD=5.0  # Health check frame freshness (seconds)
MINUS_DYNAMIC_COOLDOWN=0.5       # Wait after screen becomes dynamic (seconds)
MINUS_SCENE_CHANGE_THRESHOLD=0.01  # Frame difference threshold for scene change
MINUS_VLM_ALONE_THRESHOLD=5      # Consecutive VLM detections needed to trigger alone
```

## Performance

| Metric | Value |
|--------|-------|
| Display (video) | **30fps** (GStreamer kmssink, MJPEG → NV12 → DRM plane) |
| Display (blocking) | **60fps** (ustreamer MPP blocking mode with FreeType) |
| Preview window | **60fps** (hardware-scaled in MPP encoder) |
| Blocking composite | **~0.5ms** per frame overhead |
| Audio mute/unmute | **INSTANT** (volume element mute property) |
| ustreamer MJPEG stream | **~60fps** (MPP hardware encoding at 4K) |
| OCR latency | **100-200ms** capture + **250-400ms** inference |
| VLM latency | **~0.7s per frame** (FastVLM-1.5B, process-based with 1.5s hard timeout) |
| VLM model load | **~25s** (includes 2 warmup inferences + keepalive thread) |
| Snapshot capture | **~150ms** (4K JPEG download) |
| OCR image size | 960x540 (downscaled from 4K for speed) |
| ustreamer quality | 80% JPEG (MPP encoder) |
| Animation start | **0.3s** (fast blocking response) |
| Animation end | **0.25s** (fast unblocking) |

**FPS Tracking:**
- GStreamer identity element with pad probe counts frames
- FPS logged every 60 seconds via health monitor
- Warning logged if FPS drops below 25

## ustreamer-patched (NV12 + MPP Hardware Encoding)

We use a patched version of ustreamer from `garagehq/ustreamer` that adds:
- **NV12/NV16/NV24 format support** for RK3588 HDMI-RX devices
- **MPP hardware JPEG encoding** using RK3588 VPU (~60fps at 4K!)
- **Blocking mode system** with FreeType TrueType rendering for ad blocking overlays
- **Extended timeouts** for RK3588 HDMI-RX driver compatibility
- **Multi-worker MPP support** (4 parallel encoders optimal)
- **Cache sync fix** for DMA-related visual artifacts
- **Thread-safe FreeType** mutex for multi-worker encoding

**Why patched ustreamer?**
The stock PiKVM ustreamer doesn't support NV12 format or RK3588 hardware encoding.
Our fork adds NV12→JPEG encoding via Rockchip MPP (Media Process Platform) that
achieves ~60fps on 4K input with minimal CPU usage.

**Dynamic Format Detection:**
Minus automatically probes the V4L2 device to detect its current format and resolution. Supported formats:
- **NV12** - RK3588 HDMI-RX native (uses MPP hardware encoder directly)
- **NV24** - Some devices like Roku (converted to NV12 for MPP, ~60fps)
- **BGR24/BGR3** - Google TV and similar devices (converted to NV12 for MPP, ~42fps at 4K)
- **YUYV/UYVY** - Webcam-style devices
- **MJPEG** - Pre-compressed JPEG sources

Format conversions (NV24→NV12, BGR24→NV12) are done in software in the MPP encoder before hardware JPEG encoding.

**Performance comparison (4K HDMI input):**

| Mode | ustreamer FPS | CPU Usage | Notes |
|------|---------------|-----------|-------|
| CPU encoding | ~4 fps | ~100% | CPU can't keep up with 4K JPEG encoding |
| MPP hardware | **~60 fps** | **~5%** | `--encoder=mpp-jpeg` (default) |

**ustreamer command (used by Minus):**
```bash
/home/radxa/ustreamer-patched \
  --device=/dev/video0 \
  --format=NV12 \
  --resolution=3840x2160 \
  --persistent \
  --port=9090 \
  --host=0.0.0.0 \
  --encoder=mpp-jpeg \
  --encode-scale=passthrough \
  --quality=80 \
  --workers=4 \
  --buffers=5
```

**Installation:**
```bash
# Clone and build with MPP support
git clone https://github.com/garagehq/ustreamer.git /home/radxa/ustreamer-garagehq
cd /home/radxa/ustreamer-garagehq
make WITH_MPP=1
cp ustreamer /home/radxa/ustreamer-patched

# Minus uses /home/radxa/ustreamer-patched automatically
```

**Key changes in garagehq/ustreamer:**
- `src/ustreamer/encoders/mpp/encoder.c` - MPP hardware JPEG encoder with cache sync, blocking composite, NV24→NV12 and BGR24→NV12 format conversion
- `src/libs/capture.c` - NV12/NV16/NV24/BGR24 format support, extended timeouts
- `src/libs/blocking.c` - FreeType text rendering, NV12 compositing, thread-safe mutex
- `src/ustreamer/http/server.c` - Blocking API endpoints (`/blocking`, `/blocking/set`, `/blocking/background`)
- `src/ustreamer/encoder.c` - MPP encoder integration, multi-worker support
- `src/ustreamer/options.c` - `--encoder=mpp-jpeg` CLI option

## Audio Passthrough

**Hardware:**
- Capture: `hw:4,0` (rockchip,hdmiin) - HDMI-RX audio input
- Playback: `hw:0,0` (rockchip-hdmi0) - HDMI-TX0 output
- Format: 48kHz, stereo, S16LE

**GStreamer Pipeline:**
```
alsasrc (HDMI) ──┐
                 ├──► audiomixer ──► volume ──► alsasink
audiotestsrc ────┘
(silent keepalive)
```

The `audiotestsrc wave=silence` provides a silent keepalive that prevents pipeline stalls when the HDMI source has no audio (between songs, during video silence, etc.).

**Mute Control:**
- `ad_blocker.show()` calls `audio.mute()` - instant mute during ads
- `ad_blocker.hide()` calls `audio.unmute()` - restore audio after ads
- Uses GStreamer `volume` element's `mute` property (no pipeline restart)

**Why separate pipeline?**
- Audio runs independently from video - simpler debugging
- If audio fails, video continues unaffected
- No sync issues for live passthrough

**Error Recovery:**
- GStreamer bus monitors for pipeline errors and EOS
- Buffer probe tracks audio flow (detects stalls)
- Watchdog thread checks every 3s, restarts if no buffer for 6s
- Exponential backoff for restarts (1s → 2s → 4s → ... → 60s max)
- No maximum restart limit - always tries to recover
- Backoff resets after 5 seconds of sustained audio flow
- Mute state is preserved across restarts

**Testing:**
```bash
# Test passthrough manually
gst-launch-1.0 alsasrc device=hw:4,0 ! \
  "audio/x-raw,rate=48000,channels=2,format=S16LE" ! \
  audioconvert ! audioresample ! \
  alsasink device=hw:0,0 sync=false

# Check if HDMI source has audio
v4l2-ctl -d /dev/video0 --get-ctrl audio_present
```

## Ad Detection Logic (Weighted Model)

**OCR (Primary - Authoritative):**
- Triggers blocking immediately on 1 detection
- Stops blocking after 4 consecutive no-ads (`OCR_STOP_THRESHOLD`)
- **Authoritative for stopping** when OCR triggered the block
- Tracks `last_ocr_ad_time` for VLM context
- Handles common OCR misreads in ad timestamps (see below)

**VLM (Secondary - Anti-Waffle Protected):**
- Uses sliding window of last 45 seconds of VLM decisions (`vlm_history_window`)
- Only triggers blocking alone if 80%+ of recent decisions are "ad" (`vlm_start_agreement`)
- Hysteresis: needs 90% agreement to START (80% + 10% boost for state change)
- Minimum 4 decisions in window before VLM can act (`vlm_min_decisions`)
- 8-second cooldown after state changes prevents rapid flip-flopping (`vlm_min_state_duration`)
- **Sliding window only for starting** - stopping uses simple consecutive count

**Sliding Window Parameters:**
| Parameter | Value | Purpose |
|-----------|-------|---------|
| `vlm_history_window` | 45s | How far back to look at VLM decisions |
| `vlm_min_decisions` | 4 | Minimum decisions needed before acting |
| `vlm_start_agreement` | 80% | Agreement threshold to start blocking |
| `vlm_hysteresis_boost` | 10% | Extra agreement needed to change state |
| `vlm_min_state_duration` | 8s | Cooldown after VLM state change |

**Transition Frame Detection:**
When blocking is active, black/solid-color frames are detected as transitions between ads and held in blocking state to prevent premature unblocking and re-blocking flicker. The `_is_transition_frame()` method analyzes:
- Mean brightness < 30 with low std deviation → black screen
- Low std deviation across frame → solid color
- >95% pixels within 20 values of median → uniform/static

**Starting Blocking:**
1. OCR detects ad → blocking starts immediately (unless home screen detected)
2. VLM detects ad (no OCR) → needs 80%+ agreement in sliding window (4+ decisions)
3. VLM with recent OCR → trusted, triggers blocking
4. Home screen detection suppresses both OCR and VLM blocking on streaming interfaces

**Stopping Blocking:**
1. **If OCR triggered** (source=ocr or both): OCR says stop (4 no-ads) → ends immediately (~2-3s)
2. **If VLM triggered alone** (source=vlm): VLM says stop (2 no-ads) → ends (~4s after ad ends)
3. VLM history cleared on stop → prevents immediate re-trigger
4. VLM stop uses simple consecutive count, NOT sliding window (for responsiveness)

**Why This Design:**
- VLM sliding window prevents erratic false-positive blocking when acting alone
- OCR is authoritative for stopping OCR-triggered blocks (fast unblock)
- VLM-triggered blocks require VLM to confirm ad ended (since OCR never saw it)
- Clearing VLM history on stop prevents "waffle memory" from causing re-triggers
- VLM stopping uses simple consecutive count (not sliding window) for responsiveness

**Anti-flicker:**
- Minimum 3s blocking duration (`MIN_BLOCKING_DURATION`)
- VLM history cleared on stop prevents false re-triggers
- Transition frame detection holds blocking through black screens between ads

**Static Screen Suppression:**
- Prevents blocking on paused video screens (Netflix/YouTube show ads when paused)
- After 2.5s of static screen (`STATIC_TIME_THRESHOLD`), blocking is suppressed
- When video resumes, 0.5s cooldown (`DYNAMIC_COOLDOWN`) before re-enabling blocking
- Detection state (OCR/VLM) cleared on cooldown complete to prevent false positives
- Static ad screenshots saved to `screenshots/static/` for analysis

**OCR Timestamp Pattern Handling:**
OCR frequently misreads characters in ad timestamps. The detection handles these common confusions:

| Intended | OCR Misreads | Example |
|----------|--------------|---------|
| `0` (zero) | `o`, `O` | "Ad0:30" → "Ado:30", "AdO:30" |
| `1` (one) | `l`, `L`, `I`, `i` | "Ad1:30" → "Adl:30", "AdI:30" |
| `:` (colon) | `;`, `.` | "Ad0:30" → "Ad0;30", "Ad0.30" |

Combined misreads are also handled (e.g., "Adl;lo" for "Ad1:10"). The timestamp pattern matches:
- Standard: `Ad 0:30`, `Ad0:30`, `Ad1:45`
- Zero misreads: `Ado:30`, `Ad0:3o`, `Ado:oo`
- One misreads: `Adl:30`, `Ad1:l5`, `Adl:lo`
- Separator misreads: `Ad0;30`, `Ad0.30`, `Ado;3o`

## Blocking Overlay

When ads are detected, the screen shows a full blocking overlay **rendered at 60fps via ustreamer's native MPP blocking mode**:
- **Pixelated Background**: Blurred/pixelated version of the screen from ~6 seconds before the ad
- **Header**: `BLOCKING (OCR)`, `BLOCKING (VLM)`, or `BLOCKING (OCR+VLM)`
- **Spanish vocabulary**: Random intermediate-level word with translation
- **Example sentence**: Shows the word in context
- **Rotation**: New vocabulary every 11-15 seconds
- **Ad Preview Window**: Live preview of the blocked ad in bottom-right corner (60fps!)
- **Debug Dashboard**: Stats overlay in bottom-left corner

**Multi-color Text Per Line:**
- **Purple** - Spanish word (IBM Plex Mono Bold font)
- **White** - Header and translation (DejaVu Sans Bold font)
- **Gray** - Pronunciation and example sentence (DejaVu Sans Bold font)

**Font Configuration:**
- `FONT_PATH_VOCAB_PRIMARY` = DejaVu Sans Bold (vocabulary text, centered)
- `FONT_PATH_WORD_PRIMARY` = IBM Plex Mono Bold (Spanish word, purple)
- `FONT_PATH_STATS_PRIMARY` = IBM Plex Mono Regular (debug stats, monospace)

**Rendering Pipeline:**
All overlay rendering is done inside ustreamer's MPP encoder, NOT GStreamer:
1. `ad_blocker.py` captures pre-ad frame and creates pixelated NV12 background
2. Background uploaded via `POST /blocking/background` (async, non-blocking)
3. Text and preview configured via `GET /blocking/set`
4. FreeType renders TrueType fonts directly to NV12 planes at encoder resolution
5. Composite runs at 60fps with ~0.5ms overhead per frame

**Pixelated Background:**
Instead of a plain black background, the blocking overlay shows a heavily pixelated (20x downscale) and darkened (60% brightness) version of what was on screen before the ad appeared. This provides visual context while clearly indicating blocking is active.

Implementation (`src/ad_blocker.py`):
- Rolling 6-second snapshot buffer (3 frames at 2-second intervals)
- Uses oldest frame when blocking starts (ensures pre-ad content)
- OpenCV pixelation: downscale by 20x, upscale with INTER_NEAREST
- Converted to NV12 and uploaded via `/blocking/background` POST API
- Upload runs in background thread for non-blocking operation

**Preview Window:**
Unlike the old GStreamer approach (limited to ~4fps), the ustreamer blocking mode provides:
- Full 60fps live preview of the blocked ad
- Hardware-accelerated scaling in the MPP encoder
- Automatic resolution handling (works at 1080p, 2K, 4K)

**Web UI Toggles:** Ad Preview Window and Debug Dashboard toggleable via Settings (both default ON)

## Spanish Vocabulary

120+ intermediate-level words and phrases including:
- **Common verbs**: aprovechar, lograr, desarrollar, destacar, enfrentar...
- **Reflexive verbs**: comprometerse, enterarse, arrepentirse, darse cuenta...
- **Adjectives**: disponible, imprescindible, agotado, capaz, dispuesto...
- **Nouns**: desarrollo, comportamiento, conocimiento, ambiente, herramienta...
- **Expressions**: sin embargo, a pesar de, de repente, hoy en dia, cada vez mas...
- **False friends**: embarazada, exito, sensible, libreria, asistir...
- **Subjunctive triggers**: es importante que, espero que, dudo que, ojala...
- **Time expressions**: hace poco, dentro de poco, a la larga, de antemano...

## Housekeeping

**Log File:**
- Location: `/tmp/minus.log`
- Max 5MB per log file
- Keeps 3 backup files (minus.log.1, .2, .3)

**Screenshot Truncation:**
- Keeps only last 50 screenshots by default
- Configurable via `--max-screenshots`

## VLM Model

**FastVLM-1.5B** on Axera LLM 8850 NPU:
- Smarter than 0.5B with fewer false positives on streaming interfaces
- **~0.7s** inference time for ad detection (process-based with 1.5s hard timeout)
- **~1.0s** for custom queries (structured prompt)
- **~25s** model load time (includes 2 warmup inferences)
- Uses Python axengine + transformers tokenizer
- Home screen detection provides additional safety net

**Process-based architecture (`src/vlm_worker.py`):**
- VLM runs in a separate process for hard timeout capability
- If inference exceeds 1.5s, process is KILLED and restarted (not just timed out)
- 2 warmup inferences at startup to avoid cold-start slowness
- Keepalive thread runs dummy inference every 20s during idle to prevent NPU cold-start
- Worker process loads model once, processes requests via Queue

**Two inference modes:**
- `detect_ad(image_path)` → `(is_ad, response_text, elapsed, confidence)` — ad/not-ad classification
- `query_image(image_path, prompt)` → `(response_text, elapsed)` — custom prompt for any question about the image (used by Autonomous Mode for screen state classification)

Both modes share the same model and are serialized via the worker process queue.

```
/home/radxa/axera_models/FastVLM-1.5B/
├── fastvlm_ax650_context_1k_prefill_640_int4/  # LLM decoder models
│   ├── image_encoder_512x512.axmodel           # Vision encoder
│   ├── llava_qwen2_p128_l*.axmodel             # 28 decoder layers
│   └── model.embed_tokens.weight.npy           # Embeddings (float32)
├── fastvlm_tokenizer/                           # Tokenizer files
└── utils/                                       # LlavaConfig and InferManager
```

**Why FastVLM-1.5B instead of 0.5B?**
| Aspect | FastVLM-0.5B | FastVLM-1.5B |
|--------|--------------|--------------|
| Inference Time | 0.7s | 0.9s |
| False Positive Rate | ~88% on home screens | ~36% on home screens |
| Intelligence | Basic | **Much smarter** |
| Parameters | 0.5B | **1.5B** |

## Dependencies

```bash
# System packages
sudo apt install -y imagemagick ffmpeg curl v4l-utils

# GStreamer and plugins for video pipeline
sudo apt install -y \
  gstreamer1.0-tools \
  gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-rockchip1 \
  gir1.2-gst-plugins-base-1.0 \
  libgstreamer1.0-dev

# Build ustreamer with MPP hardware encoding and FreeType fonts
sudo apt install -y librockchip-mpp-dev libfreetype-dev libjpeg-dev libevent-dev
git clone https://github.com/garagehq/ustreamer.git /home/radxa/ustreamer-garagehq
cd /home/radxa/ustreamer-garagehq && make WITH_MPP=1
cp ustreamer /home/radxa/ustreamer-patched

# Fonts for blocking overlay
sudo apt install -y fonts-dejavu-core fonts-ibm-plex

# Python dependencies
pip3 install --break-system-packages \
  pyclipper shapely numpy opencv-python \
  pexpect PyGObject flask requests androidtv \
  rknnlite  # RKNN NPU runtime for OCR (may need Rockchip's pip repo)
```

**Note:** The `rknnlite` package is provided by Rockchip and may need to be installed from their SDK or a custom repository. On the Radxa board with NPU support, it may already be pre-installed.

**Axera NPU (for VLM):**
The FastVLM-1.5B model runs on the Axera LLM 8850 NPU. Required Python packages:
```bash
pip3 install --break-system-packages axengine transformers ml_dtypes
```
The `axengine` package requires the Axera AXCL runtime to be installed - see the Axera documentation.

## Troubleshooting

**ustreamer fails to start:**
```bash
fuser -k /dev/video0  # Kill processes using device
pkill -9 ustreamer    # Kill orphaned ustreamer
```

**VLM not loading:**
- Check Axera card: `axcl_smi`
- Verify model files exist in `/home/radxa/axera_models/FastVLM-1.5B/`
- Ensure Python dependencies: `pip3 show axengine transformers ml_dtypes`

**OCR not detecting:**
- Test snapshot: `curl http://localhost:9090/snapshot -o test.jpg`
- Check HDMI: `v4l2-ctl -d /dev/video0 --query-dv-timings`

**Display issues:**
- Check DRM plane: `modetest -M rockchip -p | grep -A5 "plane\[72\]"`
- Verify connector: `modetest -M rockchip -c | grep HDMI`

## CRITICAL: Blocking Mode Architecture

**NEVER REVERT TO GSTREAMER TEXTOVERLAY FOR BLOCKING OVERLAYS.**

The blocking overlay system uses ustreamer's native MPP blocking mode (`/blocking/*` API), NOT GStreamer's input-selector or textoverlay. This is a one-way migration - we only move forward.

**Current Architecture:**
- Simple GStreamer pipeline with `queue max-size-buffers=3 leaky=downstream` for smooth video
- All blocking compositing (background, preview, text) done in ustreamer's MPP encoder at 60fps
- Control via HTTP API: `/blocking/set`, `/blocking/background`
- FreeType TrueType font rendering:
  - **IBM Plex Mono Bold** for Spanish word (purple, centered)
  - **DejaVu Sans Bold** for vocabulary text (white/gray, centered)
  - **IBM Plex Mono Regular** for stats dashboard (bottom-left, monospace)
- Per-line multi-color text matching web UI aesthetic (see AESTHETICS.md)
- Thread-safe with mutex protection for 4 parallel MPP encoder workers

**Resolution Flexibility:**
The blocking system automatically handles resolution mismatches:
- API calls may specify 4K dimensions (3840x2160)
- With `--encode-scale passthrough`, encoder uses source resolution directly
- Preview dimensions are scaled proportionally to fit
- Positions are clamped to valid ranges
- All coordinates aligned to even values for NV12

**Thread Safety:**
FreeType is NOT thread-safe. With 4 parallel MPP encoder workers, a `pthread_mutex_t _ft_mutex` serializes all FreeType calls in the composite function to prevent crashes. Without this, concurrent FT_Set_Pixel_Sizes/FT_Load_Glyph calls corrupt FreeType's internal state.

**Why NOT GStreamer textoverlay:**
- Caused pipeline stalls every ~12 seconds
- NV12 format incompatibility issues
- 4K→1080p resolution mismatch problems
- gdkpixbufoverlay limited to ~4fps for preview updates
- Complex input-selector switching logic

**Key files:**
- `ustreamer-garagehq/src/libs/blocking.c` - NV12 compositing with FreeType, mutex protection
- `ustreamer-garagehq/src/libs/blocking.h` - Blocking mode API
- `src/ad_blocker.py` - Python client using blocking API

## ustreamer Overlay and Blocking API

**Notification Overlay** (for Fire TV setup messages, etc.):
- `GET /overlay` - Get current overlay configuration
- `GET /overlay/set?params` - Set overlay configuration

| Parameter | Description |
|-----------|-------------|
| `text` | Text to display (URL-encoded, supports newlines) |
| `enabled` | `true` or `1` to enable overlay |
| `position` | 0=top-left, 1=top-right, 2=bottom-left, 3=bottom-right, 4=center |
| `scale` | Text scale factor (1-10) |
| `color_y`, `color_u`, `color_v` | Text color in YUV |
| `bg_enabled` | Enable background box |
| `bg_alpha` | Background transparency (0-255) |
| `clear` | Clear overlay |

**Example:**
```bash
curl "http://localhost:9090/overlay/set?text=LIVE&position=1&scale=3&enabled=true"
curl "http://localhost:9090/overlay/set?clear=true"
```

**Blocking Mode** (for ad blocking overlays):

**Blocking Mode Endpoints:**
- `GET /blocking` - Get current config (enabled, preview, colors, etc.)
- `GET /blocking/set?enabled=true&text_vocab=...&preview_enabled=true` - Configure
- `POST /blocking/background` - Upload pixelated NV12 background (width*height*1.5 bytes)

**Multi-color text auto-detection:** Lines starting with `[` → white (header), `(` → gray (pronunciation), `=` → white (translation), `"` → gray (example), other → purple (Spanish word)

## Overlay Priority System

The overlay system includes a priority mechanism to handle multiple overlays gracefully:

**Persistent Overlays:**
- Setup instructions (Roku Limited Mode, Fire TV ADB Enable) are "persistent"
- Registered with duration > 60 seconds
- Have a background monitor thread that checks every 5 seconds
- Auto-restore if overwritten by short notifications (VLM status, etc.)

**Short Overlays:**
- Status notifications (VLM Ready, Connected, etc.) are short-lived (5-10s)
- Can temporarily interrupt persistent overlays
- After they expire, the persistent overlay is automatically restored

**State Changes:**
- Successful device connection calls `_clear_persistent()` to dismiss setup instructions
- This prevents stale setup overlays from reappearing after connection

**Implementation:**
- Module-level singleton state in `src/overlay.py` (`_overlay_state` dict)
- Monitor thread spawned by `_set_persistent()` polls ustreamer overlay API
- Compares current overlay text to expected text, restores if different

## Health Monitoring

The health monitor (`src/health.py`) runs in a background thread and checks:

| Subsystem | Check | Recovery |
|-----------|-------|----------|
| HDMI signal | v4l2-ctl --query-dv-timings | Show "NO SIGNAL" overlay, mute audio |
| No HDMI at startup | check_hdmi_signal() | Show bouncing "NO SIGNAL" screensaver |
| ustreamer | HTTP HEAD to :9090/snapshot | Restart ustreamer + video pipeline |
| Video pipeline | Buffer flow + FPS monitoring | Restart pipeline with exponential backoff |
| Output FPS | GStreamer pad probe | Log warning if < 25fps |
| VLM | Consecutive timeouts < 5 | Degrade to OCR-only, retry VLM after 30s |
| Memory | Usage < 90% | Force GC, clear frame buffers |
| Disk | Free > 500MB | Log warning |

**HDMI Disconnect/Reconnect Recovery:**
- Detects HDMI signal loss via ustreamer's `/state` API (`captured_fps` field)
- Signal considered lost if FPS is 0 for more than 5 seconds (handles source going to sleep)
- Shows "NO SIGNAL" overlay and mutes audio immediately
- On signal restoration: restarts ustreamer → restarts video pipeline → restores display
- Full recovery typically completes in ~7 seconds

**Display Output Resilience (HDMI-TX Disconnected):**
- Service continues running even if HDMI-TX display output is disconnected
- ustreamer runs independently for web preview and ML detection
- Web UI shows "DISPLAY DISCONNECTED" overlay with grayscale video feed underneath
- Display retry loop attempts reconnection every 7 seconds (only display pipeline, not ustreamer)
- OCR/VLM ad detection continues working without display output
- API exposes `display_connected` and `display_error` fields in `/api/status`

**Video Pipeline Watchdog:**
- Buffer watchdog detects stalls (10 seconds without buffer)
- Monitors GStreamer pipeline state (must be PLAYING)
- Handles HTTP connection errors from souphttpsrc
- Handles unexpected EOS (end-of-stream) events
- Exponential backoff for restarts (1s → 2s → 4s → ... → 30s max)
- Backoff resets after 10 seconds of sustained buffer flow

**Startup grace period:**
- 30-second grace period before ustreamer health checks begin
- Prevents false positives during VLM model loading

**Graceful degradation (startup):**
- OCR initialization: 3 retries with 2s delay, continues without OCR if all fail
- VLM model loading: 3 retries with 5s delay, continues without VLM if all fail
- Both failures are non-fatal — the system runs with whatever subsystems loaded
- `ocr_ready` and `ocr_disabled` fields in `/api/status` (matching existing `vlm_ready`/`vlm_disabled`)
- OCR status badge in web UI header: `OCR: Ready / Disabled / Failed`

**Graceful degradation (runtime):**
- If VLM fails 5+ times consecutively, switches to OCR-only mode
- VLM restart is attempted after 30 seconds in background
- OCR continues working independently

**Scene skip cap:**
- OCR: Force run after 30 consecutive skips
- VLM: Force run after 10 consecutive skips
- Prevents missing ads that appear without scene change

**Periodic logging:**
- FPS logged every 60 seconds
- Full status logged every 5 minutes (uptime, fps, hdmi, video, audio, vlm, mem, disk)

## Web UI

Minus includes a lightweight Flask-based web UI for remote monitoring and control, accessible via Tailscale from desktop or mobile devices.

**Features:**
- **Live video feed** - MJPEG stream proxied from ustreamer (CORS bypass)
- **Status display** - Blocking state, FPS, HDMI info, uptime
- **Pause controls** - 1/2/5/10 minute presets to pause ad blocking
- **Detection history** - Recent OCR/VLM detections with timestamps
- **Settings** - Toggle preview window and debug dashboard
- **Log viewer** - Collapsible log output for debugging

**Key API Routes:**
- `GET /`, `/api/status`, `/api/detections`, `/api/logs`
- `POST /api/pause/N`, `/api/resume`
- `GET/POST /api/preview/*`, `/api/debug-overlay/*`
- `POST /api/test/trigger-block`, `/api/test/stop-block`
- `GET /stream`, `/snapshot` - Proxy to ustreamer
- `GET /api/health` - Health check for uptime monitors
- `POST /api/video/restart` - Force restart video pipeline
- `GET/POST /api/video/color` - Get/set color settings (saturation, brightness, contrast, hue)
- `POST /api/ocr/test` - Run OCR on current frame (no screenshot save)
- `POST /api/vlm/test` - Run VLM on current frame (no screenshot save)
- `GET /api/vlm/status` - Get VLM status (disabled, model_loaded, etc.)
- `POST /api/vlm/disable` - Disable VLM and unload model from NPU
- `POST /api/vlm/enable` - Re-enable VLM and load model
- `POST /api/blocking/skip` - Trigger Fire TV skip button
- `POST /api/audio/sync-reset` - Reset A/V sync (~300ms dropout)
- `GET /api/autonomous` - Autonomous mode status
- `POST /api/autonomous/enable` / `disable` / `toggle` / `start` - Control autonomous mode
- `POST /api/autonomous/schedule` - Set schedule (start_hour, end_hour, always_on)
- `GET /api/autonomous/logs` - Autonomous mode log entries
- `GET /api/screenshots/review/<category>` - Unreviewed screenshots for swipe classification
- `POST /api/screenshots/approve` - Mark screenshot as correctly labeled
- `POST /api/screenshots/classify` - Move screenshot between categories
- `POST /api/screenshots/undo` - Undo last review action

**Test API Endpoints:**
For development and testing ad blocking without waiting for real ads:
```bash
# Trigger blocking for 20 seconds (max 60)
curl -X POST -H "Content-Type: application/json" \
  -d '{"duration": 20, "source": "ocr"}' \
  http://localhost:80/api/test/trigger-block

# Stop blocking immediately
curl -X POST http://localhost:80/api/test/stop-block
```

Parameters for trigger-block:
- `duration`: seconds to block (default: 10, max: 60)
- `source`: detection source - 'ocr', 'vlm', 'both', or 'default'

Test mode prevents the detection loop from canceling the blocking, allowing full testing of pixelated background, animations, and audio muting.

**Access URLs:**
- Local: `http://localhost:80`
- Tailscale: `http://<tailscale-hostname>:80`
- Direct stream: `http://<hostname>:9090/stream`

**Security:**
- No authentication (relies on Tailscale network security)
- Read-mostly API with minimal attack surface
- Binds to 0.0.0.0 for remote access

## VLM Training Data Collection

Minus automatically collects training data for future VLM improvements, organized by type:

**Screenshot directories:**
- `screenshots/ads/` - OCR-detected ads
- `screenshots/non_ads/` - User paused = false positives
- `screenshots/vlm_spastic/` - VLM uncertainty cases (detected 2-5x then changed)
- `screenshots/static/` - Static screen suppression

**Screenshot Quality Filtering (all categories):**

Every save goes through `_should_save()` which applies three layers of filtering:

| Layer | What it catches | Threshold |
|-------|----------------|-----------|
| Rate limiting | Rapid-fire saves | 5s minimum between saves per category |
| Blank rejection | Black/solid-color frames | Mean brightness < 15 or std dev < 10 |
| dHash dedup | Near-duplicate frames | Hamming distance < 10 bits (~85% similar) |

**dHash (Difference Hash):**
- Resize frame to 9x8 grayscale, compare adjacent pixels → 64-bit hash
- Two frames of the same ad with slightly different timestamps: hamming distance ~1-5
- A genuinely different scene: hamming distance ~20-30
- Keeps last 200 hashes per category for rolling dedup window

**Screenshot Review System (Tinder-style):**

The web UI includes a swipe-based review system for classifying screenshots:
- Each screenshot tab (Ads, Non-Ads, VLM Spastic, Static) has a 👀 review button
- Opens a full-screen modal with a 3-card visual stack
- **Swipe right** (or arrow key) = approve / classify as ad
- **Swipe left** (or arrow key) = reclassify / classify as not ad
- **Undo** (Ctrl+Z or button) reverses the last action
- Progress tracked in `/home/radxa/.minus_reviewed_screenshots.json` — shows oldest unreviewed first

| Category | Swipe Right | Swipe Left |
|----------|-------------|------------|
| Ads | Approved (correct) | Move to Non-Ads |
| Non-Ads | Approved (correct) | Move to Ads |
| VLM Spastic | Move to Ads | Move to Non-Ads |
| Static | Move to Ads | Move to Non-Ads |

**Review API:**
- `GET /api/screenshots/review/<category>` - Unreviewed items, oldest first
- `POST /api/screenshots/approve` - Mark as correctly labeled
- `POST /api/screenshots/classify` - Move between categories
- `POST /api/screenshots/undo` - Undo last action

## Autonomous Mode

Autonomous Mode keeps YouTube playing on streaming devices during scheduled hours so Minus can collect ad detection training data unattended. Device-agnostic design supports Fire TV, Roku, and Google TV. Uses VLM to understand screen state and take intelligent actions.

**How it works:**
1. **Schedule** — Configurable start/end hours (e.g., 22:00–06:00), or 24/7 mode
2. **OCR-based screen detection** — Before VLM, checks OCR text for login/home screen keywords (VLM often misclassifies these static screens as "PLAYING")
3. **VLM-guided keepalive** — Every 2 minutes, captures a frame and asks VLM to classify the screen state
4. **Roku ECP active app check** — Before VLM, queries Roku's `/query/active-app` API to detect if YouTube exited or screensaver activated (more reliable than VLM for Roku)
5. **Frame-change + audio verification** — After VLM says "PLAYING", verifies with dHash frame comparison + audio flow check to catch paused videos VLM misclassifies
6. **Smart actions** — Based on combined signals, takes the minimum necessary action:

| Signal | Action | Command |
|--------|--------|---------|
| OCR: login screen keywords | Select account | `down` + `select` |
| OCR: home screen keywords + static | Select video | `down` + `select` |
| VLM: PLAYING + frames changing | None | Video is fine |
| VLM: PLAYING + static + no audio | Play | `play_pause` (paused video VLM missed) |
| VLM: PLAYING + static + audio flowing | None | Music stream with static image (lo-fi) |
| VLM: PAUSED | Play | `play_pause` key |
| VLM: DIALOG | Dismiss | `select` + `play_pause` |
| VLM: MENU | Select video | `down` + `select` |
| VLM: SCREENSAVER | Wake + launch | `wakeup` + launch YouTube |
| Roku: screensaver overlay | Dismiss | `select` (wake from screensaver) |
| Roku: not on YouTube | Relaunch | `launch_app('youtube')` |

**Device-agnostic design:**
- `set_device_controller(controller, device_type)` accepts any controller
- Device type auto-detected from controller class name
- YouTube launch uses device-specific methods (Roku ECP `launch_app`, Android ADB intent)
- Skip command routes through active device controller

**Roku-specific features:**
- **Active app check** via ECP `/query/active-app` — definitively knows if YouTube is running
- **Screensaver detection** — checks for `<screensaver>` element in active-app response (Roku City screensaver overlays YouTube without closing it)
- **YouTube app ID**: 837

**OCR-based screen detection:**
VLM often misclassifies static YouTube screens (login, home) as "PLAYING". OCR keywords provide more reliable detection:

| Screen | Keywords | Action |
|--------|----------|--------|
| Login/account selection | `watch as guest`, `watchas guest`, `add a kid account`, `kid account`, `choose account`, `switch account` | `down` + `select` to choose account |
| Home/browse | `new to you`, `newtoyou`, `trending`, `subscriptions`, `library`, `views`, `year ago`, `month ago` | `down` + `select` to pick a video |

Login screen detection runs before VLM query. Home screen detection runs when VLM says "PLAYING" but frames are static.

**Frame-change verification (pause detection):**
- dHash (difference hash) compares two frames 3 seconds apart
- Hamming distance < 3 = truly static (paused or stuck)
- Audio flow check via ad_blocker's audio module (`0 <= last_buffer_age < 3s`) or ALSA `/proc/asound` status
- Note: `buffer_age = -1` means no audio ever received (not flowing), fixed to prevent false "audio flowing" detection
- Static frames + audio flowing = music stream (not paused) — prevents false play_pause
- Static frames + no audio = truly paused — sends play_pause after 2 consecutive checks

**VLM Screen Query Prompt:**
```
Look at this TV screen and classify it into exactly one category.
Answer with ONLY one of these words:
PLAYING, PAUSED, DIALOG, MENU, SCREENSAVER
```
This structured prompt returns in ~1.0s (vs 5-22s with descriptive prompts).

**Settings persistence:** `/home/radxa/.minus_autonomous_mode.json`
```json
{"enabled": true, "start_hour": 22, "end_hour": 6, "always_on": false}
```

**System settings:** `/home/radxa/.minus_system_settings.json`
```json
{"vlm_preload": true}
```
VLM preload loads the model at startup before HDMI signal arrives (configurable in Settings tab).

**API endpoints:**
- `GET /api/autonomous` - Current status (active, schedule, stats, device_type, device_connected)
- `POST /api/autonomous/enable` / `disable` / `toggle`
- `POST /api/autonomous/start` - Start immediately (manual override)
- `POST /api/autonomous/schedule` - Set hours and always_on flag
- `GET /api/autonomous/logs` - Recent log entries
- `GET/POST /api/settings/vlm-preload` - VLM preload toggle

**Web UI:** Toggle button, schedule time selectors, 24/7 checkbox (auto-enables mode), stats display in Settings tab, VLM preload toggle.

**24h stability test results (Apr 10-11, 2026):**
- Memory: stable at ~1.65GB RSS, no leak (tested 21+ hours continuous)
- FD count: stable at ~35, no leak
- Autonomous actions: 10+ DIALOG dismissals, 6+ screensaver auto-dismissals, all successful
- Ads blocked: 15+ ad breaks (OCR+VLM), all legitimate
- Audio-aware static detection: prevented 100+ false play_pause commands on lo-fi streams
- Audio restarts: 3 total (isolated, all self-recovered)
- Zero errors throughout

## WiFi Captive Portal

Minus includes a WiFi captive portal system for easy network configuration when no WiFi is connected.

**How it works:**
1. If WiFi disconnects for 30+ seconds, Minus creates a "Minus" hotspot AP
2. Users connect to the hotspot and get redirected to a setup page
3. Setup page shows available networks with signal strength
4. User selects network and enters password
5. Minus connects and stops the AP automatically

**Hotspot Configuration:**
- **SSID:** `Minus`
- **Password:** `minus123`
- **IP:** `10.42.0.1`
- **Band:** 2.4GHz (802.11 b/g)

**Captive Portal Detection:**
The portal supports automatic detection on mobile devices:
- `GET /generate_204` - Android captive portal check
- `GET /hotspot-detect.html` - Apple captive portal check
- `GET /connecttest.txt` - Windows captive portal check

**API Endpoints:**
- `GET /api/wifi/status` - Current connection status, AP mode state
- `GET /api/wifi/scan` - Scan for available networks
- `POST /api/wifi/connect` - Connect to a network (ssid, password)
- `POST /api/wifi/disconnect` - Disconnect from current network
- `POST /api/wifi/ap/start` - Start AP mode manually
- `POST /api/wifi/ap/stop` - Stop AP mode
- `GET /wifi-setup` - Captive portal setup page

**Settings Tab Integration:**
The Settings tab in the web UI shows:
- Current WiFi status (SSID, IP, signal strength)
- Disconnect button for current network
- Manual AP mode start/stop buttons

**Files:**
- `src/wifi_manager.py` - WiFi/AP management module
- `src/templates/wifi_setup.html` - Captive portal page
- `tests/test_wifi_portal.py` - Playwright tests (30 tests)

**Note:** The Radxa's internal WiFi antenna has limited range. For better AP coverage in production, consider using a USB WiFi adapter with external antenna.

## Streaming Device Configuration

Minus supports multiple streaming device types with device-specific remote control:

**Supported Devices:**
| Device | Protocol | Status |
|--------|----------|--------|
| Fire TV | ADB over WiFi | Full support |
| Roku | ECP (External Control Protocol) | Full support |
| Google TV / Android TV | ADB over WiFi | Full support |
| Apple TV | MRP/AirPlay | Coming soon |
| Generic | None | Ad blocking only |

**Web UI Setup:**
The Remote tab provides a device selector where users can:
1. Select their streaming device type
2. Follow device-specific setup instructions
3. Scan for devices on the network (Fire TV, Roku, Google TV)
4. Manually enter device IP address
5. Connect and control their device

**Device Configuration Persistence:**
- Configuration stored in `~/.minus_device_config.json`
- Persists device type, IP address, and setup state
- Survives service restarts

**API Endpoints:**
- `GET /api/device/config` - Get current configuration
- `GET /api/device/types` - List available device types
- `POST /api/device/select` - Select a device type
- `POST /api/device/ip` - Set device IP address
- `POST /api/device/setup-complete` - Mark setup complete
- `POST /api/device/reset` - Reset configuration

**Roku API Endpoints:**
- `GET /api/roku/status` - Connection status and device info
- `GET /api/roku/discover` - Scan network via SSDP multicast
- `POST /api/roku/connect` - Connect to Roku by IP
- `POST /api/roku/command` - Send remote command
- `POST /api/roku/launch/<app>` - Launch app (youtube, netflix, etc.)

**Roku Features:**
- Discovery via SSDP multicast
- ECP commands over HTTP to port 8060
- Control mode detection (Limited vs Full)
- Supports all navigation, media, and volume controls
- App launching: YouTube, Netflix, Prime, Disney+, Hulu, Plex, HBO, Peacock

**Fire TV API Endpoints:**
- `GET /api/firetv/status` - Connection status
- `GET /api/firetv/scan` - Scan network for Fire TV devices
- `POST /api/firetv/connect` - Connect to Fire TV by IP
- `POST /api/firetv/command` - Send remote command

**Google TV / Android TV API Endpoints:**
- `GET /api/googletv/status` - Connection status
- `GET /api/googletv/scan` - Scan network for devices (port 5555)
- `POST /api/googletv/connect` - Connect by IP:PORT (Wireless debugging uses dynamic port)
- `POST /api/googletv/command` - Send remote command (includes `assistant` for Google Assistant)

**Google TV Setup Notes:**
- Uses "Wireless debugging" (not USB debugging) for network ADB
- Settings > System > Developer options > Wireless debugging
- Shows IP:PORT on TV screen when enabled (e.g., 192.168.1.100:37421)
- Enter the full IP:PORT in web UI Remote tab
- First connection requires approving the ADB dialog on TV

## Fire TV Remote Control

Minus can control Fire TV devices over WiFi via ADB for ad skipping and playback control.

**Auto-setup:** Fire TV is automatically discovered and connected 5 seconds after Minus starts. First-time connection requires approving the ADB authorization dialog on the TV screen (OCR detects when it appears). ADB keys are saved for future connections.

**Features:**
- Auto-discovery of Fire TV devices on local network
- Verification that discovered device is actually a Fire TV
- ADB key generation and persistent storage for pairing
- Auto-reconnect on connection drops
- Full remote control: play, pause, select, back, d-pad, etc.
- Async-compatible interface

**Requirements:**
- Fire TV must have ADB debugging enabled
- First connection requires approving RSA key on TV screen
- Both devices must be on the same WiFi network

**Enabling ADB on Fire TV:** Settings > My Fire TV > Developer Options > ADB Debugging ON (enable Dev Options first via About > click device name 7x)

**Testing:** `python3 test_fire_tv.py [--setup|--interactive|--scan|IP]`

**Commands:** Navigation (up/down/left/right/select/back/home), Media (play/pause), Volume, Power

**Usage:** `quick_connect()` → `skip_ad()` / `go_back()` → `disconnect()`

**Setup States:** `idle` → `scanning` → `waiting_adb_enable` → `waiting_auth` → `connected`

## Google TV / Android TV Remote Control

Minus can control Google TV and Android TV devices over WiFi via ADB's Wireless debugging feature.

**Setup Flow:**
1. Select "Google TV / Android TV" in the Remote tab
2. On-screen overlay guides you through enabling Wireless debugging
3. Enter the IP:PORT shown on your TV's Wireless debugging screen
4. Approve the connection dialog on your TV

**Key Differences from Fire TV:**
- Uses "Wireless debugging" instead of "ADB debugging" (USB debugging)
- Dynamic port (not fixed 5555) - must enter IP:PORT format
- Found in Developer options after enabling developer mode

**Enabling Wireless Debugging:**
1. Settings > System > About > click Build number 7 times
2. Go back to System > Developer options
3. Turn ON "Wireless debugging"
4. Note the IP address and port shown on screen

**Commands:** Same as Fire TV plus `assistant` for Google Assistant button

**Setup States:** Same as Fire TV: `idle` → `scanning` → `waiting_adb_enable` → `waiting_auth` → `connected`

## Color Correction

Color correction is done via GStreamer's `videobalance` element in the pipeline.

**Why not ustreamer/V4L2?**
The HDMI-RX device doesn't support V4L2 image controls (saturation, contrast, brightness).
Only read-only controls are available: `audio_sampling_rate`, `audio_present`, `power_present`.

**Default settings (in `src/ad_blocker.py`):**
```
videobalance saturation=1.25 brightness=0.0 contrast=1.0 hue=0.0
```

**Web UI Controls:**
Color settings can be adjusted in real-time via the Settings tab in the web UI:
- **Saturation**: 0.5-1.5 slider (default 1.25, higher = more vivid)
- **Brightness**: -0.5 to 0.5 slider (default 0.0)
- **Contrast**: 0.5-1.5 slider (default 1.0)
- **Hue**: -0.5 to 0.5 slider (default 0.0)

**API Endpoints:**
```bash
# Get current color settings
curl http://localhost/api/video/color

# Set color settings (any combination)
curl -X POST -H "Content-Type: application/json" \
  -d '{"saturation": 1.3, "brightness": 0.1}' \
  http://localhost/api/video/color
```

**GStreamer ranges (for advanced use):**
- `saturation`: 0.0-2.0 (default 1.0)
- `contrast`: 0.0-2.0 (default 1.0)
- `brightness`: -1.0 to 1.0 (default 0.0)
- `hue`: -1.0 to 1.0 (default 0.0)

## Running as a Service

```bash
# Install
sudo ./install.sh

# View logs
journalctl -u minus -f

# Stop
sudo systemctl stop minus
./stop.sh  # Alternative with optional X11 restart

# Uninstall
sudo ./uninstall.sh
```

The service:
- Starts on boot (`multi-user.target`)
- Conflicts with display managers (gdm, lightdm, sddm)
- Restarts on crash (5 attempts per 5 minutes)
- Runs as root for DRM/device access

## Development Notes

### CRITICAL: Testing and Debugging Methodology

**Finding the Root Cause is ESSENTIAL:**
- Do NOT implement band-aid fixes that mask symptoms without understanding the cause
- Investigate WHY something is failing, not just WHAT is failing
- Example: If audio restarts constantly, don't just limit restart attempts - find out WHY it's restarting
- Use logs, `/proc` filesystem, API responses, and system state to trace the actual problem
- A fix that doesn't address root cause will likely cause other issues or recur

**Test Fixes BEFORE Pushing:**
- After implementing a fix, TEST it immediately by observing actual behavior
- Focus testing specifically on the ORIGINAL PROBLEM - verify the symptom is gone
- Do NOT push fixes without verification - iterate until the fix demonstrably works
- Run prolonged tests (30-60 seconds minimum) to catch intermittent issues
- Watch for the specific symptom that was reported (e.g., "frame jumps every 2-3 seconds")

**Testing Methodology:**
1. Understand the symptom clearly (what exactly is failing and how often)
2. Identify potential causes through log analysis and code review
3. Implement a fix targeting the root cause
4. Restart the service and observe behavior
5. Check logs for the specific error patterns that were occurring
6. Run a prolonged test (60 seconds) watching for the original symptom
7. Only commit/push after confirming the symptom is resolved

**Verification Techniques:**
- Check logs: `sudo journalctl -u minus --since "60 seconds ago" | grep -E "error|restart|fail"`
- Check FPS: `curl -s http://localhost/api/status | jq .fps`
- Check ALSA status: `cat /proc/asound/card*/pcm*/sub*/status`
- Check pipeline state: API responses, GStreamer state queries
- Record video samples for visual issues: `ffmpeg -i http://localhost:9090/stream -t 10 test.mp4`

**Common Pitfalls to Avoid:**
- Limiting retry attempts instead of fixing why retries are needed
- Assuming a fix works without observing the system under the original conditions
- Pushing multiple untested changes at once (makes debugging harder)
- Not checking if the "fix" introduced new problems

**Git commits:**
- Do NOT add "Co-Authored-By" lines to commits
- Do NOT add "Generated with Claude Code" lines to commits
- Keep commit messages clean and professional - just the message, no AI attribution

- Do NOT create v2, v3, v4 files - update existing files directly
- VLM uses Python axengine for inference (not pexpect/C++ binary)
- Both NPUs run in parallel without resource contention
- No X11 required - pure DRM/KMS display
- Color correction via GStreamer videobalance (not V4L2 controls)
- Health monitor runs every 5 seconds in background thread
- VLM frame files use PID-based naming to avoid permission conflicts
- Snapshots scaled to 960x540 before OCR (model uses 960x960 anyway, smaller = faster)
- ustreamer quality set to 80% for balance of quality and CPU load
- FPS tracked via GStreamer identity element with pad probe
- Startup cleanup removes stale frame files and kills orphaned processes
- Background upload is async to prevent blocking main thread
- Animation times optimized: 0.3s start, 0.25s end for fast response
- DYNAMIC_COOLDOWN reduced to 0.5s for faster ad detection

## Building Executable

```bash
pip3 install pyinstaller
pyinstaller minus.spec
# Output: dist/minus
```

Note: Models are external and must be present at runtime.

## Testing

The project includes a comprehensive test suite for all extracted modules.

**Running Tests:**
```bash
python3 tests/test_modules.py            # 300+ unit tests
python3 tests/test_autonomous_mode.py    # Autonomous mode tests
python3 tests/test_review_ui.py          # Playwright UI tests (requires chromium)
```

**Test Coverage:**

| Module | Test Class | Tests |
|--------|------------|-------|
| `src/vocabulary.py` | TestVocabulary | Format validation, content checks, common words |
| `src/config.py` | TestConfig | Dataclass defaults, custom values |
| `src/skip_detection.py` | TestSkipDetection | Pattern matching, countdown parsing, edge cases |
| `src/screenshots.py` | TestScreenshots | Deduplication, file saving, truncation |
| `src/console.py` | TestConsole | Console blanking/restore commands |
| `src/capture.py` | TestCapture | Snapshot capture, cleanup |
| `src/drm.py` | TestDRM | DRM probing, fallback values |
| `src/v4l2.py` | TestV4L2 | V4L2 format detection, error handling |
| `src/overlay.py` | TestOverlay | NotificationOverlay, positions, show/hide |
| `src/health.py` | TestHealth | HealthMonitor, HealthStatus, HDMI detection |
| `src/fire_tv.py` | TestFireTV | Controller, key codes, device detection |
| `src/vlm.py` | TestVLM | VLMManager, response parsing, 4-tuple returns |
| `src/ocr.py` | TestOCR | Keywords, exclusions, terminal detection |
| `src/webui.py` | TestWebUI, TestWebUIExtended | Flask routes, all API endpoints |
| `src/ad_blocker.py` | TestAdBlocker, TestAdBlockerExtended | Blocking modes, color controls, animations |
| `src/audio.py` | TestAudio, TestAudioExtended | A/V sync, pipeline controls, mute/unmute |
| `src/fire_tv.py` | TestFireTV, TestFireTVExtended | Connection, commands, device discovery |
| `src/vlm.py` | TestVLM, TestVLMExtended | Response parsing, confidence detection |
| `src/ocr.py` | TestOCR, TestOCRExtended | Keywords, exclusions, terminal detection |
| `src/skip_detection.py` | TestSkipDetection, TestSkipDetectionExtended | Pattern matching, countdown parsing |
| `src/screenshots.py` | TestScreenshots, TestScreenshotsExtended | Deduplication, categories, truncation |
| `src/config.py` | TestConfig, TestConfigValidation | Defaults, custom values |
| `src/health.py` | TestHealth, TestHealthExtended | Monitoring, callbacks, status |
| `src/overlay.py` | TestOverlay, TestOverlayExtended | Positions, show/hide, text formatting |
| `src/drm.py` | TestDRM, TestDRMExtended | DRM probing, fallback values |
| `src/v4l2.py` | TestV4L2, TestV4L2Extended | Format detection, error handling |
| `src/console.py` | TestConsole, TestConsoleExtended | Console blanking/restore |
| `src/capture.py` | TestCapture, TestCaptureExtended | Snapshot capture, cleanup |
| Integration | TestIntegration | Cross-module tests |
| Memory | TestMemoryLeaks | Resource cleanup, executor reuse |
| Blocking | TestBlockingModeIntegration | State transitions, API format |
| Error Handling | TestErrorHandling | Missing subsystems, graceful failures |
| Concurrency | TestConcurrency | Thread safety, locks |
| Vocabulary | TestVocabulary, TestVocabularyContent | Format, content, duplicates |
| API Responses | TestAPIResponseFormats | Consistent response structure |
| `src/vlm.py` | TestVLMQueryImage | Custom prompt queries, error paths |
| `src/ocr.py` | TestOCRResilience | NPU failure handling, graceful degradation |
| `src/screenshots.py` | TestScreenshotDedup | dHash, blank rejection, rate limiting, per-category |
| Memory | TestMemoryManagement | Hash buffer caps, resource cleanup |
| HDCP | TestHDCPHandling | Encrypted frame handling, blank frame rejection |
| `src/autonomous_mode.py` | TestAutonomousMode | Schedule, VLM actions, state, persistence (separate file) |
| Review UI | TestReviewModal* | Playwright: desktop/mobile swipe, modal, API (separate file) |

**Test Design:**
- Tests are self-contained with temporary directories
- Mock subprocess calls to avoid system dependencies
- Fallback to manual test runner if pytest not installed
- All 300+ tests should pass on a clean system
- Playwright tests require chromium: `python3 -m playwright install chromium`

## Module Structure

The codebase has been refactored from monolithic files into smaller, focused modules:

**Extracted from `minus.py`:**
- `src/console.py` - Console blanking functions (`blank_console`, `restore_console`)
- `src/drm.py` - DRM probing (`probe_drm_output`)
- `src/v4l2.py` - V4L2 probing (`probe_v4l2_device`)
- `src/config.py` - Configuration dataclass (`MinusConfig`)
- `src/capture.py` - Snapshot capture (`UstreamerCapture`)
- `src/screenshots.py` - Screenshot management (`ScreenshotManager`)
- `src/skip_detection.py` - Skip button detection (`check_skip_opportunity`)

**Extracted from `ad_blocker.py`:**
- `src/vocabulary.py` - Spanish vocabulary list (`SPANISH_VOCABULARY`)

**Benefits:**
- Easier to test individual components
- Better code organization and discoverability
- Reduced file sizes (minus.py ~1700 lines, ad_blocker.py ~950 lines)
- Clear separation of concerns

## Known Issues / Fixed

### GStreamer Video Path Overlay (Historical - FIXED)

**Previous problem:** Adding a `textoverlay` element to the GStreamer video path caused pipeline stalls every ~12 seconds due to NV12 format incompatibility and 4K→1080p resolution mismatch.

**Solution implemented:** Text overlay is now rendered directly in ustreamer's MPP encoder via the blocking mode API. This:
- Composites directly on NV12 frames in the encoder
- Has minimal CPU impact (~0.5ms per frame)
- Works at any resolution without GStreamer pipeline changes
- Supports pixelated background, live preview window, and text overlays
- Uses FreeType for proper TrueType font rendering

### Memory Management (Fixed)

**Issue:** Long-running sessions (several hours) could accumulate memory due to RKNN inference output buffers not being explicitly released.

**Solution implemented:**
- RKNN inference outputs are now explicitly copied and dereferenced in `src/ocr.py`
- Periodic `gc.collect()` runs every 100 OCR frames and every 50 VLM frames
- Health monitor triggers emergency cleanup at 90% memory usage
- Frame buffers (`prev_frame`, `vlm_prev_frame`) are cleared during memory critical events

**ThreadPoolExecutor fix (Jan 2026):**
- **CRITICAL:** The OCR worker was creating a new `ThreadPoolExecutor` on every iteration, causing massive file descriptor and memory leaks (~12GB after 12 hours)
- Fixed by creating a single `ocr_executor` before the loop and reusing it
- Symptom: "Too many open files" errors, display goes blank, memory exhaustion

**Memory monitoring:**
- Health monitor checks memory every 5 seconds
- Warning logged at 80% usage
- Critical cleanup triggered at 90% usage

### Fire TV Setup (Fixed)

**Status:** Fire TV auto-setup is ENABLED with notification overlays working via ustreamer API.

**Startup timing:**
- Fire TV setup starts 5 seconds after service start (runs in parallel with VLM loading)
- Total time from start to connection: ~13 seconds (5s delay + ~8s scan/connect)

**Bug fixed:** Auth retry interval was 3 seconds, causing multiple auth dialogs on the TV before user could respond. Fixed to 35 seconds (longer than AUTH_TIMEOUT of 30s) in `fire_tv_setup.py`.

### Audio Watchdog Restart Loop (Fixed - Apr 2026)

**Symptom:** Frame jumps every 2-3 seconds due to constant GStreamer audio pipeline restarts.

**Root Cause:** When HDMI signal was restored, `resume_watchdog()` tried to create a new audio pipeline without:
1. Checking if the existing pipeline was already working
2. Cleaning up the old pipeline first

This caused the new pipeline to fail with "device in use" because the old pipeline still held the ALSA device. The watchdog then repeatedly tried to restart every 3 seconds.

**Why band-aid fixes don't work:** Initially tried limiting restart attempts, but this just disabled audio after 5 restarts instead of fixing the underlying issue. The correct approach was to find WHY restarts were happening.

**Solution implemented:**
- Added `_is_alsa_device_running()` helper that checks `/proc/asound/cardX/pcmYp/sub0/status` to verify if ALSA device is actually running with our PID
- This is more reliable than GStreamer state queries when PipeWire/WirePlumber is involved
- Modified watchdog loop to skip restarts when ALSA confirms audio is flowing
- Modified `resume_watchdog()` to check if pipeline is already PLAYING before restart
- Added proper cleanup of old pipeline before creating new one

**Key insight:** The `/proc/asound` status showed the device was RUNNING with minus as owner, proving audio WAS working. GStreamer state queries were unreliable due to PipeWire interference, but the kernel-level ALSA status was authoritative.

### MPP Decoder Stuck After HDMI Signal Drop (Fixed - Apr 2026)

**Symptom:** After a brief HDMI signal loss (even 8 seconds), the video pipeline stalls every ~12 seconds with `mpp_buffer: check buffer found NULL pointer from mpp_dec_advanced_thread`. Restarting the GStreamer pipeline alone doesn't help - MPP stays stuck.

**Root Cause:** The RK3588 MPP JPEG decoder holds resources that don't get properly freed when the GStreamer pipeline is destroyed. After the HDMI source briefly drops and recovers, the decoder enters a corrupt state that persists across pipeline restarts.

**Solution implemented:**
- After 3+ consecutive pipeline failures, the system now kills ustreamer (`pkill -9 ustreamer`) to force-release MPP resources
- The health monitor detects ustreamer is down and restarts it + the video pipeline with clean MPP state
- This auto-recovers from stuck MPP decoder without manual service restart

### Audio Device Mismatch on Display Reconnect (Fixed - Apr 2026)

**Symptom:** No audio after TV wakes up from standby. Audio pipeline starts on wrong HDMI output (e.g., `hw:0,0` instead of `hw:1,0`).

**Root Cause:** When the display retry loop detects a DRM output change (TV connected to different HDMI port than at boot), it updated the config but not the audio object's playback device. Audio would start on the old device.

**Solution implemented:**
- Display retry loop now checks if `drm_info['audio_device'] != self.audio.playback_device`
- If changed, stops the audio pipeline and updates the playback device before restarting
- Ensures audio always matches the active HDMI output

### Netflix Ad Countdown Detection (Fixed - Apr 2026)

**Symptom:** Netflix ads showing "Ad 10", "Ad 5" (countdown timer format) were not detected by OCR.

**Root Cause:** Existing OCR patterns only matched "Ad X of Y" format. Netflix uses standalone "Ad NN" where NN is seconds remaining.

**Solution:** Added regex pattern `^ad\s*\d+$` to match the countdown format.

### Skip-to-Unblock Delay (Fixed - Apr 2026)

**Symptom:** After successfully skipping an ad, the blocking overlay stayed for 2-3+ seconds waiting for OCR to detect the ad was gone.

**Solution:** After a successful skip command (auto or manual via web UI), blocking is now removed after a 1.5s delay instead of waiting for 3 OCR cycles. The delay allows the skip animation to complete, then force-unblocks by resetting all detection state. Skip command is device-agnostic — routes to Fire TV (`skip_ad()`), Roku (`send_command('select')`), or Google TV based on the configured device type.

### GStreamer Bus Signal Watch FD Leak (Fixed - Apr 2026)

**Symptom:** After running for 12+ hours with no HDMI signal, the web server becomes unresponsive. Logs show `[Errno 24] Too many open files` errors. The service cannot open new files or sockets.

**Root Cause:** When the no-signal or loading GStreamer pipelines failed to start, the cleanup code did not remove the bus signal watch before destroying the pipeline. Each failed attempt leaked a file descriptor from `bus.add_signal_watch()`. With retries every 10 seconds, the 1024 FD limit was reached in ~3 hours.

**Solution:** Added proper bus cleanup in all pipeline failure paths:
```python
# Before destroying failed pipeline:
if self.bus:
    self.bus.remove_signal_watch()
    self.bus = None
```

Fixed in `src/ad_blocker.py`: `start_no_signal_mode()` and `start_loading_mode()` failure paths and exception handlers.

### Audio Pipeline Zombie State After Sleep/Wake (Fixed - Apr 2026)

**Symptom:** After TV/display sleeps for several hours and wakes up, there is no audio output even though the health monitor reports `audio=OK` and the ALSA device shows `state: RUNNING`.

**Root Cause:** The GStreamer audio pipeline runs in a separate thread. When the display sleeps, this thread can crash or die (e.g., due to ALSA device disconnection), but:
1. The Python `AudioPassthrough` object retains a stale reference to the dead pipeline
2. The ALSA device shows `owner_pid` pointing to the dead thread's PID
3. The health check only queries the Python GStreamer state, not the actual ALSA device ownership
4. Result: Health reports `audio=OK` while no actual audio is flowing

**Detection:** Check if the ALSA playback device's `owner_pid` corresponds to a live process:
```bash
# Get owner PID
cat /proc/asound/card1/pcm0p/sub0/status | grep owner_pid
# owner_pid   : 179247

# Check if process exists
ps -p 179247
# Returns empty = zombie audio state!
```

**Solution:** Enhanced `_check_audio_pipeline()` in `src/health.py` to:
1. Read the ALSA device status from `/proc/asound/cardX/pcm0p/sub0/status`
2. Verify the `owner_pid` corresponds to a live process (check `/proc/{pid}/` exists)
3. If owner is dead but device shows RUNNING, trigger full `_restart_pipeline()` (not just queue flush)
4. 10-second cooldown after any restart before zombie detection runs again (prevents restart loops)
5. Skip zombie detection if restart is already in progress
6. This runs every health check cycle (5 seconds), so recovery happens automatically

**Files modified:**
- `src/health.py` - Added `_check_alsa_zombie_state()` method with full restart and cooldown logic

### OCR Ad Timestamp Pattern Fix (Fixed - Apr 2026)

**Symptom:** Ad blocking would flicker on/off during ads because OCR sometimes reads "Ad 0:42" (with space) and sometimes "Ad0:42" (no space) or "Ado:55" (OCR misreads '0' as 'o').

**Root Cause:** The OCR pattern used word boundaries (`\bad\b`) which required a space between "Ad" and the timestamp. When OCR dropped the space, the pattern didn't match, counting as "no ad". After 3 "no ads", blocking ended, then immediately re-triggered when a frame with space was detected.

**Solution:** Updated `src/ocr.py` to match OCR variants:
- `ad[0o]:` pattern catches "Ad0:" and "Ado:" (no space, or 'o' misread)
- `[0-9o]:\d{2}` timestamp pattern handles 'o' misread as '0'
- Both per-element and cross-element checks updated

**Test cases now matched:**
- `Ad 0:42` - standard format ✓
- `Ad0:42` - no space ✓
- `Ado:55` - OCR misread '0' as 'o' ✓
- `0:30 | Ad` - Hulu style ✓

