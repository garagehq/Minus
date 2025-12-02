#!/bin/bash
# init-image.sh - Initialize Armbian image on Youyeetoo R1
# Run after flashing Armbian to verify and install required packages

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory (for accessing rknn-llm repo if available)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Default options
DO_CHECK=false
DO_DOCKER=false
DO_TAILSCALE=false
DO_FFMPEG=false
DO_BUILD_DEPS=false
DO_RKLLM=false
DO_ALL=false

usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

Initialize Armbian image on Youyeetoo R1 after first boot.

Options:
  --check           Verify system (kernel version, RKNPU driver) - always runs first
  --docker          Install Docker
  --tailscale       Install Tailscale
  --ffmpeg          Install ffmpeg
  --build-deps      Install build dependencies (gcc, cmake, etc.)
  --rkllm           Clone rknn-llm repo and build multimodal demo
  --all             Install everything (docker, tailscale, ffmpeg, build-deps, rkllm)
  -h, --help        Show this help message

Examples:
  $(basename "$0") --check                    # Just verify system
  $(basename "$0") --check --docker           # Verify and install Docker
  $(basename "$0") --all                      # Install everything

EOF
    exit 0
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

# =============================================================================
# System Verification
# =============================================================================

check_system() {
    echo ""
    echo "=========================================="
    echo "  System Verification"
    echo "=========================================="

    local all_ok=true

    # Check kernel version
    local kernel_version=$(uname -r)
    log_info "Kernel version: $kernel_version"

    if [[ "$kernel_version" == 6.1.* ]]; then
        log_success "Kernel 6.1.x detected - compatible with RKLLM"
    elif [[ "$kernel_version" == 5.10.* ]]; then
        log_error "Kernel 5.10.x detected - NOT compatible with RKLLM (need 6.1+)"
        all_ok=false
    else
        log_warn "Unexpected kernel version: $kernel_version"
    fi

    # Check RKNPU driver version
    local rknpu_version_file="/sys/kernel/debug/rknpu/version"
    if [ -f "$rknpu_version_file" ]; then
        local rknpu_version=$(cat "$rknpu_version_file" 2>/dev/null || echo "unknown")
        log_info "RKNPU driver: $rknpu_version"

        # Extract version number (e.g., "RKNPU driver: v0.9.7" -> "0.9.7")
        local version_num=$(echo "$rknpu_version" | grep -oP 'v?\K[0-9]+\.[0-9]+\.[0-9]+' || echo "")
        if [ -n "$version_num" ]; then
            local major=$(echo "$version_num" | cut -d. -f1)
            local minor=$(echo "$version_num" | cut -d. -f2)
            local patch=$(echo "$version_num" | cut -d. -f3)

            # Check if >= 0.9.7
            if [ "$major" -gt 0 ] || ([ "$major" -eq 0 ] && [ "$minor" -gt 9 ]) || \
               ([ "$major" -eq 0 ] && [ "$minor" -eq 9 ] && [ "$patch" -ge 7 ]); then
                log_success "RKNPU driver >= 0.9.7 - compatible with RKLLM"
            else
                log_error "RKNPU driver < 0.9.7 - NOT compatible with RKLLM"
                all_ok=false
            fi
        else
            log_warn "Could not parse RKNPU version"
        fi
    else
        log_warn "RKNPU debug file not found (may need to mount debugfs)"
        log_info "Trying: mount -t debugfs none /sys/kernel/debug"
        mount -t debugfs none /sys/kernel/debug 2>/dev/null || true

        if [ -f "$rknpu_version_file" ]; then
            local rknpu_version=$(cat "$rknpu_version_file" 2>/dev/null || echo "unknown")
            log_info "RKNPU driver: $rknpu_version"
        else
            log_warn "RKNPU driver version still not accessible"
        fi
    fi

    # Check CPU info
    log_info "CPU: $(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | xargs || echo 'ARM64')"
    log_info "Cores: $(nproc)"
    log_info "Memory: $(free -h | awk '/^Mem:/{print $2}')"

    # Check disk space
    local disk_free=$(df -h / | awk 'NR==2 {print $4}')
    log_info "Disk free: $disk_free"

    # Check architecture
    local arch=$(uname -m)
    log_info "Architecture: $arch"
    if [ "$arch" != "aarch64" ]; then
        log_error "Expected aarch64, got $arch"
        all_ok=false
    fi

    echo ""
    if $all_ok; then
        log_success "System verification passed!"
    else
        log_error "System verification failed - see errors above"
    fi

    return 0
}

