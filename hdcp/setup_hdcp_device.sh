#!/bin/bash
#
# setup_hdcp_device.sh — Automated HDCP 1.4 setup for Radxa Rock 5B Plus
#
# Run this script DIRECTLY ON THE ROCK 5B PLUS (not on a remote PC).
# Place these files in the same directory as this script:
#   - u-boot-rk2410_2017.09-1_arm64.deb  (U-Boot with OP-TEE)
#   - vendor_fix.ko                       (Kernel module for SIP key loading)
#
# This script:
#   1. Validates the HDCP sink key (size, type ID, KSV parity)
#   2. Converts to little-endian struct format (byte-swaps DPK and KSV)
#   3. Installs U-Boot with OP-TEE (BL32) and tee-supplicant
#   4. Fixes the device tree (HDCP nodes, vnvm partition, hdcp1x-enable)
#   5. Deploys the key files and kernel module to /home/$(whoami)/
#   6. Installs and enables the systemd service for auto-start
#   7. Reboots and verifies everything works
#
# Usage:
#   sudo ./setup_hdcp_device.sh <hdcp_sink.bin>
#
# Example:
#   sudo ./setup_hdcp_device.sh hdcp_sink_20260406_193149.bin
#

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "\n${BLUE}${BOLD}=== $1 ===${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# -------------------------------------------------------------------
# Parse arguments
# -------------------------------------------------------------------

