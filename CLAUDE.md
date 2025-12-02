# Youyeetoo R1 (Rockchip) - System Configuration Notes

This document describes the workarounds required for the Youyeetoo R1 board running Debian Bullseye with a limited Rockchip kernel (5.10.110).

## Kernel Limitations

The vendor-provided kernel lacks several standard Linux networking features:

- **No iptables/netfilter support** - Modules `ip_tables`, `iptable_filter`, `iptable_nat`, `ip6_tables` are not compiled into the kernel or available as modules
- **No TUN device support** - Module `tun` is not available
- **No bridge networking support** - Cannot create virtual bridge interfaces
- **No nftables support** - The nft backend fails with "Protocol not supported"

These limitations affect Tailscale, Docker, and any other software that relies on Linux networking features.

## APT Repository Fixes

### bullseye-backports (Removed)

Debian Bullseye backports repository has been discontinued and returns 404 errors. The fix is to comment out or remove any `bullseye-backports` entries from:
- `/etc/apt/sources.list`
- `/etc/apt/sources.list.d/*.list`

### Held Packages

The vendor image has nearly all packages marked as "held" to prevent updates from breaking custom Rockchip packages. To install certain software (like ffmpeg), you may need to unhold specific packages:

```bash
sudo apt-mark unhold <package-name>
```

## Tailscale Configuration

Tailscale requires userspace networking mode since the kernel lacks TUN and iptables support.

### Configuration

Create systemd override at `/etc/systemd/system/tailscaled.service.d/override.conf`:

```ini
[Service]
ExecStart=
ExecStart=/usr/sbin/tailscaled --state=/var/lib/tailscale/tailscaled.state --socket=/run/tailscale/tailscaled.sock --tun=userspace-networking
```

Then reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart tailscaled
```

### Limitations

- Userspace networking is slower than kernel mode
- Works for basic connectivity but may have issues with some advanced features

## Docker Configuration

Docker requires special configuration to work without iptables and bridge support.

### Configuration

Create `/etc/docker/daemon.json`:

```json
{
  "iptables": false,
  "ip6tables": false,
  "bridge": "none"
}
```

### Usage Limitations

**All containers MUST use host networking:**

```bash
docker run --network host <image>
```

Or in docker-compose.yml:
```yaml
services:
  myservice:
    network_mode: host
```

### What This Means

- Containers share the host's network stack directly
- No network isolation between containers
- No port mapping (`-p` flag) - containers bind directly to host ports
- No container-to-container DNS resolution via Docker
- Containers can communicate via localhost

## ffmpeg Installation

Due to held package conflicts with vendor libav* packages, the safest approach is to install a static ffmpeg binary:

```bash
cd /tmp
wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz
tar xf ffmpeg-release-arm64-static.tar.xz
sudo cp ffmpeg-*-arm64-static/ffmpeg /usr/local/bin/
sudo cp ffmpeg-*-arm64-static/ffprobe /usr/local/bin/
```

## Camera Screenshot (HDMI Input)

To capture a single frame from the HDMI input:

```bash
# Using GStreamer (write to writable directory)
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 ! \
  video/x-raw,format=NV12,width=1920,height=1080 ! \
  videoconvert ! jpegenc ! filesink location=/tmp/screenshot.jpg

