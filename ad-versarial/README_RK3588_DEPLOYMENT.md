# YOLOv3 Ad Detector - RK3588 Deployment Guide

This guide provides instructions for deploying the ad detection model on RK3588 NPU.

## Model Overview

| Property | Value |
|----------|-------|
| **Model** | YOLOv3 (page-based ad detector) |
| **Source** | [ad-versarial](https://github.com/ftramer/ad-versarial) - trained on web page screenshots |
| **Input** | 416x416x3 RGB image (0-255 values) |
| **Output** | 3 detection heads for bounding boxes |
| **File** | `yolov3_ad_detector_rk3588.rknn` (120 MB) |
| **Format** | FP16 (no quantization) |

## Files Included

```
models/
├── yolov3_ad_detector_rk3588.rknn   # Ready for RK3588 deployment (120 MB)
├── page_based_yolov3.onnx            # Intermediate ONNX format (235 MB)
├── page_based_yolov3.h5              # Original Keras model (236 MB)
└── page_based_yolov3.weights         # Original Darknet weights (236 MB)
```

## Model Architecture

This is a **YOLO-v3 object detector** with Darknet-53 backbone, trained to detect advertisement regions on web pages.

**Output format (3 detection heads):**
- Head 1: 13x13x18 (large ads)
- Head 2: 26x26x18 (medium ads)
- Head 3: 52x52x18 (small ads)

Each detection has 18 channels: `[x, y, w, h, confidence, class_prob] × 3 anchors`

Since there's only 1 class (ad), the 18 channels are: `(4 bbox + 1 conf + 1 class) × 3 = 18`

## Usage for Binary Classification

Although this is an object detector, you can use it for binary "ad present / no ad" classification:

```python
# Pseudocode
import numpy as np
from rknn.api import RKNN

# Load model
rknn = RKNN()
rknn.load_rknn('yolov3_ad_detector_rk3588.rknn')
rknn.init_runtime()

# Preprocess image (resize to 416x416, RGB, 0-255)
img = cv2.resize(frame, (416, 416))
img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

# Run inference
outputs = rknn.inference(inputs=[img])

# Parse YOLO outputs and apply NMS
# boxes = parse_yolo_output(outputs, conf_threshold=0.5, iou_threshold=0.4)

# Binary classification
if len(boxes) > 0:
    print("AD DETECTED")
else:
    print("NO AD")
```

## Post-Processing (NMS)

YOLO outputs need Non-Maximum Suppression. You can use:
- OpenCV's `cv2.dnn.NMSBoxes()`
- Custom implementation from rknn_model_zoo

Key parameters:
- `confidence_threshold`: 0.5 (adjust based on testing)
- `iou_threshold`: 0.4 (for NMS)

## Expected Performance

Based on YOLO-v3 benchmarks on RK3588 NPU:
- **Inference time**: ~30-50ms per frame
- **FPS**: ~20-30 FPS

## Important Caveats

### Training Data Mismatch

This model was trained on **web page screenshots** (news websites like Guardian, NYTimes, BBC). Your use case is **stream/video screenshots**.

**Potential issues:**
- Web ads look different from stream ads (video overlays, sponsor segments)
- The model may have high false positive/negative rate on stream content

**Recommendation:** Test on your 100-image benchmark dataset first before production use.

### What This Model Detects

The model was trained to detect:
- Banner ads on websites
- Sidebar advertisements
- Inline sponsored content
- Pop-up style ads

It may NOT detect:
- Sponsor segments in videos
- Product placements
- Text-only sponsor mentions
- Stream overlays (donation alerts, etc.)

## Testing Procedure

1. Transfer `yolov3_ad_detector_rk3588.rknn` to your RK3588 device
2. Run inference on your benchmark dataset (50 ads, 50 non-ads)
3. Calculate accuracy, precision, recall
4. Compare with your existing results:

| Model | Accuracy | Precision | Recall | Latency |
|-------|----------|-----------|--------|---------|
| InternVL3-1B | 87.0% | 100.0% | 74.0% | 6,713ms |
| SmolVLM-256M | 56.0% | 100.0% | 12.0% | 2,488ms |
| CLIP (Zero-Shot) | 43.0% | 42.9% | 42.0% | 165ms |
| **YOLOv3 Ad (this)** | ?% | ?% | ?% | ~30-50ms |

## Next Steps Based on Results

### If accuracy is good (>80%)
- Great! Use this model for production
- Consider quantizing to INT8 for even faster inference

### If accuracy is poor (<70%)
Options:
1. **Fine-tune on your data** - Use your 100 labeled images
2. **Try the ResNet classifier** - Contact authors (see below)
3. **Train a simple classifier on CLIP embeddings** - Fast and uses your existing CLIP RKNN models

---

# Additional Models to Investigate

## 1. ResNet Ad Classifier (Hussein et al.)

A binary classifier trained specifically to classify images as "ad" or "not ad".

**Paper:** [Automatic Understanding of Image and Video Advertisements](https://arxiv.org/abs/1707.03067) (CVPR 2017)

**Dataset:** 64,832 image ads + 3,477 video ads

**Model:** ResNet-based binary classifier (Keras `.h5` format)

**Status:** Model weights NOT publicly available - must request from authors

### How to Request

**Contact:** Adriana Kovashka
**Email:** kovashka@cs.pitt.edu
**Project Page:** https://people.cs.pitt.edu/~kovashka/ads/

**Suggested email template:**
```
Subject: Request for Pre-trained Ad Classifier Model Weights

Dear Dr. Kovashka,

I am working on an advertisement detection project for video stream monitoring
and found your CVPR 2017 paper "Automatic Understanding of Image and Video
Advertisements" highly relevant to my work.

I noticed that the ad-versarial project (https://github.com/ftramer/ad-versarial)
references a pre-trained ResNet model (keras_resnet.h5) from your research.
Would it be possible to obtain the model weights for research purposes?

I plan to convert the model for deployment on embedded hardware (Rockchip RK3588 NPU)
for real-time ad detection in video streams.

Thank you for your consideration.

Best regards,
[Your name]
```

---

## 2. Percival Model (Brave Browser) - CONVERTED AND READY

A lightweight neural network designed for in-browser ad detection.

**Paper:** [Percival: Making In-Browser Perceptual Ad Blocking Practical with Deep Learning](https://arxiv.org/abs/1905.07444) (USENIX ATC 2020)

**Architecture:** Modified SqueezeNet (454K parameters)

**Status:** CONVERTED - See `models/percival_ad_detector_rk3588.rknn` (1.2 MB)

**Accuracy:** 96.76% (on web ad detection task from paper)

**Input:** 224x224 RGB (0-255)

**Output:** 2-class softmax [non-ad, ad]

**See:** `README_PERCIVAL_RK3588.md` for detailed usage instructions

---

## 3. HuggingFace Models (Text-Based)

These are **text classifiers**, not image classifiers, but listed for completeness:

| Model | Type | Accuracy | URL |
|-------|------|----------|-----|
| bondarchukb/bert-ads-classification | BERT text | N/A | [Link](https://huggingface.co/bondarchukb/bert-ads-classification) |
| Joshnicholas/ad-classifier | DistilBERT text | 97.99% | [Link](https://huggingface.co/Joshnicholas/ad-classifier) |
| morenolq/spotify-podcast-advertising | BERT text | N/A | [Link](https://huggingface.co/morenolq/spotify-podcast-advertising-classification) |

**Note:** These classify **text**, not images. Not suitable for screenshot-based detection.

---

## 4. Datasets for Fine-Tuning

If you need to train/fine-tune your own model:

| Dataset | Size | Type | URL |
|---------|------|------|-----|
| PeterBrendan/AdImageNet | 9,003 samples | Ad creatives | [HuggingFace](https://huggingface.co/datasets/PeterBrendan/AdImageNet) |
| 0x7o/ad_detector | Unknown | Ad detection | [HuggingFace](https://huggingface.co/datasets/0x7o/ad_detector) |
| biglam/illustrated_ads | Unknown | Historic newspaper ads | [HuggingFace](https://huggingface.co/datasets/biglam/illustrated_ads) |
| Roboflow Banner Detection | 764 samples | Banner ads + YOLO model | [Roboflow](https://universe.roboflow.com/school-9uzxn/banner-detection-with-yolo) |

---

## Recommended Approach

Based on your benchmark results and available resources:

### Option A: Quick Test (Today)
1. Test YOLOv3 ad detector on your benchmark
2. If accuracy > 80%, use it

### Option B: Fine-tune CLIP (1-2 days)
1. Extract CLIP embeddings from your 100 labeled images
2. Train a simple classifier (logistic regression or small MLP)
3. Use CLIP vision encoder (165ms) + tiny classifier (~1ms)
4. Expected: Fast inference + better accuracy than zero-shot

### Option C: Request ResNet Model (1-2 weeks)
1. Email Dr. Kovashka for the ResNet ad classifier
2. Convert to ONNX → RKNN
3. Expected: Better accuracy since it's trained for ad classification

### Option D: Train Custom Model (1 week+)
1. Download AdImageNet dataset (9,003 images)
2. Fine-tune MobileNetV2 or EfficientNet
3. Convert to RKNN
4. Expected: Best accuracy but most effort

---

## Quick Reference

**Model file to transfer:**
```
models/yolov3_ad_detector_rk3588.rknn (120 MB)
```

**Input preprocessing:**
- Resize to 416x416
- RGB color order
- Values 0-255 (no normalization needed)

**Expected latency:** 30-50ms per frame

**Confidence threshold:** Start with 0.5, adjust based on results