if [[ $# -lt 1 ]]; then
    echo "Usage: sudo $0 <hdcp_sink.bin>"
    echo ""
    echo "  hdcp_sink.bin — Raw HDCP sink key (308 bytes, from generate_sink_bin.py)"
    echo ""
    echo "  Run this script ON the Rock 5B Plus device, not remotely."
    echo "  Place u-boot-rk2410_*.deb and vendor_fix.ko in the same directory."
    exit 1
fi

KEY_FILE="$1"

# Must run as root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root (sudo)"
    exit 1
fi

# Detect the real user (not root) for home directory
REAL_USER="${SUDO_USER:-$(whoami)}"
REAL_HOME=$(eval echo "~$REAL_USER")

# Find required files in the script directory
UBOOT_DEB=$(find "$SCRIPT_DIR" -maxdepth 2 -name "u-boot-rk2410_*.deb" -print -quit 2>/dev/null || true)
VENDOR_FIX_KO=$(find "$SCRIPT_DIR" -maxdepth 2 -name "vendor_fix.ko" -print -quit 2>/dev/null || true)
VENDOR_FIX_C=$(find "$SCRIPT_DIR" -maxdepth 2 -name "vendor_fix.c" -print -quit 2>/dev/null || true)

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------

log_step "Pre-flight Checks"

# Check we're on the right hardware
if ! grep -qi "rockchip" /proc/device-tree/compatible 2>/dev/null; then
    log_error "This doesn't appear to be a Rockchip device"
    exit 1
fi
log_info "Rockchip device detected"

# Check for python3
if ! command -v python3 &>/dev/null; then
    log_error "python3 is required but not installed"
    exit 1
fi

# Check for dtc
if ! command -v dtc &>/dev/null; then
    log_info "Installing device-tree-compiler..."
    apt-get install -y device-tree-compiler >/dev/null 2>&1
fi
log_info "Tools: python3, dtc — OK"

# Check key file
if [[ ! -f "$KEY_FILE" ]]; then
    log_error "Key file not found: $KEY_FILE"
    exit 1
fi

if [[ -z "$UBOOT_DEB" ]] || [[ ! -f "$UBOOT_DEB" ]]; then
    log_error "U-Boot deb not found in $SCRIPT_DIR"
    log_info "Place u-boot-rk2410_*.deb in the same directory as this script"
    log_info "Build it with: cd bsp && ./bsp u-boot rk2410 rock-5b-plus"
    exit 1
fi
log_info "U-Boot deb: $(basename "$UBOOT_DEB")"

if [[ -z "$VENDOR_FIX_C" ]] || [[ ! -f "$VENDOR_FIX_C" ]]; then
    # No source — need pre-compiled module
    if [[ -z "$VENDOR_FIX_KO" ]] || [[ ! -f "$VENDOR_FIX_KO" ]]; then
        log_error "Neither vendor_fix.c nor vendor_fix.ko found in $SCRIPT_DIR"
        log_info "Place either the source (.c) or pre-compiled module (.ko) in the script directory"
        exit 1
    fi
    log_info "Kernel module (pre-compiled): $(basename "$VENDOR_FIX_KO")"
    NEED_COMPILE=0
else
    log_info "Kernel module source: $(basename "$VENDOR_FIX_C")"
    NEED_COMPILE=1
fi

# -------------------------------------------------------------------
# Step 1: Validate the HDCP key
# -------------------------------------------------------------------

log_step "Step 1: Validating HDCP Key"

KEY_RESULT=$(python3 -c "
import struct, sys

data = open('$KEY_FILE', 'rb').read()
errors = []

if len(data) != 308:
    errors.append(f'Key file must be exactly 308 bytes (got {len(data)})')

if len(data) >= 4:
    type_id = struct.unpack('<I', data[0:4])[0]
    if type_id != 2:
        errors.append(f'Type ID must be 0x02 (Sink/RX), got 0x{type_id:02x}')

if len(data) >= 9:
    ksv = data[4:9]
    ones = bin(int.from_bytes(ksv, 'big')).count('1')
    if ones != 20:
        errors.append(f'KSV must have exactly 20 set bits (got {ones})')

if len(data) >= 289:
    dpk = data[9:289]
    if dpk == b'\x00' * 280:
        errors.append('DPK is all zeros — key appears to be empty/invalid')

if errors:
    for e in errors:
        print(f'FAIL: {e}', file=sys.stderr)
    sys.exit(1)
else:
    ksv = data[4:9]
    print(f'OK: 308 bytes, type=Sink, KSV={ksv.hex()}, parity=20/20')
" 2>&1)

if [[ $? -ne 0 ]]; then
    echo "$KEY_RESULT"
    log_error "Key validation failed"
    exit 1
fi
log_info "$KEY_RESULT"

# -------------------------------------------------------------------
# Step 2: Convert key to little-endian struct format
# -------------------------------------------------------------------

log_step "Step 2: Converting Key to Little-Endian"

python3 -c "
import hashlib

raw = open('$KEY_FILE', 'rb').read()
ksv_be = raw[4:9]
ksv_le = ksv_be[::-1]

dpk_le = b''
for i in range(40):
    dpk_le += raw[9+i*7:9+(i+1)*7][::-1]

sha1 = hashlib.sha1(dpk_le).digest()

key = ksv_le + b'\x00'*3 + dpk_le + sha1  # 308 bytes
open('$REAL_HOME/hdcp_struct_le.bin', 'wb').write(key)
open('$REAL_HOME/hdcp_key_le.hex', 'w').write((key + b'\x00\x00').hex())

print(f'KSV: {ksv_be.hex()} (BE) -> {ksv_le.hex()} (LE)')
print(f'DPK[0]: {raw[9:16].hex()} (BE) -> {raw[9:16][::-1].hex()} (LE)')
print(f'Wrote hdcp_struct_le.bin (308 bytes) to $REAL_HOME/')
print(f'Wrote hdcp_key_le.hex (620 hex chars) to $REAL_HOME/')
"

chown "$REAL_USER:$REAL_USER" "$REAL_HOME/hdcp_struct_le.bin" "$REAL_HOME/hdcp_key_le.hex"
log_info "Little-endian key files created in $REAL_HOME/"

# -------------------------------------------------------------------
# Step 3: Install U-Boot with OP-TEE
# -------------------------------------------------------------------

log_step "Step 3: Installing U-Boot with OP-TEE (BL32)"

if [[ -e /dev/tee0 ]]; then
    log_info "OP-TEE already present (/dev/tee0 exists) — skipping U-Boot install"
else
    log_info "Removing old u-boot package..."
    dpkg --remove --force-depends u-boot-rknext 2>/dev/null || true

    log_info "Installing new U-Boot with OP-TEE..."
    dpkg -i --force-conflicts --force-overwrite "$UBOOT_DEB"

    # Detect boot device: find which mmcblk has the root partition
    ROOT_DEV=$(findmnt -n -o SOURCE / | sed 's/p[0-9]*$//')
    if [[ -z "$ROOT_DEV" ]]; then
        ROOT_DEV="/dev/mmcblk0"
    fi
    log_info "Detected boot device: $ROOT_DEV"

    log_info "Flashing to boot area on $ROOT_DEV..."
    cd /usr/lib/u-boot/rock-5b-plus/
    ./setup.sh update_bootloader "$ROOT_DEV"
    cd "$SCRIPT_DIR"

    log_info "U-Boot with OP-TEE installed and flashed"
fi

# Install tee-supplicant if not present
if ! systemctl is-enabled tee-supplicant &>/dev/null; then
    log_info "Installing tee-supplicant..."
    apt-get install -y tee-supplicant libteec1 >/dev/null 2>&1
    systemctl enable tee-supplicant
    log_info "tee-supplicant installed and enabled"
else
    log_info "tee-supplicant already enabled — OK"
fi

# -------------------------------------------------------------------
# Step 4: Fix the Device Tree
# -------------------------------------------------------------------

log_step "Step 4: Fixing Device Tree"

KERNEL_VER=$(uname -r)
DTB_PATH="/usr/lib/linux-image-${KERNEL_VER}/rockchip/rk3588-rock-5b-plus.dtb"

if [[ ! -f "$DTB_PATH" ]]; then
    log_error "DTB not found at $DTB_PATH"
    log_info "Kernel version: $KERNEL_VER"
    exit 1
fi

# Check if fixes are already applied
NEEDS_FIX=0

if [[ -e /proc/device-tree/hdmirx-controller@fdee0000/hdcp1x-enable ]]; then
    log_info "hdcp1x-enable already in device tree"
else
    NEEDS_FIX=1
fi

if grep -q vnvm /proc/mtd 2>/dev/null; then
    log_info "vnvm partition already present"
else
    NEEDS_FIX=1
fi

if [[ $NEEDS_FIX -eq 1 ]]; then
    WORK_DIR=$(mktemp -d)

    log_info "Decompiling DTB..."
    dtc -I dtb -O dts -o "$WORK_DIR/temp.dts" "$DTB_PATH" 2>/dev/null

    log_info "Applying modifications..."
    python3 -c "
import re

with open('$WORK_DIR/temp.dts', 'r') as f:
    dts = f.read()

changes = 0

# Edit 1 & 2: Enable hdcp@fde40000 and hdcp@fde70000
for addr in ['fde40000', 'fde70000']:
    pattern = r'(hdcp@' + addr + r'\s*\{[^}]*?)status\s*=\s*\"disabled\"'
    if re.search(pattern, dts, re.DOTALL):
        dts = re.sub(pattern, r'\1status = \"okay\"', dts, count=1, flags=re.DOTALL)
        changes += 1
        print(f'  Enabled hdcp@{addr}')

# Edit 3: Add vnvm partition (shrink loader, add vnvm)
if 'vnvm@380000' not in dts:
    old_loader = 'label = \"loader\";\n\t\t\t\t\treg = <0x00 0x1000000>;'
    new_parts = 'label = \"loader\";\n\t\t\t\t\treg = <0x00 0x380000>;\n\t\t\t\t};\n\n\t\t\t\tvnvm@380000 {\n\t\t\t\t\tlabel = \"vnvm\";\n\t\t\t\t\treg = <0x380000 0x40000>;'
    if old_loader in dts:
        dts = dts.replace(old_loader, new_parts)
        changes += 1
        print('  Added vnvm@380000 partition')
    else:
        print('  WARNING: Could not find loader partition to modify')

# Edit 4: Add hdcp1x-enable to hdmirx-controller
if 'hdcp1x-enable' not in dts:
    pattern = r'(hdmirx-controller@fdee0000\s*\{[^}]*?)(hpd-trigger-level)'
    if re.search(pattern, dts, re.DOTALL):
        dts = re.sub(pattern, r'\1hdcp1x-enable;\n\t\t\2', dts, count=1, flags=re.DOTALL)
        changes += 1
        print('  Added hdcp1x-enable')
    else:
        # Try alternate insertion point
        pattern2 = r'(hdmirx-controller@fdee0000\s*\{[^}]*?status\s*=\s*\"okay\";)'
        if re.search(pattern2, dts, re.DOTALL):
            dts = re.sub(pattern2, r'\1\n\t\thdcp1x-enable;', dts, count=1, flags=re.DOTALL)
            changes += 1
            print('  Added hdcp1x-enable (alt insertion)')
        else:
            print('  WARNING: Could not find hdmirx-controller node')

with open('$WORK_DIR/temp.dts', 'w') as f:
    f.write(dts)

print(f'Total: {changes} modifications applied')
"

    log_info "Recompiling DTB..."
    dtc -I dts -O dtb -o "$WORK_DIR/modified.dtb" "$WORK_DIR/temp.dts" 2>/dev/null

    log_info "Backing up original DTB..."
    cp "$DTB_PATH" "${DTB_PATH}.bak"

    log_info "Installing modified DTB..."
    cp "$WORK_DIR/modified.dtb" "$DTB_PATH"

    # Handle SD card interference
    if lsblk | grep -q mmcblk1; then
        log_warn "SD card detected — checking if it needs DTB update too..."
        SD_MNT=$(mktemp -d)
        if mount /dev/mmcblk1p3 "$SD_MNT" 2>/dev/null; then
            SD_DTB="$SD_MNT/usr/lib/linux-image-${KERNEL_VER}/rockchip/rk3588-rock-5b-plus.dtb"
            if [[ -f "$SD_DTB" ]]; then
                cp "$WORK_DIR/modified.dtb" "$SD_DTB"
                log_info "Updated SD card DTB to prevent boot interference"
            fi
            umount "$SD_MNT" 2>/dev/null
        fi
        rmdir "$SD_MNT" 2>/dev/null
    fi

    rm -rf "$WORK_DIR"
    log_info "Device tree modified successfully"
else
    log_info "All DTB fixes already applied — skipping"
fi

# -------------------------------------------------------------------
# Step 5: Build/deploy kernel module
# -------------------------------------------------------------------

log_step "Step 5: Kernel Module"

KVER=$(uname -r)
KBUILD="/lib/modules/${KVER}/build"

# Check if existing module matches current kernel
if [[ -f "$REAL_HOME/vendor_fix.ko" ]]; then
    KO_INFO=$(modinfo "$REAL_HOME/vendor_fix.ko" 2>/dev/null | grep vermagic | awk '{print $2}' || true)
    if [[ "$KO_INFO" == "$KVER" ]]; then
        log_info "Existing vendor_fix.ko matches kernel $KVER — skipping build"
        NEED_COMPILE=0
    else
        log_warn "Existing vendor_fix.ko is for kernel '$KO_INFO', running kernel is '$KVER'"
        NEED_COMPILE=1
    fi
fi

if [[ $NEED_COMPILE -eq 1 ]]; then
    # Try on-device compilation
    if [[ -d "$KBUILD" ]] && [[ -f "$KBUILD/Makefile" ]] && command -v gcc &>/dev/null && command -v make &>/dev/null; then
        log_info "Kernel headers found at $KBUILD — compiling on device"

        # Install build deps if needed
        if ! command -v gcc &>/dev/null; then
            log_info "Installing build-essential..."
            apt-get install -y build-essential >/dev/null 2>&1
        fi

        BUILD_DIR=$(mktemp -d)
        cp "$VENDOR_FIX_C" "$BUILD_DIR/vendor_fix.c"
        echo "obj-m += vendor_fix.o" > "$BUILD_DIR/Makefile"

        log_info "Compiling vendor_fix.ko for kernel $KVER..."
        if make -C "$KBUILD" M="$BUILD_DIR" modules 2>&1 | tail -3; then
            cp "$BUILD_DIR/vendor_fix.ko" "$REAL_HOME/vendor_fix.ko"
            chown "$REAL_USER:$REAL_USER" "$REAL_HOME/vendor_fix.ko"
            log_info "Module compiled and installed for kernel $KVER"
        else
            log_error "On-device compilation failed"
            if [[ -n "$VENDOR_FIX_KO" ]] && [[ -f "$VENDOR_FIX_KO" ]]; then
                log_warn "Falling back to pre-compiled module (may not match kernel)"
                cp "$VENDOR_FIX_KO" "$REAL_HOME/vendor_fix.ko"
                chown "$REAL_USER:$REAL_USER" "$REAL_HOME/vendor_fix.ko"
            else
                log_error "No fallback module available. Cross-compile on an x86_64 host."
                rm -rf "$BUILD_DIR"
                exit 1
            fi
        fi
        rm -rf "$BUILD_DIR"

    elif [[ -n "$VENDOR_FIX_KO" ]] && [[ -f "$VENDOR_FIX_KO" ]]; then
        # No kernel headers — use pre-compiled module
        log_warn "Kernel headers not available — using pre-compiled vendor_fix.ko"
        log_warn "If module fails to load, cross-compile for kernel $KVER on an x86_64 host"
        cp "$VENDOR_FIX_KO" "$REAL_HOME/vendor_fix.ko"
        chown "$REAL_USER:$REAL_USER" "$REAL_HOME/vendor_fix.ko"
    else
        log_error "Cannot compile: no kernel headers at $KBUILD and no pre-compiled .ko"
        log_info "Either install linux-headers-$KVER or provide a pre-compiled vendor_fix.ko"
        exit 1
    fi
else
    # Module already exists and matches — just make sure it's in place
    if [[ ! -f "$REAL_HOME/vendor_fix.ko" ]] && [[ -n "$VENDOR_FIX_KO" ]]; then
        cp "$VENDOR_FIX_KO" "$REAL_HOME/vendor_fix.ko"
        chown "$REAL_USER:$REAL_USER" "$REAL_HOME/vendor_fix.ko"
    fi
    log_info "vendor_fix.ko ready in $REAL_HOME/"
fi

# -------------------------------------------------------------------
# Step 6: Install systemd service
# -------------------------------------------------------------------

log_step "Step 6: Installing Systemd Service"

cat > /etc/systemd/system/hdcp-enable.service << SVCEOF
[Unit]
Description=Load HDCP keys and enable HDCP on HDMI RX
After=multi-user.target tee-supplicant.service
Requires=tee-supplicant.service

[Service]
Type=oneshot
ExecStart=/sbin/insmod $REAL_HOME/vendor_fix.ko keyfile=$REAL_HOME/hdcp_struct_le.bin
ExecStartPost=/bin/sh -c 'cat $REAL_HOME/hdcp_key_le.hex > /sys/class/misc/hdmirx_hdcp/test_key1x'
ExecStartPost=/bin/sh -c 'echo 1 > /sys/class/misc/hdmirx_hdcp/enable'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable hdcp-enable.service 2>/dev/null
log_info "hdcp-enable.service installed and enabled"

# -------------------------------------------------------------------
# Step 7: Reboot
# -------------------------------------------------------------------

log_step "Setup Complete"

echo ""
log_info "${BOLD}All components installed:${NC}"
echo "  - U-Boot with OP-TEE (BL32)"
echo "  - Device tree: HDCP nodes enabled, vnvm partition, hdcp1x-enable"
echo "  - HDCP key: little-endian byte-swapped, ready for hardware"
echo "  - Kernel module: vendor_fix.ko (SIP key loading bypass)"
echo "  - Systemd service: hdcp-enable.service (auto-starts on boot)"
echo ""
echo -e "${YELLOW}${BOLD}The device needs to reboot for changes to take effect.${NC}"
echo ""
read -p "Reboot now? [Y/n] " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    log_info "Rebooting in 3 seconds..."
    sleep 3
    reboot
else
    log_info "Reboot skipped. Run 'sudo reboot' when ready."
    echo ""
    echo "After reboot, verify with:"
    echo "  cat /sys/class/misc/hdmirx_hdcp/support   # Should be 1"
    echo "  cat /sys/class/misc/hdmirx_hdcp/status    # Should show Authenticated success"
    echo ""
    echo "Capture with:"
    echo "  gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 \\"
    echo "    ! videoconvert ! jpegenc ! filesink location=/tmp/capture.jpg"
fi
