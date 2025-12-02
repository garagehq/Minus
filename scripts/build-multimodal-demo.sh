#!/bin/bash
# build-multimodal-demo.sh - Build RKLLM multimodal demo natively on ARM device
# Run this on the Youyeetoo R1 (not on x86 host)

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Find rknn-llm directory
RKLLM_DIR=""
if [ -d "$HOME/rknn-llm" ]; then
    RKLLM_DIR="$HOME/rknn-llm"
elif [ -d "/root/rknn-llm" ]; then
    RKLLM_DIR="/root/rknn-llm"
else
    log_error "rknn-llm directory not found. Clone it first:"
    echo "  git clone https://github.com/airockchip/rknn-llm.git ~/rknn-llm"
    exit 1
fi

DEMO_DIR="$RKLLM_DIR/examples/multimodal_model_demo/deploy"
INSTALL_DIR="$DEMO_DIR/install/demo_Linux_aarch64"

log_info "rknn-llm directory: $RKLLM_DIR"
log_info "Demo directory: $DEMO_DIR"

# Check for native compiler
if ! command -v gcc &> /dev/null; then
    log_error "gcc not found. Install build-essential first."
    exit 1
fi

if ! command -v cmake &> /dev/null; then
    log_error "cmake not found. Install cmake first."
    exit 1
fi

# Verify we're on ARM
ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ]; then
    log_error "This script is for native ARM compilation. Detected: $ARCH"
    exit 1
fi

log_info "Building natively on $ARCH with system gcc..."

cd "$DEMO_DIR"

# Clean previous build
rm -rf build
mkdir build
cd build

# Configure with native compilers (NOT cross-compiler)
cmake .. \
    -DCMAKE_C_COMPILER=gcc \
    -DCMAKE_CXX_COMPILER=g++ \
    -DCMAKE_BUILD_TYPE=Release

# Build
make -j$(nproc)

# Install
make install

log_success "Build complete!"
log_info "Demo binary: $INSTALL_DIR/demo"

# Check if runtime libraries are installed
echo ""
log_info "Checking runtime libraries..."

if [ -f /usr/lib/librkllmrt.so ]; then
    log_success "librkllmrt.so found in /usr/lib"
else
    log_error "librkllmrt.so NOT found. Installing..."
    LIBRKLLM="$RKLLM_DIR/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so"
    if [ -f "$LIBRKLLM" ]; then
        sudo cp "$LIBRKLLM" /usr/lib/
        sudo ldconfig
        log_success "Installed librkllmrt.so"
    else
        log_error "Cannot find librkllmrt.so in repo"
    fi
fi

if [ -f /usr/lib/librknnrt.so ]; then
    log_success "librknnrt.so found in /usr/lib"
else
    log_error "librknnrt.so NOT found. Installing..."
    LIBRKNN="$RKLLM_DIR/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/aarch64/librknnrt.so"
    if [ -f "$LIBRKNN" ]; then
        sudo cp "$LIBRKNN" /usr/lib/
        sudo ldconfig
        log_success "Installed librknnrt.so"
    else
        log_error "Cannot find librknnrt.so in repo"
    fi
fi

echo ""
echo "=========================================="
echo "  Next Steps"
echo "=========================================="
echo ""
echo "1. Download models from: https://console.box.lenovo.com/l/l0tXb8"
echo "   Fetch code: rkllm"
echo ""
echo "2. Create models directory and copy models:"
echo "   mkdir -p $INSTALL_DIR/models"
echo "   # Copy internvl3-1b_vision_fp16_rk3588.rknn -> models/vision.rknn"
echo "   # Copy internvl3-1b_w8a8_rk3588.rkllm -> models/llm.rkllm"
echo ""
echo "3. Run the demo:"
echo "   cd $INSTALL_DIR"
echo "   ./demo demo.jpg models/vision.rknn models/llm.rkllm 2048 4096 3 '<|vision_start|>' '<|vision_end|>' '<|image_pad|>'"
echo ""
