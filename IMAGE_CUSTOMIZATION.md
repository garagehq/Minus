# Pre-baking Configurations into the Youyeetoo R1 Image

This document describes modifications you can make to the SDK rootfs to avoid running INSTALL.sh post-boot.

---

## What Can Be Pre-Baked

| Item | Can Pre-bake? | How |
|------|---------------|-----|
| APT source fixes | Yes | Edit rootfs `/etc/apt/sources.list` |
| Package unhold | Partial | Modify package build configs |
| ffmpeg static | Yes | Copy binary to rootfs |
| Docker install | Yes | Install in rootfs chroot |
| Docker config | Yes | Add config files to rootfs |
| Tailscale install | Yes | Install in rootfs chroot |
| Tailscale config | Yes | Add systemd override to rootfs |
| RKLLM runtime libs | Yes | Copy to rootfs `/usr/lib/` |

---

## Locating the Rootfs in the SDK

After extracting the SDK, look for:
```bash
# Debian/Ubuntu rootfs location (varies by SDK)
find . -name "rootfs" -type d
find . -name "*.ext4" -o -name "linaro-rootfs.img"

# Common locations:
# - output/images/rootfs/
# - debian/
# - ubuntu/
# - buildroot/output/target/
```

---

## Method 1: Modify Rootfs Directory Directly

If the SDK builds from a rootfs directory:

### 1. Fix APT Sources
```bash
ROOTFS=~/youyeetoo-sdk/<SDK_DIR>/path/to/rootfs

# Comment out bullseye-backports
sudo sed -i 's/^deb.*bullseye-backports/#&/' $ROOTFS/etc/apt/sources.list
```

### 2. Add ffmpeg Static Binary
```bash
# Download on your host
wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz
tar xf ffmpeg-release-arm64-static.tar.xz

# Copy to rootfs
sudo cp ffmpeg-*-arm64-static/ffmpeg $ROOTFS/usr/local/bin/
sudo cp ffmpeg-*-arm64-static/ffprobe $ROOTFS/usr/local/bin/
sudo chmod +x $ROOTFS/usr/local/bin/ffmpeg $ROOTFS/usr/local/bin/ffprobe
```

### 3. Add Docker Configuration
```bash
sudo mkdir -p $ROOTFS/etc/docker
sudo tee $ROOTFS/etc/docker/daemon.json > /dev/null << 'EOF'
{
  "iptables": false,
  "ip6tables": false,
  "bridge": "none"
}
EOF
```

### 4. Add Tailscale Systemd Override
```bash
sudo mkdir -p $ROOTFS/etc/systemd/system/tailscaled.service.d
sudo tee $ROOTFS/etc/systemd/system/tailscaled.service.d/override.conf > /dev/null << 'EOF'
[Service]
ExecStart=
ExecStart=/usr/sbin/tailscaled --state=/var/lib/tailscale/tailscaled.state --socket=/run/tailscale/tailscaled.sock --tun=userspace-networking
EOF
```

### 5. Add RKLLM Runtime Libraries
```bash
RKLLM_REPO=/mnt/c/Users/cyeng/Documents/Projects/stream-sentry-overall/rknn-llm

# Copy RKLLM runtime library
sudo cp $RKLLM_REPO/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so $ROOTFS/usr/lib/

# Copy RKNN runtime library (for vision models)
sudo cp $RKLLM_REPO/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/aarch64/librknnrt.so $ROOTFS/usr/lib/

# Update library cache config
echo "/usr/lib" | sudo tee -a $ROOTFS/etc/ld.so.conf.d/rkllm.conf
```

### 6. Add First-Boot Script for Final Setup
```bash
# Create a first-boot script for things that need network
sudo tee $ROOTFS/usr/local/bin/first-boot-setup.sh > /dev/null << 'EOF'
#!/bin/bash
# First-boot setup - run once after first boot
# Usage: sudo /usr/local/bin/first-boot-setup.sh

set -e

MARKER="/var/lib/first-boot-done"
if [ -f "$MARKER" ]; then
    echo "First boot setup already completed"
    exit 0
fi

echo "=== Running first-boot setup ==="

# Install Tailscale (requires network)
if ! command -v tailscale &> /dev/null; then
    echo "Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
    systemctl daemon-reload
    systemctl enable tailscaled
    systemctl restart tailscaled
fi

# Install Docker (requires network)
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    apt-get update
    apt-get install -y ca-certificates curl
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bullseye stable" > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl daemon-reload
    systemctl enable docker
    systemctl restart docker
fi

# Mark as done
touch "$MARKER"
echo "=== First-boot setup complete ==="
EOF

sudo chmod +x $ROOTFS/usr/local/bin/first-boot-setup.sh
```

---

## Method 2: Chroot into Rootfs (More Powerful)

For installing packages that need `apt`:

```bash
ROOTFS=~/youyeetoo-sdk/<SDK_DIR>/path/to/rootfs

# Set up QEMU for ARM64 emulation
sudo apt install -y qemu-user-static binfmt-support
sudo update-binfmts --enable qemu-aarch64

# Mount necessary filesystems
sudo mount --bind /dev $ROOTFS/dev
sudo mount --bind /dev/pts $ROOTFS/dev/pts
sudo mount --bind /proc $ROOTFS/proc
sudo mount --bind /sys $ROOTFS/sys

# Copy DNS config
sudo cp /etc/resolv.conf $ROOTFS/etc/resolv.conf

# Chroot into rootfs
sudo chroot $ROOTFS /bin/bash

# === Inside chroot (now running as ARM64 via QEMU) ===
apt update
apt install -y build-essential cmake git curl ca-certificates

# Install packages, then exit
exit

# Cleanup mounts
sudo umount $ROOTFS/sys
sudo umount $ROOTFS/proc
sudo umount $ROOTFS/dev/pts
sudo umount $ROOTFS/dev
```

---

## Summary: Recommended Pre-Bake List

1. **APT source fixes** - Direct file edit
2. **ffmpeg static binary** - Copy to `/usr/local/bin/`
3. **Docker daemon.json** - Copy config file
4. **Tailscale systemd override** - Copy config file
5. **RKLLM libraries** - Copy to `/usr/lib/`
6. **build-essential, cmake, git** - Install via chroot
7. **First-boot script** - For network-dependent installs (Docker, Tailscale packages)

This way, after flashing the new image:
1. Boot up
2. Run `sudo /usr/local/bin/first-boot-setup.sh`
3. Run `sudo tailscale up` to authenticate
4. Done!
