# Real3D - Real-time 2D to 3D Conversion for Minus

## Overview

Real3D adds XReal-style 2D-to-3D conversion to Minus, enabling real-time stereoscopic 3D output from any 2D HDMI source. This allows viewing regular TV content, streaming, or gaming with depth perception using 3D glasses.

**Key Achievement: 30+ FPS at 1080p output** using the Axera AX650/AX8850 NPU for depth estimation.

## Architecture

```
┌──────────────┐     ┌────────────────────┐     ┌─────────────────────┐
│   HDMI-RX    │────▶│     ustreamer      │────▶│    Real3D Module    │
│ /dev/video0  │     │ (MJPEG encoding)   │     │                     │
│  4K@30fps    │     │   :9090/snapshot   │     │ ┌─────────────────┐ │
└──────────────┘     └────────────────────┘     │ │ Depth Estimator │ │
                                                │ │ Axera AX650 NPU │ │
                                                │ │   ~40ms/frame   │ │
                                                │ └────────┬────────┘ │
                                                │          │          │
                                                │ ┌────────▼────────┐ │
                                                │ │ DIBR Synthesis  │ │
                                                │ │  ~20ms/frame    │ │
                                                │ └────────┬────────┘ │
                                                └──────────┼──────────┘
                                                           │
                                                  ┌────────▼────────┐
                                                  │  SBS 3D Output  │
                                                  │ GStreamer→kmssink│
                                                  │  1920x1080@30fps │
                                                  └─────────────────┘
```

## What Worked

### 1. Depth Anything V2 on Axera NPU

