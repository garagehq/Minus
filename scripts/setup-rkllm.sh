#!/bin/bash
# RKLLM Setup Script for Youyeetoo R1 (RK3588)
# Prerequisites: RKNPU driver v0.9.7+ (check with: cat /sys/kernel/debug/rknpu/version)

set -e

echo "=== RKLLM Setup Script ==="
echo ""

# Check RKNPU driver version
DRIVER_VERSION=$(cat /sys/kernel/debug/rknpu/version 2>/dev/null | grep -oP 'v\d+\.\d+\.\d+' || echo "unknown")
echo "Current RKNPU driver: $DRIVER_VERSION"

if [[ "$DRIVER_VERSION" == "unknown" ]]; then
    echo "ERROR: Cannot read RKNPU driver version. Is the NPU driver loaded?"
    exit 1
fi

# Extract version numbers for comparison
MAJOR=$(echo "$DRIVER_VERSION" | cut -d'.' -f1 | tr -d 'v')
MINOR=$(echo "$DRIVER_VERSION" | cut -d'.' -f2)
PATCH=$(echo "$DRIVER_VERSION" | cut -d'.' -f3)

# Check if version >= 0.9.7
if [[ "$MAJOR" -eq 0 && "$MINOR" -lt 9 ]] || [[ "$MAJOR" -eq 0 && "$MINOR" -eq 9 && "$PATCH" -lt 7 ]]; then
    echo "ERROR: RKNPU driver $DRIVER_VERSION is too old. Need v0.9.7 or higher."
    echo "RKLLM will not work on this kernel. You need to build a custom image."
    exit 1
fi

echo "Driver version OK!"
echo ""

# Install build dependencies
echo "=== Installing build dependencies ==="
sudo apt update
sudo apt install -y build-essential cmake git

# Set up rknn-llm directory
RKLLM_DIR="$HOME/rknn-llm"
if [[ ! -d "$RKLLM_DIR" ]]; then
    echo "=== Cloning rknn-llm repository ==="
    git clone https://github.com/airockchip/rknn-llm.git "$RKLLM_DIR"
else
    echo "=== rknn-llm already exists at $RKLLM_DIR ==="
fi

# Build the simple LLM API demo
echo ""
echo "=== Building rkllm_api_demo ==="
cd "$RKLLM_DIR/examples/rkllm_api_demo/deploy"

cat > build-native.sh << 'EOF'
#!/bin/bash
set -e
BUILD_TYPE=Release
C_COMPILER=gcc
CXX_COMPILER=g++
TARGET_ARCH=aarch64
TARGET_PLATFORM=linux_${TARGET_ARCH}
ROOT_PWD="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${ROOT_PWD}/build/build_${TARGET_PLATFORM}_${BUILD_TYPE}"
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"
cmake ../.. \
    -DCMAKE_C_COMPILER=${C_COMPILER} \
    -DCMAKE_CXX_COMPILER=${CXX_COMPILER} \
    -DCMAKE_BUILD_TYPE=${BUILD_TYPE}
make -j4
make install
EOF

chmod +x build-native.sh
./build-native.sh

# Build the multimodal demo
echo ""
echo "=== Building multimodal_model_demo ==="
cd "$RKLLM_DIR/examples/multimodal_model_demo/deploy"

cat > build-native.sh << 'EOF'
#!/bin/bash
set -e
rm -rf build
mkdir build && cd build
cmake .. \
    -DCMAKE_CXX_COMPILER=g++ \
    -DCMAKE_C_COMPILER=gcc \
    -DCMAKE_BUILD_TYPE=Release
make -j4
make install
EOF

chmod +x build-native.sh
./build-native.sh

# Create models directory
echo ""
echo "=== Creating models directory ==="
mkdir -p "$HOME/rkllm-models"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Download models from: https://console.box.lenovo.com/l/l0tXb8 (code: rkllm)"
echo "2. Place models in: $HOME/rkllm-models/"
echo ""
echo "To run the multimodal demo:"
echo "  cd $RKLLM_DIR/examples/multimodal_model_demo/deploy/install/demo_Linux_aarch64"
echo "  export LD_LIBRARY_PATH=./lib:\$LD_LIBRARY_PATH"
echo "  cp ../../data/demo.jpg ."
echo "  ln -s $HOME/rkllm-models models"
echo "  ./demo demo.jpg models/<vision>.rknn models/<llm>.rkllm 2048 4096 3 \"<|vision_start|>\" \"<|vision_end|>\" \"<|image_pad|>\""
echo ""
echo "To run the simple LLM demo:"
echo "  cd $RKLLM_DIR/examples/rkllm_api_demo/deploy/install/demo_Linux_aarch64"
echo "  export LD_LIBRARY_PATH=./lib:\$LD_LIBRARY_PATH"
echo "  ./llm_demo $HOME/rkllm-models/<model>.rkllm 2048 4096"
