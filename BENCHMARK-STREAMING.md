# Stream Sentry - Streaming Benchmarks

This document tracks all streaming/display approaches tested for the HDMI passthrough + ML pipeline.

## Requirements

- **Display**: 4K@30fps smooth passthrough (minimum 20fps acceptable)
- **ML Capture**: ~1fps frame capture for OCR (doesn't need to be realtime)
- **Critical**: Frame capture must NOT block/stutter the display
- **Critical**: Frame capture must NOT include our ad-blocking overlay

## Hardware

- **Device**: Rock 5B+ (RK3588)
- **HDMI-RX**: /dev/video0 (V4L2 multiplanar, BGR3/NV12/NV16/NV24 formats)
- **Resolution**: 3840x2160 @ 30fps
- **NPU**: RKNN for PaddleOCR inference

---

## Approaches Tested

### 1. GStreamer tee + appsink

**Status**: ❌ FAILED - Display ~1fps

**Configuration tested**:
```bash
v4l2src device=/dev/video0 io-mode=2 do-timestamp=true !
video/x-raw,format=BGR,width=3840,height=2160,framerate=30/1 !
tee name=t
t. ! queue max-size-buffers=3 leaky=downstream ! glimagesink sync=false
t. ! queue max-size-buffers=1 leaky=downstream ! videoscale ! videoconvert ! appsink
```

**Issue**: Display branch ran at ~1fps despite trying:
- Different sinks: glimagesink, xvimagesink, autovideosink, ximagesink
- Different queue settings
- Different format negotiations

**Hypothesis**: CPU videoconvert at 4K (24MB/frame * 30fps = 720MB/s) is the bottleneck.
Even the display branch was affected, possibly due to pipeline synchronization.

**Note**: Research suggests this SHOULD work with proper hardware acceleration.
Missing: RGA-accelerated format conversion? Need to investigate rgaconvert plugin.

---

### 2. mpv + IPC Screenshot

**Status**: ❌ FAILED - Causes display stutter

**Configuration tested**:
```bash
mpv av://v4l2:/dev/video0 --vo=gpu --gpu-context=x11egl \
    --profile=low-latency --untimed --fs --input-ipc-server=/tmp/mpv-socket
```

**Display Quality**: ✅ Good (30fps with --vo=gpu --gpu-context=x11egl)

**Frame Capture**:
```python
# IPC command
{"command": ["screenshot-to-file", "/tmp/frame.jpg", "video"]}
```

**Issue**: Screenshot command takes ~700-1000ms and causes visible stutter in display.
Even with async flag, mpv's video pipeline appears to block during screenshot encoding.

**Attempted fixes**:
- Async IPC command (didn't help - encoding still blocks video thread)
- RAM disk /dev/shm (faster I/O, but encoding still blocks)
- JPEG instead of PNG (faster, but still ~700ms)

---

### 3. mpv + scrot (screen capture)

**Status**: ❌ FAILED - Captures overlay

**Display Quality**: ✅ Good (mpv runs smoothly)

**Frame Capture Speed**: ~230ms per capture

**Issue**: scrot captures the entire screen including our ad-blocking overlay.
Would require hiding overlay during capture, causing visible flicker (unacceptable).

This is what v1 did with "quick check" mechanism - hide overlay, capture, show overlay.
Results in 500ms+ of exposed screen during each check.

---

### 4. Raw OpenCV V4L2 Capture (without display)

**Status**: ⚠️ PARTIAL - Good capture, but no display

**Benchmark**:
```python
cap = cv2.VideoCapture('/dev/video0', cv2.CAP_V4L2)
# Captured 100 frames in 3.63s = 27.5 fps
```

**Issue**: V4L2 device only allows ONE reader at a time.
Cannot have both mpv and OpenCV reading from /dev/video0 simultaneously.

---

### 5. FFmpeg SDL2 Output

**Status**: ❌ NOT FULLY TESTED

**Notes**: FFmpeg with SDL2 output might work but requires proper format configuration.
Initial test failed due to format issues.

---

## WORKING SOLUTION

### ustreamer + ffplay + HTTP Snapshot

**Status**: ✅ WORKING - Smooth display + non-blocking 78ms snapshots

**Architecture**:
```
┌──────────────┐     ┌────────────────────┐     ┌─────────────┐
│   HDMI-RX    │────▶│     ustreamer      │────▶│  ffplay     │
│ /dev/video0  │     │ (MJPEG encoding)   │     │ (display)   │
│  4K@30fps    │     │                    │     │  30fps      │
│              │     │   :9090/stream     │     │             │
│              │     │   :9090/snapshot   │     └─────────────┘
│              │     │        │           │
└──────────────┘     └────────┼───────────┘
                              │
                              ▼ HTTP snapshot (~78ms)
                     ┌────────────────────┐
                     │    ML Worker       │
                     │  (curl → OpenCV)   │
                     │    PaddleOCR       │
                     └────────────────────┘
```

**Configuration**:
```bash
# Start ustreamer (captures from v4l2, serves HTTP stream)
ustreamer --device=/dev/video0 --format=BGR24 --port=9090

# Display stream with ffplay (fullscreen, low latency)
ffplay -fflags nobuffer -flags low_delay -framedrop \
    -f mjpeg http://localhost:9090/stream -fs

# Take snapshot for ML (non-blocking, ~78ms)
curl -s -o /tmp/frame.jpg http://localhost:9090/snapshot
```

**Benchmark Results**:
- Stream capture: 30fps
- JPEG encoding: ~130-135ms per frame (4 workers parallel)
- Snapshot during stream: ~78ms (non-blocking!)
- Display latency: Low (MJPEG decode + display)

**Key Benefits**:
1. Snapshots are from video buffer, NOT screen (won't capture overlay)
2. Snapshot is completely non-blocking (stream continues smoothly)
3. Display and ML are independent
4. 4K resolution works without issue

---

## Previously Tested (Failed)

---

### B. mjpg-streamer

**Reference**: https://github.com/jacksonliam/mjpg-streamer

**Concept**: Plugin-based MJPEG streamer with HTTP snapshot endpoint.

**Likely Issues**:
- Single-threaded encoding (4K bottleneck)
- HTTP snapshot may block stream

---

### C. GStreamer with RGA Acceleration

**Concept**: Use Rockchip RGA for hardware-accelerated format conversion.

**Investigate**:
- Is there an rgaconvert GStreamer plugin?
- Can we use NV12 format directly without CPU conversion?
- MPP (Media Processing Platform) integration

---

### D. Dual V4L2 subdevices

**Concept**: Some HDMI-RX chips support multiple V4L2 subdevices.

**Investigate**:
- Check if /dev/video0 supports multiple readers via subdev
- HDMI-RX chip documentation

---

## Performance Baselines

| Operation | Time | Notes |
|-----------|------|-------|
| scrot 4K capture | ~230ms | Fast, but captures overlay |
| mpv IPC screenshot (JPEG) | ~700-1000ms | Blocks display |
| mpv IPC screenshot (PNG) | ~1300ms | Blocks display |
| OpenCV V4L2 read | ~36ms/frame | Device exclusive |
| PaddleOCR inference | ~300-700ms | Depends on text density |

---

## Key Learnings

1. **V4L2 is exclusive**: Only one process can read from /dev/video0 at a time
2. **mpv GPU display works**: `--vo=gpu --gpu-context=x11egl` gives smooth 30fps
3. **Screenshot encoding blocks**: Any screenshot method that encodes in mpv's thread causes stutter
4. **Screen capture includes overlay**: Can't use scrot/import without flicker
5. **GStreamer CPU bottleneck**: videoconvert at 4K is too slow without hardware acceleration

---

## Ideal Solution Characteristics

1. **Split at source**: Capture device feeds both display and ML independently
2. **Hardware acceleration**: Display and encoding use GPU/RGA/VPU, not CPU
3. **Shared memory**: ML reads frames from buffer without blocking display
4. **Non-blocking**: Frame capture never waits for or blocks the display pipeline