# =============================================================================
# Installation Functions
# =============================================================================

install_docker() {
    echo ""
    echo "=========================================="
    echo "  Installing Docker"
    echo "=========================================="

    if command -v docker &> /dev/null; then
        log_info "Docker already installed: $(docker --version)"
        # Ensure service is running
        systemctl is-active --quiet docker || systemctl start docker
        return 0
    fi

    log_info "Installing Docker dependencies..."
    apt-get update
    apt-get install -y ca-certificates curl gnupg

    log_info "Adding Docker GPG key..."
    install -m 0755 -d /etc/apt/keyrings

    # Detect OS (Ubuntu or Debian)
    local os_id=$(. /etc/os-release && echo "$ID")
    local codename=$(. /etc/os-release && echo "$VERSION_CODENAME")

    log_info "Detected OS: $os_id ($codename)"

    # Clean up any existing docker repo config (handles bad state from previous runs)
    rm -f /etc/apt/keyrings/docker.gpg
    rm -f /etc/apt/sources.list.d/docker.list

    if [ "$os_id" = "ubuntu" ]; then
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --batch --yes --dearmor -o /etc/apt/keyrings/docker.gpg
        chmod a+r /etc/apt/keyrings/docker.gpg
        echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $codename stable" > /etc/apt/sources.list.d/docker.list
    else
        curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --batch --yes --dearmor -o /etc/apt/keyrings/docker.gpg
        chmod a+r /etc/apt/keyrings/docker.gpg
        echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $codename stable" > /etc/apt/sources.list.d/docker.list
    fi

    log_info "Installing Docker packages..."
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    log_info "Starting Docker service..."
    systemctl enable docker
    systemctl start docker

    log_success "Docker installed successfully!"
    docker --version
}

install_tailscale() {
    echo ""
    echo "=========================================="
    echo "  Installing Tailscale"
    echo "=========================================="

    if command -v tailscale &> /dev/null; then
        log_info "Tailscale already installed: $(tailscale version | head -1)"
        return 0
    fi

    log_info "Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh

    log_info "Enabling Tailscale service..."
    systemctl enable tailscaled
    systemctl start tailscaled

    log_success "Tailscale installed successfully!"
    log_info "Run 'sudo tailscale up' to authenticate"
}

install_ffmpeg() {
    echo ""
    echo "=========================================="
    echo "  Installing ffmpeg"
    echo "=========================================="

    if command -v ffmpeg &> /dev/null; then
        log_info "ffmpeg already installed: $(ffmpeg -version 2>&1 | head -1)"
        return 0
    fi

    log_info "Installing ffmpeg via apt..."
    apt-get update
    apt-get install -y ffmpeg

    log_success "ffmpeg installed successfully!"
    ffmpeg -version 2>&1 | head -1
}

install_build_deps() {
    echo ""
    echo "=========================================="
    echo "  Installing Build Dependencies"
    echo "=========================================="

    log_info "Installing build-essential, cmake, and other dependencies..."
    apt-get update
    apt-get install -y \
        build-essential \
        cmake \
        git \
        curl \
        wget \
        pkg-config \
        libssl-dev \
        net-tools

    log_success "Build dependencies installed!"
    log_info "gcc: $(gcc --version | head -1)"
    log_info "cmake: $(cmake --version | head -1)"
}

