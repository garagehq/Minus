# HDCP 1.4 Setup Guide

Detailed guide for configuring HDCP 1.4 on the Radxa Rock 5B Plus HDMI RX port using the provided setup scripts.

## Overview

The `setup_hdcp_device.sh` script automates the entire HDCP setup process:

1. Validates your HDCP sink key file
2. Converts the key to the hardware's expected format (little-endian byte-swap)
3. Installs U-Boot with OP-TEE (BL32 firmware required for secure key loading)
4. Patches the device tree to enable HDCP hardware
5. Compiles the kernel module on-device (or uses pre-compiled fallback)
6. Creates a systemd service for automatic HDCP enablement on boot

After a single reboot, HDCP is active permanently.

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Hardware | Radxa Rock 5B Plus |
| OS | Debian Bookworm (other distros may work but are untested) |
| Root access | Script must run as root (`sudo`) |
| HDCP 1.4 sink key | Raw 308-byte DCP LLC format (see Key Requirements below) |

## Key File Requirements

Your HDCP key file must meet these specifications:

| Property | Requirement |
|----------|-------------|
| Size | Exactly **308 bytes** |
| Format | Raw DCP LLC binary format |
| Type ID | First 4 bytes must be `0x02000000` (Sink/Receiver type) |
| KSV | Bytes 5-9; must have exactly 20 ones and 20 zeros in binary |
| Device Keys | Bytes 10-289 (280 bytes); must not be all zeros |
| Padding | Bytes 290-308 (19 bytes); typically zeros |

The script validates all of these automatically and will reject invalid keys with specific error messages.

## Directory Structure

The HDCP setup files are located in the project's `hdcp/` directory:

```
Minus/hdcp/
├── setup_hdcp_device.sh          # Main setup script
├── u-boot-rk2410_2017.09-1_arm64.deb  # U-Boot with OP-TEE
├── vendor_fix.c                  # Kernel module source (preferred)
└── vendor_fix.ko                 # Pre-compiled module (fallback)
```

## Running the Setup

```bash
cd /home/radxa/Minus/hdcp
sudo ./setup_hdcp_device.sh /path/to/your_hdcp_key.bin
```

The script is interactive and will:
- Show progress for each step
- Ask for confirmation before rebooting
- Provide verification commands if you skip the reboot

### Example Output

```
=== Pre-flight Checks ===
[INFO]  Rockchip device detected
[INFO]  Tools: python3, dtc — OK
[INFO]  U-Boot deb: u-boot-rk2410_2017.09-1_arm64.deb
[INFO]  Kernel module source: vendor_fix.c

=== Step 1: Validating HDCP Key ===
[INFO]  OK: 308 bytes, type=Sink, KSV=a1b2c3d4e5, parity=20/20

=== Step 2: Converting Key to Little-Endian ===
[INFO]  KSV: a1b2c3d4e5 (BE) -> e5d4c3b2a1 (LE)
[INFO]  Little-endian key files created in /home/radxa/

=== Step 3: Installing U-Boot with OP-TEE (BL32) ===
[INFO]  Installing new U-Boot with OP-TEE...
[INFO]  Detected boot device: /dev/mmcblk0
[INFO]  U-Boot with OP-TEE installed and flashed

=== Step 4: Fixing Device Tree ===
[INFO]  Applying modifications...
  Enabled hdcp@fde40000
  Enabled hdcp@fde70000
  Added vnvm@380000 partition
  Added hdcp1x-enable
[INFO]  Device tree modified successfully

=== Step 5: Kernel Module ===
[INFO]  Kernel headers found — compiling on device
[INFO]  Module compiled and installed for kernel 6.1.84-8-rk2410

=== Step 6: Installing Systemd Service ===
[INFO]  hdcp-enable.service installed and enabled

=== Setup Complete ===
The device needs to reboot for changes to take effect.
Reboot now? [Y/n]
```

## Verification

After reboot, verify HDCP is working:

```bash
# Check HDCP support is enabled
cat /sys/class/misc/hdmirx_hdcp/support
# Expected: 1

# Check HDCP is enabled
cat /sys/class/misc/hdmirx_hdcp/enable
# Expected: 1

# Check authentication status (with HDCP source connected)
cat /sys/class/misc/hdmirx_hdcp/status
# Expected: HDCP1.4: Authenticated success

# Check the systemd service
systemctl status hdcp-enable.service
# Expected: active (exited)

# Check the kernel module is loaded
lsmod | grep vendor_fix
# Expected: vendor_fix  16384  0
```

## Files Created by Setup

The script creates these files:

| File | Location | Purpose |
|------|----------|---------|
| `hdcp_struct_le.bin` | `/home/radxa/` | Little-endian key for kernel module |
| `hdcp_key_le.hex` | `/home/radxa/` | Hex key for sysfs interface |
| `vendor_fix.ko` | `/home/radxa/` | Compiled kernel module |
| `hdcp-enable.service` | `/etc/systemd/system/` | Auto-start service |