# Using ffmpeg
ffmpeg -f v4l2 -i /dev/video0 -frames:v 1 /tmp/screenshot.jpg
```

## RKLLM / NPU LLM Inference

The Youyeetoo R1 has an RK3588 with NPU, but running RKLLM requires a newer RKNPU driver than what's included in the vendor image.

### Current Status (Vendor Debian Image)

- **Vendor kernel**: 5.10.110
- **Vendor RKNPU driver**: v0.8.2 (check with `sudo cat /sys/kernel/debug/rknpu/version`)
- **Required RKNPU driver**: v0.9.7+ (v0.9.8 recommended)
- **Result**: Models load but inference fails with `matmul(w8a8) run failed`

### What We Learned

1. **RKLLM v1.2.2** loads and initializes successfully on driver v0.8.2
2. Vision encoder (RKNN) loads successfully
3. LLM model loads successfully
4. **Actual inference fails** - the W8A8 quantized matmul operations require newer driver

### Error Output

```
W rkllm: Warning: Your rknpu driver version is too low, please upgrade to 0.9.7
I rkllm: rkllm-runtime version: 1.2.2, rknpu driver version: 0.8.2, platform: RK3588
...
E rkllm: matmul(w8a8) run failed
```

### Why Patching the Vendor SDK Failed

We attempted to patch the RKNPU driver v0.9.8 into the Youyeetoo vendor SDK (kernel 5.10), but it **does not compile** because:

1. **`MONITOR_TYPE_DEV`** - renamed to `MONITOR_TPYE_DEV` in 5.10
2. **`rockchip_opp_set_low_length`** - function doesn't exist in 5.10
3. **`vm_flags_set/clear`** - kernel 6.x APIs, not available in 5.10

**Conclusion**: RKNPU driver v0.9.8 requires **kernel 6.1+**, it cannot be backported to 5.10.

### SDK Compilation Notes (Ubuntu 24.04 WSL)

If attempting to compile the Youyeetoo SDK in WSL:

1. **Python 2 required** - U-Boot build needs python2, but Ubuntu 24.04 removed it
   - Use `scripts/install-python2.sh` to install from Ubuntu 22.04 packages
2. **Python symlink** - Need `python-is-python3` package for repo tool
3. **libnsl2 dependency** - Required for python2.7 packages
4. **SDK uses `repo sync`** - Android-style multi-repo management

### The Solution: Armbian with Kernel 6.1

**Armbian officially supports Youyeetoo R1** with kernel 6.1:

**Download pre-built images**: https://www.armbian.com/youyeetoo-r1/
- Armbian Bookworm (Minimal/IOT) - kernel 6.1
- Armbian Noble (Desktop Gnome) - kernel 6.1

**Or build your own**:
```bash
git clone https://github.com/OpenSource-YYT/build
cd build
./compile.sh
# Select youyeetoo-r1 and kernel 6.1
```

**After flashing Armbian, verify**:
```bash
uname -r                                    # Should show 6.1.x
sudo cat /sys/kernel/debug/rknpu/version   # Should show >= 0.9.7
```

### Available Models (as of Nov 2025)

From `https://console.box.lenovo.com/l/l0tXb8` (fetch code: `rkllm`):
- `internvl3-1b_w8a8_rk3588.rkllm` (761 MB) - LLM component
- `internvl3-1b_vision_fp16_rk3588.rknn` (619 MB) - Vision encoder

### RKLLM Setup (After Armbian Install)

Once on Armbian with kernel 6.1 and RKNPU driver 0.9.7+:

```bash
# Clone rknn-llm repo
git clone https://github.com/airockchip/rknn-llm.git ~/rknn-llm

# Build multimodal demo
cd ~/rknn-llm/examples/multimodal_model_demo/deploy
cat > build-native.sh << 'EOF'
#!/bin/bash
set -e
rm -rf build
mkdir build && cd build
cmake .. -DCMAKE_CXX_COMPILER=g++ -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Release
make -j4
make install
EOF
chmod +x build-native.sh
./build-native.sh

# Download models and run
cd install/demo_Linux_aarch64
export LD_LIBRARY_PATH=./lib:$LD_LIBRARY_PATH
./demo demo.jpg models/vision.rknn models/llm.rkllm 2048 4096 3 "<|vision_start|>" "<|vision_end|>" "<|image_pad|>"
```

### Resources

- **Armbian R1 Downloads**: https://www.armbian.com/youyeetoo-r1/
- **OpenSource-YYT Build**: https://github.com/OpenSource-YYT/build
- **rknn-llm Repo**: https://github.com/airockchip/rknn-llm
- **Model Zoo**: https://console.box.lenovo.com/l/l0tXb8 (code: `rkllm`)
- **Radxa RKLLM Guide**: https://docs.radxa.com/en/rock5/rock5b/app-development/rkllm_install

## Summary

### Vendor Debian Image (Kernel 5.10.110)

| Feature | Status | Workaround |
|---------|--------|------------|
| iptables | Not supported | Disable in apps |
| TUN device | Not supported | Userspace networking |
| Bridge networking | Not supported | Host networking only |
| Tailscale | Works | `--tun=userspace-networking` |
| Docker | Works | `--network host` only |
| ffmpeg | Works | Static binary install |
| RKLLM/NPU | **Not working** | Cannot patch - driver needs kernel 6.1 |

### Armbian Image (Kernel 6.1) - RECOMMENDED

