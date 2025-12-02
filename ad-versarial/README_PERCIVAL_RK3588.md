# Percival Ad Detector - RK3588 Deployment Guide

This guide provides instructions for deploying the Percival ad detection model on RK3588 NPU.

## Model Overview

| Property | Value |
|----------|-------|
| **Model** | Percival (Modified SqueezeNet) |
| **Source** | [dxaen/percival](https://github.com/dxaen/percival) - Brave Browser ad blocker |
| **Paper** | [Percival: Making In-Browser Perceptual Ad Blocking Practical with Deep Learning](https://arxiv.org/abs/1905.07444) (USENIX ATC 2020) |
| **Input** | 224x224x3 RGB image (0-255 values) |
| **Output** | 2 classes: [non-ad probability, ad probability] |
| **File** | `percival_ad_detector_rk3588.rknn` (1.2 MB) |
| **Format** | FP16 (no quantization) |

## Files Included

```
models/
├── percival_ad_detector_rk3588.rknn    # Ready for RK3588 deployment (1.2 MB)
├── percival_ad_detector.onnx           # Intermediate ONNX format (1.75 MB)

percival_model/
├── Sq2.json                            # Original Frugally Deep model (3.2 MB)
├── percival.pth                        # PyTorch weights (1.8 MB)
```

## Model Architecture

Percival is a **modified SqueezeNet** binary classifier trained to detect advertisements.

**Architecture:**
- Input: 224×224×3 RGB
- Initial Conv (64 filters, 3×3, stride 2) → ReLU → MaxPool
- 6 Fire Modules (squeeze-expand pattern):
  - Fire3-4: squeeze=16, expand=64
  - Fire6-7: squeeze=32, expand=128
  - Fire9-10: squeeze=48-64, expand=256
- MaxPool after Fire4 and Fire7
- Dropout (0.5) → Conv (2 classes) → ReLU → AvgPool → Softmax

**Total Parameters:** 454,354 (~1.7 MB)

## Performance

From the original paper:
- **Accuracy:** 96.76% (replicating EasyList rules on web ads)
- **Expected Inference:** ~5-15ms on RK3588 NPU (estimated based on model size)

## Usage

### Python with RKNN Runtime

```python
import cv2
import numpy as np
from rknnlite.api import RKNNLite

# Load model
rknn = RKNNLite()
rknn.load_rknn('models/percival_ad_detector_rk3588.rknn')
rknn.init_runtime()

# Preprocess image
img = cv2.imread('screenshot.jpg')
img = cv2.resize(img, (224, 224))
img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
img = np.expand_dims(img, axis=0).astype(np.float32)

# Run inference
outputs = rknn.inference(inputs=[img])

# Parse output - [non-ad_prob, ad_prob]
probs = outputs[0][0]
is_ad = probs[1] > probs[0]  # or probs[1] > 0.5

if is_ad:
    print(f"AD DETECTED (confidence: {probs[1]:.2%})")
else:
    print(f"NO AD (confidence: {probs[0]:.2%})")

rknn.release()
```

### Input Preprocessing

```python
# Simple preprocessing - no normalization needed
def preprocess(image_path):
    img = cv2.imread(image_path)
    img = cv2.resize(img, (224, 224))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return np.expand_dims(img, axis=0).astype(np.float32)
```

### Output Interpretation

The model outputs softmax probabilities for 2 classes:
- `output[0]`: probability of NOT being an ad
- `output[1]`: probability of being an ad

For binary classification:
```python
ad_probability = outputs[0][0][1]
is_ad = ad_probability > 0.5  # Adjust threshold as needed
```

## Important Caveats

### Training Data

Percival was trained on **web page screenshots** (banner ads, sidebar ads, popup ads).

**Potential issues for stream content:**
- May not detect video-embedded ads (sponsor segments)
- May not recognize stream overlays (donation alerts, etc.)
- Optimized for static image ads, not video-style ads

**Recommendation:** Test on your benchmark dataset first.

### What This Model Detects

Trained to detect:
- Banner advertisements on web pages
- Sidebar ad units
- Inline sponsored content
- Popup-style ads
- Image-based advertisements

May NOT detect:
- Video sponsor segments
- Text-only sponsorship mentions
- Product placements
- Animated GIF ads (depends on frame timing)

## Comparison with Other Models

| Model | Size | Input | Accuracy | Latency (est) | Notes |
|-------|------|-------|----------|---------------|-------|
| **Percival** | 1.2 MB | 224×224 | 96.76%* | ~5-15ms | Binary classifier |
| YOLOv3 Ad | 120 MB | 416×416 | ?% | ~30-50ms | Object detector |
| InternVL3-1B | ~800 MB | VLM | 87% | 6,713ms | VLM (your data) |
| CLIP Zero-Shot | ~600 MB | 224×224 | 43% | 165ms | Zero-shot (your data) |

*96.76% is on web ad replication task, not your benchmark data

## Testing Procedure

1. Transfer `percival_ad_detector_rk3588.rknn` to your RK3588 device
2. Run inference on your benchmark dataset (50 ads, 50 non-ads)
3. Calculate accuracy, precision, recall
4. Compare latency with other models

### Expected Results Format

```
Percival Results:
- Accuracy: ?%
- Precision: ?%
- Recall: ?%
- Latency: ?ms per image
```

## Troubleshooting

### Model loads but outputs garbage
- Check input is RGB, not BGR
- Ensure input is 224×224
- Verify input values are 0-255, not normalized

### Very slow inference
- Ensure using RKNNLite runtime on device, not RKNN simulation
- Check NPU driver version: `cat /sys/kernel/debug/rknpu/version` (need 0.9.7+)

### RKNPU driver error
- Percival should work on older drivers since it's a simple CNN
- If issues, check Armbian/kernel version

## GitHub Repository

**Original Source:** https://github.com/dxaen/percival

**Model Files Location:**
- Frugally Deep JSON: https://github.com/dxaen/percival/tree/master/models/json
- PyTorch weights: https://github.com/dxaen/percival/tree/master/models/pytorch

## Paper Citation

```bibtex
@inproceedings{percival2020,
  title={Percival: Making In-Browser Perceptual Ad Blocking Practical with Deep Learning},
  author={Din, Zain ul Abi and Tigas, Panagiotis and King, Samuel T. and Livshits, Benjamin},
  booktitle={USENIX Annual Technical Conference (ATC)},
  year={2020}
}
```

## Quick Reference

**Model file to transfer:**
```
models/percival_ad_detector_rk3588.rknn (1.2 MB)
```

**Input preprocessing:**
- Resize to 224x224
- RGB color order
- Values 0-255 (no normalization needed)

**Output:**
- Shape: (1, 2)
- Index 0: non-ad probability
- Index 1: ad probability

**Expected latency:** ~5-15ms per frame (estimate for RK3588)
