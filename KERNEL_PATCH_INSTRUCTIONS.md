# Youyeetoo R1 Kernel Patch Instructions

## Goal
Patch the RKNPU driver from v0.8.2 to v0.9.8 to enable RKLLM (LLM inference on NPU).

## Prerequisites

- WSL2 with Ubuntu (x86_64) + Docker installed
- ~60GB free disk space
- Downloaded SDK files (all 6 parts + dl.tar.gz)

---

## Step 1: Install Docker in WSL (if not already installed)

```bash
# Install Docker
sudo apt update
sudo apt install -y docker.io
sudo usermod -aG docker $USER

# Start Docker service
sudo service docker start

# Log out and back in, or run: newgrp docker
```

---

## Step 2: Rename SDK Files (if needed)

If your downloaded files have inconsistent names (Chrome renamed on conflict):

```bash
cd /mnt/c/Users/cyeng/Downloads

# Rename files to correct sequential naming (skip if already correct)
mv "r1_linux_release_v2.0_v3.0_20240928_sdk.tar-003.gz00" "r1_linux_release_v2.0_v3.0_20240928_sdk.tar.gz00" 2>/dev/null
mv "r1_linux_release_v2.0_v3.0_20240928_sdk.tar-002.gz01" "r1_linux_release_v2.0_v3.0_20240928_sdk.tar.gz01" 2>/dev/null
mv "r1_linux_release_v2.0_v3.0_20240928_sdk.tar-004.gz02" "r1_linux_release_v2.0_v3.0_20240928_sdk.tar.gz02" 2>/dev/null
mv "r1_linux_release_v2.0_v3.0_20240928_sdk.tar-005.gz03" "r1_linux_release_v2.0_v3.0_20240928_sdk.tar.gz03" 2>/dev/null
mv "r1_linux_release_v2.0_v3.0_20240928_sdk.tar-006.gz04" "r1_linux_release_v2.0_v3.0_20240928_sdk.tar.gz04" 2>/dev/null
```

---

## Step 3: Extract SDK and Sync Repos

The SDK uses `repo` (Android-style multi-repo management) and extracts directly into `youyeetoo-sdk/`:

```bash
cd ~/stream-sentry-overall/youyeetoo-sdk

# Extract the split archive (extracts into current directory)
# This takes 10-30 minutes
cat r1_linux_release_v2.0_v3.0_20240928_sdk.tar.gz* | tar -zxvf -

# Sync local repositories
.repo/repo/repo sync -l

# Extract pre-downloaded dependencies
tar -zxvf dl.tar.gz -C buildroot/

# Verify kernel directory exists
ls -la kernel/
```

---

## Step 4: Install Build Dependencies (Direct Compilation - No Docker)

**Note:** Ubuntu 20.04 is recommended. Other versions may cause errors.

```bash
sudo apt update
sudo apt install -y \
    git ssh make gcc libssl-dev liblz4-tool expect \
    g++ patchelf chrpath gawk texinfo diffstat \
    bison flex fakeroot cmake unzip \
    device-tree-compiler python3-pip libncurses-dev \
    python3-pyelftools bc libelf-dev python-is-python3
```

---

## Step 5: Patch the RKNPU Driver

**Run these commands OUTSIDE Docker (in WSL), before or after starting Docker:**

```bash
# In WSL (not inside Docker container)
cd ~/stream-sentry-overall/youyeetoo-sdk

# Find the kernel directory
ls -la kernel/

# Backup the original rknpu driver
mv kernel/drivers/rknpu kernel/drivers/rknpu.bak.v0.8.2

# Extract the new v0.9.8 driver to /tmp
cd /tmp
rm -rf /tmp/drivers
tar -xjf ~/stream-sentry-overall/rknn-llm/rknpu-driver/rknpu_driver_0.9.8_20241009.tar.bz2

# Move the new driver into the kernel tree
mv /tmp/drivers/rknpu ~/stream-sentry-overall/youyeetoo-sdk/kernel/drivers/

# Verify the patch
cd ~/stream-sentry-overall/youyeetoo-sdk/kernel
echo "=== Old driver version (backup) ==="
grep -r "RKNPU_DRIVER_VERSION\|0\.8\." drivers/rknpu.bak.v0.8.2/ 2>/dev/null | head -3

echo ""
echo "=== New driver version ==="
grep -r "RKNPU_DRIVER_VERSION\|0\.9\." drivers/rknpu/ 2>/dev/null | head -3
```

The new driver files should show version 0.9.8.

---

## Step 6: Build the Kernel

### Option A: Build kernel only (faster, for testing)