| Feature | Status | Notes |
|---------|--------|-------|
| iptables | Should work | Standard kernel |
| TUN device | Should work | Standard kernel |
| Bridge networking | Should work | Standard kernel |
| Tailscale | Works | Normal mode |
| Docker | Works | Normal mode |
| RKLLM/NPU | **Works** | RKNPU driver 0.9.7+ included |

## SmolVLM-256M Conversion Guide

This section documents how to convert SmolVLM-256M-Instruct for RK3588 NPU deployment.

### Toolkit Versions (as of Nov 2025)

| Component | Version | Notes |
|-----------|---------|-------|
| rknn-toolkit2 | v2.3.2 | For vision encoder ONNX→RKNN |
| rkllm-toolkit | v1.2.3 | For LLM conversion |
| rknn-llm repo | v1.2.3 | Examples and runtime libs |
| Python | 3.11 or 3.12 | Both have wheel support |

### Installation (x86_64 Linux/WSL)

```bash
# Clone the rknn-llm repo
git clone -b release-v1.2.3 https://github.com/airockchip/rknn-llm.git
cd rknn-llm

# Install rknn-toolkit2 (for vision encoder)
pip install rknn-toolkit2

# Install rkllm-toolkit (for LLM)
pip install ./rkllm-toolkit/packages/rkllm_toolkit-1.2.3-cp312-cp312-linux_x86_64.whl

# Install dependencies
pip install torch transformers onnx
```

### Download SmolVLM Model

```bash
# Using HuggingFace CLI
huggingface-cli download HuggingFaceTB/SmolVLM-256M-Instruct

# Model will be cached at:
# ~/.cache/huggingface/hub/models--HuggingFaceTB--SmolVLM-256M-Instruct/
```

### Critical Issue: Vision Encoder Export

**Problem**: The official `export_vision.py` script exports SmolVLM correctly (with connector), but the resulting ONNX has a ScatterND/Gather type mismatch that RKNN-Toolkit2 cannot process.

**Root Cause**: SmolVLM uses SigLIP vision encoder with dynamic position embedding indexing. PyTorch's ONNX exporter creates invalid graph nodes when tracing this dynamic indexing.

**Solution**: Use a custom static wrapper that pre-computes position embeddings:

```python
"""
SmolVLM Vision + Connector - Static Export for RKNN
Save as: convert_smolvlm_vision.py
"""
import torch
import os
from transformers import SmolVLMForConditionalGeneration

class SmolVLMVisionStatic(torch.nn.Module):
    """
    SmolVLM Vision encoder + Connector with static position embeddings.
    Fixed 512x512 input to avoid dynamic graph issues.
    """
    def __init__(self, vlm, image_size=512):
        super().__init__()
        vision_model = vlm.model.vision_model

        # Copy the embeddings components
        self.patch_embedding = vision_model.embeddings.patch_embedding
        self.patch_size = vision_model.embeddings.patch_size

        # Pre-compute position embeddings for fixed 512x512
        num_patches = (image_size // self.patch_size) ** 2  # 32x32 = 1024 patches
        self.position_embedding = torch.nn.Parameter(
            vision_model.embeddings.position_embedding.weight[:num_patches].clone()
        )

        # Copy the encoder and post-layernorm
        self.encoder = vision_model.encoder
        self.post_layernorm = vision_model.post_layernorm

        # CRITICAL: Include the connector (projector)!
        self.connector = vlm.model.connector

    def forward(self, pixel_values):
        batch_size = pixel_values.shape[0]
        patch_embeds = self.patch_embedding(pixel_values)
        embeddings = patch_embeds.flatten(2).transpose(1, 2)
        embeddings = embeddings + self.position_embedding.unsqueeze(0)
        hidden_states = self.encoder(embeddings).last_hidden_state
        hidden_states = self.post_layernorm(hidden_states)
        # Pass through connector - maps to LLM embedding space!
        image_features = self.connector(hidden_states)
        return image_features

# Load model
MODEL_PATH = "HuggingFaceTB/SmolVLM-256M-Instruct"
model = SmolVLMForConditionalGeneration.from_pretrained(
    MODEL_PATH, torch_dtype=torch.float32, _attn_implementation="eager"
)

# Create static wrapper
vision_model = SmolVLMVisionStatic(model, image_size=512)
vision_model.eval()

# Trace and export
pixel_values = torch.randn(1, 3, 512, 512, dtype=torch.float32)
traced_model = torch.jit.trace(vision_model, pixel_values)

torch.onnx.export(
    traced_model, pixel_values, "smolvlm_vision_static.onnx",
    input_names=['pixel'], output_names=['image_features'],
    opset_version=17, dynamo=False
)
```