The original DTB is backed up to `*.dtb.bak` before modification.

## Kernel Module Compilation

The `vendor_fix.ko` kernel module must match your running kernel version.

### Automatic On-Device Compilation (Recommended)

If kernel headers are installed, the script compiles the module automatically:

```bash
# Install kernel headers (if not already present)
sudo apt install linux-headers-$(uname -r)

# Re-run setup to compile module
sudo ./setup_hdcp_device.sh /path/to/your_key.bin
```

### Pre-Compiled Fallback

If kernel headers aren't available, the script uses the pre-compiled `vendor_fix.ko`. This only works if the pre-compiled module matches your kernel version exactly.

### Force Recompilation

To force recompilation (e.g., after a kernel update):

```bash
rm /home/radxa/vendor_fix.ko
sudo ./setup_hdcp_device.sh /path/to/your_key.bin
```

## Idempotent Operation

The script is safe to re-run at any time. It detects already-installed components and skips them:

- If OP-TEE is present (`/dev/tee0` exists), U-Boot install is skipped
- If DTB already has HDCP modifications, patching is skipped
- If `vendor_fix.ko` matches the running kernel, compilation is skipped

Re-run the script when:
- Updating the HDCP key
- After a kernel update (to recompile the module)
- After changing boot media (eMMC ↔ SD card)

## Troubleshooting

### Key Validation Failures

| Error | Cause | Solution |
|-------|-------|----------|
| "must be exactly 308 bytes" | Wrong file size | Ensure key is raw DCP format, not hex or base64 |
| "Type ID must be 0x02" | Wrong key type | You have a Source key; need a Sink key |
| "KSV must have exactly 20 set bits" | Invalid KSV | Key file is corrupted or wrong format |
| "DPK is all zeros" | Empty key | Key file is placeholder/invalid |

### HDCP Support Shows 0

Check each component in order:

```bash
# 1. OP-TEE loaded?
ls /dev/tee0
# If missing: U-Boot install failed, re-run setup

# 2. vnvm partition present?
cat /proc/mtd | grep vnvm
# If missing: DTB patch failed

# 3. hdcp1x-enable in device tree?
ls /proc/device-tree/hdmirx-controller@fdee0000/hdcp1x-enable
# If missing: DTB patch failed

# 4. Service running?
systemctl status hdcp-enable.service
# Should be "active (exited)"

# 5. Module loaded?
lsmod | grep vendor_fix
# If missing: module failed to load (kernel mismatch?)
dmesg | grep vendor_fix
# Check for version errors
```

### Status Shows "Authenticated failed"

The HDCP handshake was attempted but rejected:
- Key may be invalid, corrupted, or revoked
- Verify key file is correct 308-byte format

### Status Shows "Unknown status"

No HDCP source is connected, or source hasn't initiated handshake:
- Connect an HDCP source (FireTV, Roku, PS5, etc.)
- Wait a few seconds for handshake to complete
- Check again

### Black Frame Captured

If status shows "Authenticated success" but captures are black:
- Source may be using HDCP 2.x instead of 1.4
- This setup only supports HDCP 1.4
- Most devices fall back to 1.4 automatically; some may not

### Module Fails to Load

```bash
# Check dmesg for errors
dmesg | grep vendor_fix

# If version mismatch, recompile:
sudo apt install linux-headers-$(uname -r)
rm /home/radxa/vendor_fix.ko
sudo ./setup_hdcp_device.sh /path/to/your_key.bin
```

### SD Card Interference

If an SD card with a Radxa image is present, U-Boot may load the DTB from the SD card instead of eMMC. The script handles this automatically by updating both DTBs, but for cleanest results, remove the SD card before running setup.

## Boot Device Detection

The script auto-detects whether the system boots from eMMC or SD card and flashes U-Boot to the correct device. If you change boot media, re-run the setup script.

## Service Management

```bash
# Check service status
systemctl status hdcp-enable.service

# Manually restart HDCP (after modifying key, etc.)
sudo systemctl restart hdcp-enable.service

# Disable HDCP auto-start
sudo systemctl disable hdcp-enable.service

# Re-enable HDCP auto-start
sudo systemctl enable hdcp-enable.service
```

## Capturing HDCP-Protected Content

Once HDCP is authenticated, capture works normally:

```bash
# Single frame capture
gst-launch-1.0 v4l2src device=/dev/video0 num-buffers=1 \
  ! videoconvert ! jpegenc ! filesink location=/tmp/capture.jpg

# Live display
gst-launch-1.0 v4l2src device=/dev/video0 \
  ! videoconvert ! autovideosink

# Record to file
gst-launch-1.0 v4l2src device=/dev/video0 \
  ! video/x-raw,format=NV16 ! videoconvert \
  ! x264enc ! mp4mux ! filesink location=/tmp/recording.mp4
```

> **Note:** The HDMI RX uses the multiplanar V4L2 API. Use GStreamer for capture — `ffmpeg` does not support multiplanar capture on this device.