setup_rkllm() {
    echo ""
    echo "=========================================="
    echo "  Setting up RKLLM"
    echo "=========================================="

    # Use /root for root user, otherwise use SUDO_USER's home
    local target_home="$HOME"
    if [ "$EUID" -eq 0 ] && [ -n "$SUDO_USER" ]; then
        target_home=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    fi
    local rkllm_dir="$target_home/rknn-llm"

    # Clone rknn-llm repo if not exists
    if [ -d "$rkllm_dir" ]; then
        log_info "rknn-llm repo already exists at $rkllm_dir"
    else
        log_info "Cloning rknn-llm repository..."
        git clone https://github.com/airockchip/rknn-llm.git "$rkllm_dir"
        # Fix ownership if running as sudo
        if [ "$EUID" -eq 0 ] && [ -n "$SUDO_USER" ]; then
            chown -R "$SUDO_USER:$SUDO_USER" "$rkllm_dir"
        fi
    fi

    # Install RKLLM runtime libraries (always update in case of version changes)
    log_info "Installing RKLLM runtime libraries..."
    local librkllm="$rkllm_dir/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so"
    local librknn="$rkllm_dir/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/aarch64/librknnrt.so"

    if [ -f "$librkllm" ]; then
        cp "$librkllm" /usr/lib/
        log_success "Installed librkllmrt.so"
    else
        log_warn "librkllmrt.so not found at $librkllm"
    fi

    if [ -f "$librknn" ]; then
        cp "$librknn" /usr/lib/
        log_success "Installed librknnrt.so"
    else
        log_warn "librknnrt.so not found at $librknn"
    fi

    ldconfig

    # Build multimodal demo (skip if already built)
    local demo_dir="$rkllm_dir/examples/multimodal_model_demo/deploy"
    local demo_binary="$demo_dir/install/demo_Linux_aarch64/demo"

    if [ -f "$demo_binary" ]; then
        log_info "Multimodal demo already built at $demo_binary"
        log_info "To rebuild, delete: rm -rf $demo_dir/build $demo_dir/install"
    else
        log_info "Building multimodal demo..."
        cd "$demo_dir"

        rm -rf build
        mkdir build && cd build
        cmake .. \
            -DCMAKE_CXX_COMPILER=g++ \
            -DCMAKE_C_COMPILER=gcc \
            -DCMAKE_BUILD_TYPE=Release
        make -j$(nproc)
        make install

        # Fix ownership if running as sudo
        if [ "$EUID" -eq 0 ] && [ -n "$SUDO_USER" ]; then
            chown -R "$SUDO_USER:$SUDO_USER" "$demo_dir/build" "$demo_dir/install"
        fi

        log_success "RKLLM multimodal demo built!"
    fi

    log_info "Demo location: $demo_dir/install/demo_Linux_aarch64/"

    echo ""
    log_info "Next steps:"
    echo "  1. Download models from: https://console.box.lenovo.com/l/l0tXb8 (code: rkllm)"
    echo "  2. Copy models to: $demo_dir/install/demo_Linux_aarch64/models/"
    echo "  3. Run demo:"
    echo "     cd $demo_dir/install/demo_Linux_aarch64"
    echo "     ./demo demo.jpg models/vision.rknn models/llm.rkllm 2048 4096 3 \"<|vision_start|>\" \"<|vision_end|>\" \"<|image_pad|>\""
}

# =============================================================================
# Main
# =============================================================================

# Parse arguments
if [ $# -eq 0 ]; then
    usage
fi

while [ $# -gt 0 ]; do
    case "$1" in
        --check)
            DO_CHECK=true
            shift
            ;;
        --docker)
            DO_DOCKER=true
            shift
            ;;
        --tailscale)
            DO_TAILSCALE=true
            shift
            ;;
        --ffmpeg)
            DO_FFMPEG=true
            shift
            ;;
        --build-deps)
            DO_BUILD_DEPS=true
            shift
            ;;
        --rkllm)
            DO_RKLLM=true
            shift
            ;;
        --all)
            DO_ALL=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

# --all enables everything
if $DO_ALL; then
    DO_CHECK=true
    DO_DOCKER=true
    DO_TAILSCALE=true
    DO_FFMPEG=true
    DO_BUILD_DEPS=true
    DO_RKLLM=true
fi

# Always run check first if any install is requested
if $DO_DOCKER || $DO_TAILSCALE || $DO_FFMPEG || $DO_BUILD_DEPS || $DO_RKLLM; then
    DO_CHECK=true
fi

# Check root for install operations
if $DO_DOCKER || $DO_TAILSCALE || $DO_FFMPEG || $DO_BUILD_DEPS || $DO_RKLLM; then
    check_root
fi

echo ""
echo "=========================================="
echo "  Youyeetoo R1 Armbian Initialization"
echo "=========================================="
echo ""

# Run selected operations
if $DO_CHECK; then
    check_system
fi

if $DO_FFMPEG; then
    install_ffmpeg
fi

if $DO_BUILD_DEPS; then
    install_build_deps
fi

if $DO_DOCKER; then
    install_docker
fi

if $DO_TAILSCALE; then
    install_tailscale
fi

if $DO_RKLLM; then
    # Ensure build deps are installed first
    if ! command -v cmake &> /dev/null; then
        install_build_deps
    fi
    setup_rkllm
fi

echo ""
echo "=========================================="
echo "  Complete!"
echo "=========================================="
echo ""

if $DO_TAILSCALE; then
    log_info "Don't forget to run: sudo tailscale up"
fi