### Why the Connector is Critical

| Without Connector | With Connector |
|-------------------|----------------|
| Output: 1024 tokens × 768 dim | Output: **64 tokens × 576 dim** |
| Raw vision features | Features mapped to LLM space |
| LLM cannot understand | LLM receives correct embeddings |
| Model hallucinates | Model works correctly |

### Convert Vision ONNX to RKNN

```python
from rknn.api import RKNN

rknn = RKNN(verbose=False)
# SmolVLM uses SigLIP normalization: mean=0.5, std=0.5
rknn.config(
    target_platform="rk3588",
    mean_values=[[127.5, 127.5, 127.5]],
    std_values=[[127.5, 127.5, 127.5]]
)
rknn.load_onnx("smolvlm_vision_static.onnx")
rknn.build(do_quantization=False)
rknn.export_rknn("smolvlm_vision_rk3588.rknn")
```

### Convert LLM to RKLLM

```python
from rkllm.api import RKLLM

llm = RKLLM()
llm.load_huggingface(model="HuggingFaceTB/SmolVLM-256M-Instruct", device="cpu")
llm.build(
    do_quantization=True,
    quantized_dtype="w8a8",
    target_platform="rk3588",
    num_npu_core=3,
    max_context=4096,
    dataset=None  # Optional: use calibration dataset for better accuracy
)
llm.export_rkllm("smolvlm_llm_w8a8_rk3588.rkllm")
```

**Note**: RKLLM-Toolkit only exports the `LlamaForCausalLM` component from `Idefics3ForConditionalGeneration` - this is expected for multimodal models.

### Runtime Chat Template Configuration

The chat template is configured at **runtime** on the device, not during export:

```c
// In C++ after rkllm_init()
rkllm_set_chat_template(
    llm_handle,
    "",                              // system_prompt (empty)
    "<|im_start|>User:",             // prompt_prefix
    "<end_of_utterance>\nAssistant:" // prompt_postfix
);
```

### SmolVLM Token IDs

| Token | ID | Description |
|-------|-----|-------------|
| `<\|im_start\|>` | 1 | BOS token |
| `<\|im_end\|>` | 2 | PAD token |
| `<image>` | **49190** | Image placeholder |
| `<end_of_utterance>` | 49279 | EOS token |

### Prompt Format

```
<|im_start|>User:<image>What is in this image?<end_of_utterance>
Assistant:
```

The 64 visual tokens from the vision encoder replace the `<image>` token (ID 49190) in the input sequence.

### Output Model Sizes

| File | Size | Description |
|------|------|-------------|
| `smolvlm_vision_rk3588.rknn` | ~194 MB | Vision + Connector (FP16) |
| `smolvlm_llm_w8a8_rk3588.rkllm` | ~207 MB | LLM (W8A8 quantized) |

### Performance Comparison (RK3588)

| Model | Vision Encoding | Visual Tokens | Inference | Notes |
|-------|-----------------|---------------|-----------|-------|
| SmolVLM-256M | **876ms** | 64 | ~1180ms | 2.8x faster encoding |
| InternVL3-1B | 2472ms | 256 | ~480ms | More accurate |

### Troubleshooting

**"The text is/contains..." hallucinations**: Vision encoder missing connector - re-export with connector included.

**ScatterND/Gather ONNX error**: Use the static wrapper script above instead of official export_vision.py.

**"matmul(w8a8) run failed"**: RKNPU driver too old - need v0.9.7+ (requires kernel 6.1).

**1024 tokens instead of 64**: Vision encoder exported without connector.

### Resources

- **SmolVLM Model**: https://huggingface.co/HuggingFaceTB/SmolVLM-256M-Instruct
- **rknn-llm Repo**: https://github.com/airockchip/rknn-llm
- **Radxa RKLLM Guide**: https://docs.radxa.com/en/rock5/rock5c/app-development/rkllm_usage

## Next Steps

1. Download Armbian image from https://www.armbian.com/youyeetoo-r1/
2. Flash to eMMC or SD card
3. Verify kernel 6.1 and RKNPU driver version
4. Run `scripts/setup-rkllm.sh` to build demos
5. Test with InternVL3-1B model
