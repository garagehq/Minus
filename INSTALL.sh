#!/bin/bash
# INSTALL.sh - Setup script for Youyeetoo R1 (Rockchip) Debian Bullseye
# This script addresses kernel limitations (no iptables/netfilter/bridge support)
set -e

echo "=============================================="
echo "Youyeetoo R1 Debian Bullseye Setup Script"
echo "=============================================="

# ------------------------------------------
# 1. Fix APT sources (bullseye-backports EOL)
# ------------------------------------------
echo ""
echo "=== Fixing APT sources ==="
# Comment out bullseye-backports if present (EOL, no longer available)
if grep -q "bullseye-backports" /etc/apt/sources.list 2>/dev/null; then
    sudo sed -i 's/^deb.*bullseye-backports/#&/' /etc/apt/sources.list
    echo "Commented out bullseye-backports in sources.list"
fi

# Remove any bullseye-backports files in sources.list.d
for f in /etc/apt/sources.list.d/*backports*; do
    if [ -f "$f" ]; then
        sudo rm -f "$f"
        echo "Removed $f"
    fi
done

sudo apt update

# ------------------------------------------
# 2. Unhold packages needed for upgrades
# ------------------------------------------
echo ""
echo "=== Unholding ffmpeg-related packages ==="
sudo apt-mark unhold \
    libavcodec58 libavcodec-dev \
    libavformat58 libavformat-dev \
    libavutil56 libavutil-dev \
    libavfilter7 \
    libavresample4 \
    libpostproc55 \
    libswresample3 libswresample-dev \
    libswscale5 libswscale-dev \
    libwebp6 libwebpmux3 libwebpdemux2 \
    2>/dev/null || true

# ------------------------------------------
# 3. Install ffmpeg (static binary - safest for vendor systems)
# ------------------------------------------
echo ""
echo "=== Installing ffmpeg (static binary) ==="
cd /tmp
if [ ! -f /usr/local/bin/ffmpeg ]; then
    wget -q https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz
    tar xf ffmpeg-release-arm64-static.tar.xz
    sudo cp ffmpeg-*-arm64-static/ffmpeg /usr/local/bin/
    sudo cp ffmpeg-*-arm64-static/ffprobe /usr/local/bin/
    rm -rf ffmpeg-*-arm64-static*
    echo "ffmpeg installed to /usr/local/bin/"
else
    echo "ffmpeg already installed"
fi

# ------------------------------------------
# 4. Install and configure Tailscale
# ------------------------------------------
echo ""
echo "=== Installing Tailscale ==="
curl -fsSL https://tailscale.com/install.sh | sh

# Configure Tailscale for userspace networking (kernel lacks TUN/iptables)
echo "Configuring Tailscale for userspace networking..."
sudo mkdir -p /etc/systemd/system/tailscaled.service.d
sudo tee /etc/systemd/system/tailscaled.service.d/override.conf > /dev/null << 'EOF'
[Service]
ExecStart=
ExecStart=/usr/sbin/tailscaled --state=/var/lib/tailscale/tailscaled.state --socket=/run/tailscale/tailscaled.sock --tun=userspace-networking
EOF

sudo systemctl daemon-reload
sudo systemctl enable tailscaled
sudo systemctl restart tailscaled

echo "Tailscale installed. Run 'sudo tailscale up' to authenticate."

# ------------------------------------------
# 5. Install and configure Docker
# ------------------------------------------
echo ""
echo "=== Installing Docker ==="

# Clean up any broken Docker repos
sudo rm -f /etc/apt/sources.list.d/docker.list
sudo rm -f /etc/apt/sources.list.d/*docker* 2>/dev/null || true
sudo rm -f /etc/apt/keyrings/docker.gpg 2>/dev/null || true

# Install prerequisites
sudo apt-get install -y ca-certificates curl

# Add Docker GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository (Debian Bullseye ARM64)
echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bullseye stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Configure Docker for limited kernel (no iptables, no bridge)
echo "Configuring Docker for kernel without iptables/bridge support..."
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json > /dev/null << 'EOF'
{
  "iptables": false,
  "ip6tables": false,
  "bridge": "none"
}
EOF

# Add current user to docker group
sudo usermod -aG docker $USER

# Start Docker
sudo systemctl daemon-reload
sudo systemctl enable docker
sudo systemctl restart docker

echo ""
echo "=============================================="
echo "Installation complete!"
echo "=============================================="
echo ""
echo "IMPORTANT NOTES:"
echo "1. Log out and back in for docker group changes"
echo "2. Run 'sudo tailscale up' to connect to Tailscale"
echo "3. Docker containers MUST use '--network host' mode"
echo "   Example: docker run --network host your-image"
echo ""
