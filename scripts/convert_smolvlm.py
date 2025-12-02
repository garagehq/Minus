#!/usr/bin/env python3
"""
SmolVLM-256M Conversion Script for RKNN/RKLLM
==============================================

Run this on an x86 Linux machine with:
- Python 3.8-3.12
- CUDA (optional, for faster export)

Expected speedup over InternVL3-1B:
- Vision encoder: 93M params vs ~400M -> ~4x faster encoding
- Visual tokens: 64 vs 256 -> ~4x fewer tokens to process
- Total potential: ~8-16x faster end-to-end

Usage:
    pip install torch transformers rknn-toolkit2 rkllm-toolkit
    python convert_smolvlm.py

Expected output files:
    - smolvlm_256m_vision_rk3588.rknn  (~180MB)
    - smolvlm_256m_llm_w8a8_rk3588.rkllm (~200MB)
"""

import os
import torch
import argparse
from pathlib import Path

# Configuration
MODEL_NAME = "HuggingFaceTB/SmolVLM-256M-Instruct"
TARGET_PLATFORM = "rk3588"
OUTPUT_DIR = "./output"
BATCH_SIZE = 1
IMAGE_HEIGHT = 512
IMAGE_WIDTH = 512

def export_vision_onnx():
    """Export SmolVLM vision encoder to ONNX"""
    print("\n[1/4] Loading SmolVLM-256M model...")
    from transformers import SmolVLMForConditionalGeneration

    model = SmolVLMForConditionalGeneration.from_pretrained(
        MODEL_NAME,
        torch_dtype=torch.float32,
        _attn_implementation="eager",
    )

    print("[2/4] Extracting vision encoder + connector...")

    class SmolVLMVision(torch.nn.Module):
        def __init__(self, vlm):
            super().__init__()
            self.vpm = vlm.model.vision_model
            self.connector = vlm.model.connector

        def forward(self, pixel_values):
            image_hidden_states = self.vpm(pixel_values).last_hidden_state
            image_hidden_states = self.connector(image_hidden_states)
            return image_hidden_states

    vision_model = SmolVLMVision(model)
    vision_model = vision_model.to(torch.float32).eval()

    # Create dummy input
    dummy_input = torch.randn(BATCH_SIZE, 3, IMAGE_HEIGHT, IMAGE_WIDTH, dtype=torch.float32)

    # Test forward pass
    with torch.no_grad():
        output = vision_model(dummy_input)
    print(f"    Vision encoder output shape: {output.shape}")
    print(f"    Visual tokens: {output.shape[1]} (vs 256 for InternVL3-1B)")

    # Export to ONNX
    onnx_path = f"{OUTPUT_DIR}/smolvlm_256m_vision.onnx"
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"[3/4] Exporting to ONNX: {onnx_path}")
    torch.onnx.export(
        vision_model,
        dummy_input,
        onnx_path,
        input_names=['pixel'],
        output_names=['image_features'],
        opset_version=15,
        dynamo=False  # Use legacy exporter for better compatibility
    )

    print(f"    ONNX exported: {onnx_path}")
    return onnx_path

def convert_vision_rknn(onnx_path):
    """Convert vision ONNX to RKNN"""
    print("\n[4/4] Converting vision encoder to RKNN...")

    try:
        from rknn.api import RKNN
    except ImportError:
        print("ERROR: rknn-toolkit2 not installed")
        print("Install with: pip install rknn-toolkit2")
        return None

    # SmolVLM uses SigLIP normalization
    mean_value = [[0.5 * 255, 0.5 * 255, 0.5 * 255]]
    std_value = [[0.5 * 255, 0.5 * 255, 0.5 * 255]]

    rknn = RKNN(verbose=False)
    rknn.config(target_platform=TARGET_PLATFORM, mean_values=mean_value, std_values=std_value)       

    print(f"    Loading ONNX: {onnx_path}")
    rknn.load_onnx(onnx_path)

    print("    Building RKNN model (FP16, no quantization)...")
    rknn.build(do_quantization=False, dataset=None)

    rknn_path = f"{OUTPUT_DIR}/smolvlm_256m_vision_fp16_{TARGET_PLATFORM}.rknn"
    rknn.export_rknn(rknn_path)

    print(f"    RKNN exported: {rknn_path}")
    return rknn_path

def convert_llm_rkllm():
    """Convert SmolVLM LLM component to RKLLM"""
    print("\n[LLM] Converting SmolLM2-135M to RKLLM...")

    try:
        from rkllm.api import RKLLM
    except ImportError:
        print("ERROR: rkllm-toolkit not installed")
        print("Install with: pip install rkllm-toolkit (x86 only)")
        return None

    # SmolVLM uses SmolLM2-135M as the LLM backbone
    # We need to export just the LLM part
    llm = RKLLM()

    # Load SmolLM2-135M (the LLM backbone)
    ret = llm.load_huggingface(model=MODEL_NAME, device="cpu")
    if ret != 0:
        print(f"Failed to load model: {ret}")
        return None

    # Build with W8A8 quantization for RK3588
    dataset = None  # Use default quantization
    ret = llm.build(
        do_quantization=True,
        optimization_level=1,
        quantized_dtype="w8a8",
        quantized_algorithm="normal",
        target_platform=TARGET_PLATFORM,
        num_npu_core=3,
        dataset=dataset
    )

    if ret != 0:
        print(f"Failed to build model: {ret}")
        return None

    rkllm_path = f"{OUTPUT_DIR}/smolvlm_256m_llm_w8a8_{TARGET_PLATFORM}.rkllm"
    ret = llm.export_rkllm(rkllm_path)

    if ret != 0:
        print(f"Failed to export model: {ret}")
        return None

    print(f"    RKLLM exported: {rkllm_path}")
    return rkllm_path

def main():
    print("=" * 60)
    print("SmolVLM-256M Conversion for RK3588 NPU")
    print("=" * 60)
    print(f"\nModel: {MODEL_NAME}")
    print(f"Target: {TARGET_PLATFORM}")
    print(f"Output: {OUTPUT_DIR}/")
    print()
    print("Expected improvements over InternVL3-1B:")
    print("  - Vision encoder: 93M vs ~400M params")
    print("  - Visual tokens: 64 vs 256")
    print("  - Encoding speed: ~4x faster")
    print("  - Inference speed: ~4x faster")
    print()

    # Export vision encoder
    onnx_path = export_vision_onnx()

    # Convert to RKNN
    rknn_path = convert_vision_rknn(onnx_path)

    # Convert LLM
    rkllm_path = convert_llm_rkllm()

    print("\n" + "=" * 60)
    print("CONVERSION COMPLETE")
    print("=" * 60)
    print("\nOutput files:")
    if rknn_path:
        print(f"  Vision: {rknn_path}")
    if rkllm_path:
        print(f"  LLM: {rkllm_path}")

    print("\nCopy these files to your RK3588 device and update your demo:")
    print("  ./ad_detector demo.jpg smolvlm_vision.rknn smolvlm_llm.rkllm 10 3")
    print()
    print("Expected tokens for SmolVLM:")
    print("  img_start: '<image>'")
    print("  img_end: '</image>'")
    print("  img_content: '<image_placeholder>'")

if __name__ == "__main__":
    main()