```bash
cd ~/stream-sentry-overall/youyeetoo-sdk/kernel

# Set cross-compiler
export CROSS_COMPILE=../prebuilts/gcc/linux-x86/aarch64/gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu/bin/aarch64-none-linux-gnu-
export ARCH=arm64

# Configure kernel
make rockchip_linux_defconfig rk3588_linux.config

# Build kernel image (this creates boot.img)
make rk3588s-yyt.img -j$(nproc)
```

### Option B: Build full firmware (complete image)

```bash
cd ~/stream-sentry-overall/youyeetoo-sdk

# Set board config first
./build.sh BoardConfig-R1-Debian.mk

# Build everything
./build.sh

# Or build specific components:
./build.sh kernel      # Just kernel
./build.sh uboot       # Just U-Boot
./build.sh recovery    # Just recovery
./build.sh firmware    # Package firmware
./build.sh updateimg   # Create update.img for flashing
```

Build takes 10-60 minutes depending on what you're building.

---

## Step 7: Locate the Built Kernel Image

**Inside Docker or WSL:**

```bash
cd ~/stream-sentry-overall/youyeetoo-sdk

# Find kernel/boot images
find . -name "boot.img" -o -name "Image" -o -name "Image.gz" 2>/dev/null | head -10

# Common locations:
# - kernel/arch/arm64/boot/Image
# - rockdev/boot.img
# - output/images/boot.img
```

---

## Step 8: Flash the Kernel to Your Device

### Option A: Flash just boot.img (safest)
```bash
# From WSL - put device in LOADER mode first
# (hold recovery button while connecting USB / powering on)

# Install rkdeveloptool if needed
sudo apt install -y rkdeveloptool

# Check device is detected
sudo rkdeveloptool ld

# Flash boot partition (kernel)
cd ~/stream-sentry-overall/youyeetoo-sdk
sudo rkdeveloptool db rockdev/MiniLoaderAll.bin  # Or find loader in tools/
sudo rkdeveloptool wl 0x8000 rockdev/boot.img    # Offset may vary
sudo rkdeveloptool rd                             # Reboot device
```

### Option B: Create full firmware and reflash (Windows)
```bash
# Inside Docker - build full image
cd /home/youyeetoo
./build.sh

# Output firmware will be in rockdev/
# Use RKDevTool on Windows to flash the full update.img
```

---

## Step 9: Verify After Flashing

Boot the device and check:
```bash
# Check kernel version
uname -r

# Check RKNPU driver version (should now be 0.9.8)
sudo cat /sys/kernel/debug/rknpu/version
# Expected: RKNPU driver: v0.9.8
```

---

## Troubleshooting

### Build fails with missing dependencies
```bash
sudo apt install -y libelf-dev libssl-dev
```

### Cross-compiler not found
```bash
# Find compilers in the SDK
find ~/stream-sentry-overall/youyeetoo-sdk -name "*aarch64*gcc" -type f 2>/dev/null
```

### Kernel config mismatch
```bash
# Extract config from your running device
scp youyeetoo@<device-ip>:/proc/config.gz .
gunzip config.gz
mv config ~/stream-sentry-overall/youyeetoo-sdk/kernel/.config
```

### Build script not found
```bash
# Check for build script
ls ~/stream-sentry-overall/youyeetoo-sdk/*.sh

# Check board configs
ls ~/stream-sentry-overall/youyeetoo-sdk/device/rockchip/rk3588/
```

### Extraction fails / corrupted archive
```bash
# Verify file sizes match expected
# gz00-gz04: 4GB each (4294967296 bytes)
# gz05: ~1.04GB (1115684864 bytes approx)
ls -la r1_linux_release_v2.0_v3.0_20240928_sdk.tar.gz0*
```

---

## File Checklist

Before extraction, verify you have (after renaming):
- [x] `r1_linux_release_v2.0_v3.0_20240928_sdk.tar.gz00` (4 GB)
- [x] `r1_linux_release_v2.0_v3.0_20240928_sdk.tar.gz01` (4 GB)
- [x] `r1_linux_release_v2.0_v3.0_20240928_sdk.tar.gz02` (4 GB)
- [x] `r1_linux_release_v2.0_v3.0_20240928_sdk.tar.gz03` (4 GB)
- [x] `r1_linux_release_v2.0_v3.0_20240928_sdk.tar.gz04` (4 GB)
- [x] `r1_linux_release_v2.0_v3.0_20240928_sdk.tar.gz05` (1.07 GB)
- [ ] `dl.tar.gz` (734 MB) - optional

---

## Notes

- First full build takes 30-60+ minutes
- Subsequent kernel-only builds take 5-15 minutes
- Keep the backup (`drivers/rknpu.bak.v0.8.2`) in case you need to revert