- **Model**: `depth_anything_v2_vits_ax650.axmodel` (28MB, w8a16 quantized)
- **Input**: 518x518 RGB image
- **Output**: 518x518 depth map (normalized 0-1)
- **Inference time**: ~37-45ms on AX650 NPU
- **Source**: Pre-compiled from [AXERA-TECH/Depth-Anything-V2](https://huggingface.co/AXERA-TECH/Depth-Anything-V2)

The Axera-optimized model runs efficiently on the M.2 NPU card, leaving the RK3588 CPU/GPU free for other tasks.

### 2. DIBR (Depth Image Based Rendering)

Implemented standard DIBR algorithm for synthesizing stereo views:
1. Convert depth map to disparity (pixel shift amount)
2. Warp original image to create left/right eye views
3. Combine into Side-by-Side (SBS) 3D format

Working resolution: 640x360 (for speed), upscaled to 1080p output.

### 3. Frame Skipping Optimization

**Key insight**: Depth doesn't change significantly between consecutive frames in video content.

| Skip Factor | FPS | Quality Impact |
|-------------|-----|----------------|
| 1 (every frame) | 13.3 | Full temporal accuracy |
| 2 (every 2nd) | 22.4 | Minimal artifacts |
| 3 (every 3rd) | 28.9 | Slight motion blur on fast scenes |
| 4 (every 4th) | **34.0** | Acceptable for most content |

**Result**: With `skip_depth=3-4`, we achieve **28-34 FPS** at 1080p.

### 4. Python + GStreamer Integration

- Frame capture via ustreamer `/snapshot` HTTP API
- Depth estimation via `axengine` Python bindings
- Display output via GStreamer `appsrc` → `kmssink`

## What Didn't Work / Challenges

### 1. Pure Pipeline Throughput

Initial non-optimized approach only achieved ~12-15 FPS:
- Depth estimation: ~50ms
- DIBR in Python: ~30ms
- Total: ~80ms/frame = 12.5 FPS

**Solution**: Frame skipping + lower DIBR resolution.

### 2. Fixed Model Input Size

The Depth Anything V2 model is compiled for fixed 518x518 input. Cannot reduce resolution to speed up inference.

**Workaround**: Accept the ~40ms depth time, optimize other stages.

### 3. No RK3588 NPU Depth Model

While RK3588 has a 6 TOPS NPU, there's no pre-compiled depth model available. The RKNN model zoo doesn't include Depth Anything.

**Potential future work**: Convert Depth Anything to RKNN format for parallel processing.

### 4. No Live HDMI Testing (Yet)

Due to no HDMI signal during development, testing was done with:
- Static images (confirmed depth + DIBR quality)
- Video files (confirmed pipeline works)
- Synthetic frames (confirmed FPS benchmarks)

Live HDMI testing requires signal to be connected.

## Performance Summary

### Benchmark Results (1920x1080 output)

| Metric | Value |
|--------|-------|
| **Throughput FPS** | **28-34 FPS** (with skip_depth=3-4) |
| Depth estimation | 40-45ms per execution |
| DIBR synthesis | 19-22ms per frame |
| End-to-end latency | 70-100ms |
| Memory usage | ~500MB (model + buffers) |
| CPU usage | ~20-30% (single thread) |
| NPU usage | ~90% during depth inference |

### Quality vs Performance Tradeoffs

| Setting | FPS | 3D Quality | Best For |
|---------|-----|------------|----------|
| `skip_depth=1` | 13 | Best | Static content |
| `skip_depth=2` | 22 | Good | Normal video |
| `skip_depth=3` | 29 | Acceptable | Most content |
| `skip_depth=4` | 34 | OK | Fast action |

## File Locations

```
/home/radxa/Minus/
├── src/
│   └── real3d.py                    # Main Real3D module

/home/radxa/axera_models/Depth-Anything-V2/
├── depth_anything_v2_vits_ax650.axmodel  # Depth model (28MB)
├── stereo3d.py                      # Initial implementation
├── stereo3d_fast.py                 # Optimized single-threaded
├── real3d_service.py                # Pipelined service
├── benchmark_pipeline.py            # Pipeline benchmark
├── benchmark_optimized.py           # Frame-skipping benchmark
├── test_video_pipeline.py           # Video file test
├── examples/                        # Test images
└── output_sbs_panda.mp4             # Test output video
```

## Usage

### Standalone Testing

```bash
# Test with static image
cd /home/radxa/axera_models/Depth-Anything-V2
python3 stereo3d.py --image examples/demo01.jpg --output sbs_test.png

# Benchmark at 1080p
python3 benchmark_optimized.py --frames 200

# Test video conversion
python3 test_video_pipeline.py --input /path/to/video.mp4 --output sbs_video.mp4
```

### Integration with Minus

```python
from real3d import Real3DMode, Real3DConfig

# Configure
config = Real3DConfig(
    connector_id=215,      # HDMI output
    plane_id=72,           # DRM plane
    ustreamer_port=9090,
    output_width=1920,
    output_height=1080,
    skip_depth=3,          # For ~29 FPS
    strength=1.0           # 3D effect strength
)

# Start
real3d = Real3DMode(config)
real3d.start()

# Adjust on the fly
real3d.set_strength(1.5)   # More 3D pop
real3d.set_skip_depth(4)   # Faster

# Stop
real3d.stop()
```

## Future Improvements

### Short Term
1. **Live HDMI testing** - Validate with actual HDMI signal
2. **Toggle integration** - Add mode switch in Minus GUI
3. **Temporal filtering** - Smooth depth between skip frames

### Medium Term
1. **RKNN depth model** - Run depth on RK3588 NPU for parallel processing
2. **C implementation** - Move DIBR to C for lower overhead
3. **RGA acceleration** - Use RK3588 2D accelerator for image warping

### Long Term
1. **Video Depth Anything** - Use temporally-consistent depth model
2. **MV-HEVC output** - Native 3D video encoding
3. **Eye tracking** - Adjust disparity based on viewing distance

## Dependencies

```bash
# Python packages
pip3 install --break-system-packages axengine opencv-python numpy

# The axengine package requires AXCL runtime
# Installed via Axera SDK

# GStreamer (already installed for Minus)
# sudo apt install gstreamer1.0-tools gstreamer1.0-plugins-base
```

## Troubleshooting

### "axengine not available"
Ensure the Axera AXCL runtime is installed and the M.2 NPU card is detected:
```bash
/usr/bin/axcl/axcl-smi
```

### "Depth model not found"
Download from HuggingFace:
```python
from huggingface_hub import hf_hub_download
hf_hub_download(
    repo_id='AXERA-TECH/Depth-Anything-V2',
    filename='depth_anything_v2_vits_ax650.axmodel',
    local_dir='/home/radxa/axera_models/Depth-Anything-V2'
)
```

### Low FPS
- Increase `skip_depth` (e.g., 3 → 4)
- Ensure no other processes using Axera NPU
- Check thermal throttling: `axcl-smi` shows temperature

### Visual Artifacts
- Reduce `strength` parameter
- Enable temporal filtering (future feature)
- Check if source content has fast motion

## References

- [Depth Anything V2](https://depth-anything-v2.github.io/)
- [AXERA-TECH Models](https://huggingface.co/AXERA-TECH)
- [DIBR Overview](https://en.wikipedia.org/wiki/Depth_image-based_rendering)
- [XReal Real 3D](https://www.xreal.com/) (inspiration)
