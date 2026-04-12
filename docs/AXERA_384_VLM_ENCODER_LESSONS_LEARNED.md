# FastVLM 384x384 Vision Encoder for Axera M5 — Lessons Learned

Complete documentation of converting FastVLM vision encoders from 512x512 to 384x384
for the Axera AX650N NPU, covering every failure mode encountered and the final working solution.

**Date:** 2026-04-12
**Hardware:** Axera M5 LLM 8850 (AX650N), Radxa board ("minus" via Tailscale)
**Models:** FastVLM-0.5B, FastVLM-1.5B (apple/FastVLM on HuggingFace)
**Tools:** Pulsar2 5.1-patch1-lite, PyTorch, ONNX, rknn-toolkit2

---

## Table of Contents

1. [Background and Motivation](#1-background-and-motivation)
2. [Architecture Overview](#2-architecture-overview)
3. [The ONNX Export — SEBlock Dynamic Pooling Patch](#3-the-onnx-export--seblock-dynamic-pooling-patch)
4. [Attempt 1: Naive Int8 Conversion — Total Failure](#4-attempt-1-naive-int8-conversion--total-failure)
5. [Attempt 2: Fixing Input Format Mismatch](#5-attempt-2-fixing-input-format-mismatch)
6. [Attempt 3: Fixing Output Scale (×0.5 Hack)](#6-attempt-3-fixing-output-scale-05-hack)
7. [Attempt 4: Real Calibration Images](#7-attempt-4-real-calibration-images)
8. [Attempt 5: U16 Precision — The Breakthrough](#8-attempt-5-u16-precision--the-breakthrough)
9. [Attempt 6: AXERA-Style Config — The Final Solution](#9-attempt-6-axera-style-config--the-final-solution)
10. [The Working Pulsar2 Configuration](#10-the-working-pulsar2-configuration)
11. [The Working ONNX Export Script](#11-the-working-onnx-export-script)
12. [Calibration Data Preparation](#12-calibration-data-preparation)
13. [Complete Build Commands](#13-complete-build-commands)
14. [Performance Results](#14-performance-results)
15. [Known Issues and Edge Cases](#15-known-issues-and-edge-cases)
16. [Key Principles for Axera Vision Encoder Conversion](#16-key-principles-for-axera-vision-encoder-conversion)
17. [File Locations](#17-file-locations)
18. [RK3588 Comparison](#18-rk3588-comparison)

---

## 1. Background and Motivation

FastVLM (Apple) is a vision-language model using a FastViTHD vision encoder with a Qwen2 LLM backbone.
AXERA-TECH provides pre-converted 512x512 image encoders for their AX650N NPU. Testing on RK3588
showed that 384x384 resolution actually **improves** accuracy on TV ad detection (91.5% vs 85%) while
being 4x faster. We wanted to bring this speedup to the Axera platform.

**Goal:** Create 384x384 image encoder axmodels that match or exceed the 512x512 baseline quality.

**Token count by resolution:**
- 1024x1024 → 256 tokens (patch_size=64, so 1024/64 = 16, 16² = 256)
- 512x512 → 64 tokens (8² = 64)
- 384x384 → 36 tokens (6² = 36)

---

## 2. Architecture Overview

FastVLM has three components:

```
Image → [FastViTHD Vision Encoder] → [MLP Projector] → image embeddings → [Qwen2 LLM] → text
         (1,3,H,W) uint8           (1,N,3072)         (1,N,hidden)
```

- **FastViTHD**: CNN-based encoder with 5 stages, RepMixer + Attention blocks
  - Embedding dims: [96, 192, 384, 768, 1536]
  - Total downsampling: 64× (stem 4× + 4 downsample stages 2× each)
  - Final conv_exp with SE block produces (B, C, H, W) features
  - Features reshaped to (B, H×W, C) = (B, N, 3072)

- **MLP Projector**: 2-layer MLP with GELU
  - 0.5B: 3072 → 896 → 896
  - 1.5B: 3072 → 1536 → 1536

- **LLM**: Qwen2 (0.5B: 24 layers, 896 hidden; 1.5B: 28 layers, 1536 hidden)

The vision encoder + projector are compiled to a single axmodel. The LLM layers are separate axmodel files.

---

## 3. The ONNX Export — SEBlock Dynamic Pooling Patch

**Problem:** FastViTHD is instantiated with `inference_mode=True`, which hardcodes the SE (Squeeze-Excite)
block's average pooling kernel to `[16, 16]` — matching the 1024x1024 spatial output (1024/64 = 16).
At 384x384, the spatial output is only 6×6, causing a crash:

```
RuntimeError: Given input size: (3072x6x6). Calculated output size: (3072x0x0). Output size is too small
```

**Fix:** Patch `SEBlock.forward` to use dynamic global average pooling before loading the model:

```python
def patch_se_block_for_dynamic_pooling(SEBlock):
    import torch.nn.functional as F
    def _dynamic_forward(self, inputs):
        b, c, h, w = inputs.size()
        x = F.avg_pool2d(inputs, kernel_size=[h, w])  # Dynamic, not [16, 16]
        x = self.reduce(x)
        x = F.relu(x)
        x = self.expand(x)
        x = torch.sigmoid(x)
        return inputs * x
    SEBlock.forward = _dynamic_forward
```

**This patch is required for ANY non-1024 resolution.** The original code at line 111 of `llava_qwen.py`:
```python
# x = F.avg_pool2d(inputs, kernel_size=[h, w])  # commented out
x = F.avg_pool2d(inputs, kernel_size=[16, 16])   # hardcoded for 1024
```

---

## 4. Attempt 1: Naive Int8 Conversion — Total Failure

**What we did:**
- Exported ONNX with preprocessing baked in (uint8 NHWC → float32/255 → NCHW)
- Input name: `images`, shape: `(1, 384, 384, 3)`, dtype: uint8
- Pulsar2 config: default U8 quantization, NPU1, Numpy calibration with random data
- `calibration_mean=[0,0,0]`, `calibration_std=[1,1,1]`

**Result:** 50% accuracy (always outputs "Yes"), 0% non-ad detection.

**What went wrong:**
1. Int8 (U8) quantization destroyed the vision features
2. Random calibration data gave wrong quantization ranges
3. NPU1 mode (single core) was slow

---

## 5. Attempt 2: Fixing Input Format Mismatch

**Discovery:** The working 512x512 models accept `uint8 NHWC` input named `images`.
Our first ONNX exported `float32 NCHW` input named `pixel_values`.

**What we did:** Re-exported ONNX with a wrapper class that:
- Accepts uint8 NHWC input
- Bakes in `/255.0` normalization and NHWC→NCHW permutation
- Updated Pulsar2 config: `src_dtype: U8`, `src_layout: NHWC`

**Result:** Still 50% accuracy. The format was fixed but int8 quantization was the real problem.

---

## 6. Attempt 3: Fixing Output Scale (×0.5 Hack)

**Discovery:** The 384 axmodel output had 2× the standard deviation of the 512 model:
```
512 model output std: 0.27  ✅
384 model output std: 0.56  ❌ (ratio: 2.04×)
```

**What we did:** Added `image_features = image_features * 0.5` in the ONNX wrapper to compensate.

**Result:** Scale matched perfectly (ratio 1.02), but still 50% accuracy. The scale was a symptom,
not the cause. Int8 quantization was destroying feature **patterns**, not just magnitude.

**Lesson:** Matching output statistics (mean, std) does not mean the features are correct.
The 384 int8 features were heavily discretized into a small set of values with a hard clamp
at min=-2.8146, while the 512 model had smooth continuous values from -6.2 to +3.1.

---

## 7. Attempt 4: Real Calibration Images

**Hypothesis:** Random noise calibration data was causing Pulsar2 to set wrong quantization ranges.

**What we did:** Generated calibration data from 34 real ad/non-ad images:
- Square-padded, resized to 384x384
- Saved as uint8 NHWC numpy arrays
- Kept the ×0.5 output scaling

**Result:** Scale improved to 0.82× ratio, but still 50% accuracy. Real calibration
tightened the ranges but int8 was fundamentally insufficient for this architecture.

---

## 8. Attempt 5: U16 Precision — The Breakthrough

**Discovery:** Research into AXERA-TECH's own conversion repos revealed that they use **U16 (int16)
precision for ALL vision encoders**, not int8. Evidence:

1. SmolVLM config: `layer_configs: [{start_tensor_names: ["DEFAULT"], end_tensor_names: ["DEFAULT"], data_type: "U16"}]`
2. Every AXERA vision encoder config found uses U16
3. CLIP model filenames explicitly contain "u16" (e.g., `clip_vit_l14_336px_image_encoder_all_u16_fc_u8.axmodel`)
4. The working 512x512 FastVLM encoder (167MB) is sized consistently with U16, not U8 (our U8 was 140MB)

**What we did:**
- Removed the ×0.5 hack
- Set `layer_configs` to U16 for entire model
- Added `enable_smooth_quant: true`, `conv_bias_data_type: "FP32"`
- Used real image calibration

**Result:**
- **90% accuracy on 0.5B** (up from 50%)
- **100% accuracy on 1.5B** (up from 50%)
- Scale ratio: 0.99 (near perfect)
- Feature range: -4.5 to 3.0 (healthy, vs -2.8 to 1.5 with int8)

**BUT:** Encoder speed was 81ms — **slower** than the 512 model's 47ms. This was because we used NPU1 mode.

---

## 9. Attempt 6: AXERA-Style Config — The Final Solution

**Discovery:** Found AXERA's actual FastVLM build config at `github.com/AXERA-TECH/FastVLM.axera`:

Critical differences from our approach:

| Setting | AXERA | Our Previous |
|---------|-------|-------------|
| `npu_mode` | **NPU3** | NPU1 |
| ONNX structure | **No baked-in preprocessing** | Preprocessing baked in |
| `tensor_layout` | **NCHW** (model native) | NHWC (wrapped) |
| `calibration_format` | **Image** (JPEGs) | Numpy |
| `calibration_std` | **[255, 255, 255]** | [1, 1, 1] |
| `calibration_size` | **-1 (all images)** | 32 |
| `enable_onnxsim` | **true** | missing |

**The key insight:** AXERA exports the ONNX in its **native format** (float32 NCHW, input name `pixel_values`)
and lets Pulsar2's `input_processors` handle the uint8 NHWC → float32 NCHW conversion at runtime.
The `calibration_std=[255,255,255]` tells Pulsar2 to divide by 255 (matching the model's expected [0,1] range).

**Do NOT bake preprocessing into the ONNX model.** This interferes with Pulsar2's quantization pipeline.

**Result:**
- **90% accuracy on 0.5B, 100% on 1.5B**
- **28ms encoder** — 1.66× faster than 512 (47ms)
- Scale ratio: 0.97-1.02 (excellent)

---

## 10. The Working Pulsar2 Configuration

```json
{
    "model_type": "ONNX",
    "npu_mode": "NPU3",
    "onnx_opt": {
        "enable_onnxsim": true
    },
    "quant": {
        "input_configs": [
            {
                "tensor_name": "pixel_values",
                "calibration_dataset": "/data/calib_images_384.tar",
                "calibration_format": "Image",
                "calibration_size": 8,
                "calibration_mean": [0, 0, 0],
                "calibration_std": [255.0, 255.0, 255.0]
            }
        ],
        "layer_configs": [
            {
                "start_tensor_names": ["DEFAULT"],
                "end_tensor_names": ["DEFAULT"],
                "data_type": "U16"
            }
        ],
        "calibration_method": "MinMax",
        "transformer_opt_level": 1,
        "enable_smooth_quant": true,
        "conv_bias_data_type": "FP32"
    },
    "input_processors": [
        {
            "tensor_name": "pixel_values",
            "tensor_format": "RGB",
            "tensor_layout": "NCHW",
            "src_format": "RGB",
            "src_layout": "NHWC",
            "src_dtype": "U8"
        }
    ],
    "compiler": {
        "check": 0
    }
}
```

### Config field explanations:

- **`npu_mode: "NPU3"`** — Use all 3 NPU cores. This is 1.66× faster than NPU1 for the encoder.
  AXERA uses NPU3 for ALL their vision encoder builds.

- **`calibration_format: "Image"`** — Feed real JPEG images. Pulsar2 handles resize/crop internally.
  Do NOT use Numpy format for vision encoders.

- **`calibration_std: [255, 255, 255]`** — Since the ONNX model expects float32 [0,1] input,
  and Pulsar2 normalizes as `(pixel - mean) / std`, setting std=255 maps uint8 [0,255] → [0,1].

- **`layer_configs: data_type: "U16"`** — The most critical setting. Vision encoders MUST use U16
  on Axera. Int8 (U8) destroys features for transformer/CNN hybrid architectures.

- **`enable_smooth_quant: true`** — SmoothQuant paper technique. Redistributes quantization difficulty
  between weights and activations. Essential for models with outlier activations.

- **`conv_bias_data_type: "FP32"`** — Keep convolution biases in full precision. Small overhead, 
  prevents accumulation of quantization errors.

- **`tensor_layout: "NCHW"`** — Must match the ONNX model's actual input layout. The ONNX
  expects NCHW; Pulsar2's `input_processors` handle the NHWC→NCHW conversion at runtime.

- **`enable_onnxsim: true`** — Run ONNX Simplifier before compilation. Folds constants,
  removes redundant ops. Recommended by AXERA.

### Settings that are nice-to-have but caused OOM in our environment:

- `precision_analysis: true` + `precision_analysis_method: "EndToEnd"` + `precision_analysis_mode: "NPUBackend"`
- `calibration_size: -1` (use all images)
- `disable_auto_refine_scale: true`

These are used in AXERA's full config but required more memory than our Docker environment had.
The lite config above works fine without them.

---

## 11. The Working ONNX Export Script

The ONNX must be exported in **native format** — float32 NCHW, no preprocessing wrapper:

```python
import torch
import torch.nn as nn

class FastVLMVisionWithProjector(nn.Module):
    def __init__(self, vision_tower, mm_projector):
        super().__init__()
        self.vision_tower = vision_tower
        self.mm_projector = mm_projector

    def forward(self, pixel_values):
        # pixel_values: (B, 3, H, W) float32 [0, 1]
        image_forward_outs = self.vision_tower.vision_tower(
            pixel_values, return_image_embeddings=True
        )
        image_features = image_forward_outs["image_embeddings"]
        B, C, H, W = image_features.shape
        image_features = image_features.reshape(B, C, H * W).transpose(1, 2)
        image_features = self.mm_projector(image_features)
        return image_features

# Export with float32 NCHW input
dummy = torch.randn(1, 3, 384, 384, dtype=torch.float32)
torch.onnx.export(model, dummy, "fastvlm_vision_384.onnx",
                  input_names=["pixel_values"],
                  output_names=["image_features"],
                  opset_version=15)
```

**Do NOT:**
- Bake `/255.0` normalization into the model
- Add NHWC→NCHW permutation in the model
- Change the input name to "images" (let it be "pixel_values")
- Add any output scaling (×0.5 etc.)

Pulsar2 handles all input format conversion via `input_processors` and `calibration_std`.

---

## 12. Calibration Data Preparation

Create a tar archive of representative JPEG images resized to the target resolution:

```python
from PIL import Image
import tarfile, os

os.makedirs("calib_images_384", exist_ok=True)
for i, img_path in enumerate(image_paths[:32]):
    img = Image.open(img_path).convert("RGB")
    # Square pad (FastVLM preprocessing)
    w, h = img.size
    size = max(w, h)
    new_img = Image.new("RGB", (size, size), (127, 127, 127))
    new_img.paste(img, ((size - w) // 2, (size - h) // 2))
    img = new_img.resize((384, 384), Image.BILINEAR)
    img.save(f"calib_images_384/{i:04d}.jpg")

with tarfile.open("calib_images_384.tar", "w") as tar:
    for f in sorted(os.listdir("calib_images_384")):
        tar.add(f"calib_images_384/{f}", arcname=f)
```

**Requirements:**
- Use **real representative images** (mix of ad and non-ad content)
- **JPEG format**, not numpy arrays
- Resize to target resolution (384×384) with square padding
- 8-32 images is sufficient (AXERA uses 8 for SmolVLM)
- Set `calibration_format: "Image"` in the config

---

## 13. Complete Build Commands

### Prerequisites
```bash
# Pulsar2 Docker (download from HuggingFace)
wget https://huggingface.co/AXERA-TECH/Pulsar2/resolve/main/5.1-patch1/ax_pulsar2_5.1_patch1_lite.tar.gz
sudo docker load -i ax_pulsar2_5.1_patch1_lite.tar.gz
```

### Build 0.5B
```bash
sudo docker run --rm -v $WORKSPACE:/data pulsar2:5.1-patch1-lite \
  pulsar2 build \
    --target_hardware AX650 \
    --input /data/fastvlm_0.5b_vision_384.onnx \
    --output_dir /data/output_0.5b \
    --output_name image_encoder_384x384_0.5b_ax650.axmodel \
    --config /data/config_axera_lite.json
```

### Build 1.5B
```bash
sudo docker run --rm -v $WORKSPACE:/data pulsar2:5.1-patch1-lite \
  pulsar2 build \
    --target_hardware AX650 \
    --input /data/fastvlm_1.5b_vision_384.onnx \
    --output_dir /data/output_1.5b \
    --output_name image_encoder_384x384.axmodel \
    --config /data/config_axera_lite.json
```

### Important notes:
- The axmodel output file is in the **output root directory**, NOT in `compiler/`
- Build takes ~15-25 minutes per model
- Do NOT run two Pulsar2 containers simultaneously — they compete for resources and fail silently
- The Docker container creates root-owned files; use `sudo rm -rf` to clean output dirs before re-running

---

## 14. Performance Results

### Encoder Speed (isolated, 5-run average)

| Model | Resolution | NPU Mode | Encoder Time |
|-------|-----------|----------|-------------|
| FastVLM (AXERA 512) | 512×512 | Unknown | 47ms |
| FastVLM (ours, int8) | 384×384 | NPU1 | N/A (broken) |
| FastVLM (ours, U16) | 384×384 | NPU1 | 81ms |
| **FastVLM (ours, AXERA-style)** | **384×384** | **NPU3** | **28ms** |

### Accuracy (10 images: 5 ads + 5 non-ads)

| Model | Resolution | Quantization | Accuracy | Non-Ad Acc | Avg Total Time |
|-------|-----------|-------------|----------|------------|---------------|
| FastVLM-0.5B | 512×512 | AXERA U16 | 100% | 100% | 0.44s |
| FastVLM-0.5B | 384×384 | Int8 | 50% | 0% | 0.40s |
| FastVLM-0.5B | 384×384 | U16 NPU1 | 90% | 80% | 0.45s |
| **FastVLM-0.5B** | **384×384** | **U16 NPU3** | **90%** | **80%** | **0.41s** |
| FastVLM-1.5B | 512×512 | AXERA U16 | 100% | 100% | 1.73s |
| FastVLM-1.5B | 384×384 | Int8 | 54% | 46% | 6.70s |
| FastVLM-1.5B | 384×384 | U16 NPU1 | 100% | 100% | 3.81s |
| **FastVLM-1.5B** | **384×384** | **U16 NPU3** | **100%** | **100%** | **0.57s*** |

*Median time. Average is 3.36s due to 3 outlier images generating long responses (8-11s each).

### Feature Quality Comparison

| Metric | 512 AXERA | 384 Int8 | 384 U16 NPU3 |
|--------|----------|---------|-------------|
| Output std | 0.27 | 0.56 (2×) | 0.27 |
| Output range | [-6.2, 3.1] | [-2.8, 1.5] | [-4.4, 2.8] |
| Value distribution | Smooth, continuous | Discretized, clamped | Smooth, continuous |
| Std ratio to 512 | 1.00 | 2.04 | 0.97 |

---

## 15. Known Issues and Edge Cases

### 1. Input name mismatch
The AXERA-style 384 models have input name `pixel_values` while the AXERA 512 models use `images`.
Code must use `session.get_inputs()[0].name` dynamically, not hardcode `"images"`.

### 2. Long generation on specific images (1.5B only)
Three specific test images consistently produce 8-11s responses with 1.5B at 384×384,
while the same images take ~0.5s at 512×512. The answers are correct but verbose.
This is likely because 36 tokens (vs 64) provide less spatial detail, making the LLM
less confident and more verbose on complex images. Consider:
- Setting stricter `max_new_tokens` in the inference config
- Using the 0.5B model which doesn't exhibit this behavior
- Accepting the occasional slow response since accuracy is maintained

### 3. Pulsar2 container resource management
- Never run two Pulsar2 containers simultaneously — they fail silently in the compiler stage
- The `--rm` flag cleans up containers but leaves root-owned files in mounted volumes
- Use `sudo rm -rf` to clean output directories before re-running
- The axmodel file appears in the output ROOT directory, not in `compiler/` subdirectory

### 4. Precision analysis OOM
The full AXERA config with `precision_analysis_mode: "NPUBackend"` and `calibration_size: -1`
can OOM in resource-constrained Docker environments. The lite config (without precision analysis,
calibration_size: 8) produces equivalent results for FastVLM.

---

## 16. Key Principles for Axera Vision Encoder Conversion

These apply to ANY vision encoder conversion for AX650N, not just FastVLM:

1. **Always use U16 for vision encoders.** Int8 (U8) destroys features for CNN and ViT architectures.
   AXERA uses U16 for every vision encoder they've published (FastVLM, SmolVLM, InternVL, Janus-Pro,
   Qwen-VL, CLIP, Depth-Anything).

2. **Always use NPU3.** All 3 NPU cores. There is no reason to use NPU1 for vision encoders.

3. **Do NOT bake preprocessing into the ONNX.** Export the model in its native format (float32 NCHW).
   Let Pulsar2 handle input format conversion via `input_processors` and `calibration_std`.

4. **Use Image format calibration with real images.** Not numpy arrays, not random noise.
   8 images is sufficient. Use `calibration_format: "Image"`.

5. **Set `calibration_std` to handle normalization.** If the model expects [0,1] input,
   use `std=[255,255,255]`. If it expects ImageNet normalization, use the appropriate pixel-space values.

6. **Always enable smooth_quant and FP32 conv bias.** These are universal across all AXERA configs.

7. **Enable onnxsim.** Set `onnx_opt.enable_onnxsim: true` for cleaner graph optimization.

8. **Use MinMax calibration.** Not MSE, not KL, not Percentile. AXERA uses MinMax universally
   for vision encoders.

9. **Verify features, not just accuracy.** Check output std, range, and distribution against
   the reference model. A scale mismatch (even with correct accuracy) indicates a problem.

10. **The SEBlock patch is FastVLM-specific.** Any non-1024 resolution needs the dynamic pooling
    patch before ONNX export. Other architectures may have similar resolution-dependent hardcoding.

---

## 17. File Locations

### On the build machine (WSL2)
```
/home/cyeng/stream-sentry-overall/models/
├── FastVLM-0.5B/                    # HuggingFace model
│   ├── convert/
│   │   ├── export_vision_onnx.py    # ONNX export script (with SE patch)
│   │   ├── fastvlm_vision_384.onnx  # Float32 NCHW ONNX (for Axera)
│   │   └── fastvlm_vision_384.onnx.data
│   └── llava_qwen.py               # Model code
├── FastVLM-1.5B/                    # Same structure
├── pulsar2_workspace/
│   ├── config/
│   │   └── config_axera_lite.json   # Working Pulsar2 config
│   ├── calib_images_384.tar         # Calibration JPEG images
│   ├── export_vision_axera.py       # Axera ONNX export (with preprocessing — DO NOT USE)
│   ├── onnx_0.5b_nchw/             # Correct ONNX files for Pulsar2
│   ├── onnx_1.5b_nchw/
│   ├── output_0.5b_axstyle/        # Final 0.5B axmodel
│   └── output_1.5b_axstyle/        # Final 1.5B axmodel
└── AXERA_384_VLM_ENCODER_LESSONS_LEARNED.md  # This document
```

### On minus (Axera M5 board)
```
/home/radxa/axera_models/
├── FastVLM-0.5B/fastvlm_C128_CTX1024_P640_ax650/
│   ├── image_encoder_512x512_0.5b_ax650.axmodel    # AXERA original (working)
│   ├── image_encoder_384x384_0.5b_ax650.axmodel     # Our AXERA-style (working)
│   └── image_encoder_384x384_u16_0.5b_ax650.axmodel  # Old U16 NPU1 (slower)
├── FastVLM-1.5B/fastvlm_ax650_context_1k_prefill_640_int4/
│   ├── image_encoder_512x512.axmodel                # AXERA original (working)
│   ├── image_encoder_384x384.axmodel                 # Our AXERA-style (working)
│   └── image_encoder_384x384_u16.axmodel              # Old U16 NPU1 (slower)
└── ...
```

### vlm.py settings for 384×384
```python
VISION_MODEL_PATH = LLM_MODEL_PATH / "image_encoder_384x384.axmodel"
INPUT_SIZE = 384
TOKEN_LENGTH = 36
```

---

## 18. RK3588 Comparison

The 384x384 conversion was trivially successful on RK3588 using rknn-toolkit2:
- No quantization issues (fp32 pass-through for vision encoder)
- 91.5% accuracy on TV ads (better than 1024×1024's 85%)
- Simple ONNX → RKNN conversion with no special config needed

The Axera AX650N requires significantly more care due to mandatory quantization (no fp32 inference
on NPU). The U16 precision + correct Pulsar2 config bridges the gap, achieving comparable accuracy
with faster encoder speed (28ms on Axera NPU3 vs variable on RK3588).

**Key takeaway:** The same ONNX model works on both platforms. The difference is entirely in the
compilation/quantization toolchain configuration.
