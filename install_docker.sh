#!/bin/bash
set -e

echo "=== Cleaning up broken Docker repos ==="
sudo rm -f /etc/apt/sources.list.d/docker.list
sudo rm -f /etc/apt/sources.list.d/download_docker_com_linux_ubuntu.list 2>/dev/null
sudo rm -f /etc/apt/keyrings/docker.gpg 2>/dev/null

echo "=== Installing prerequisites ==="
sudo apt-get update
sudo apt-get install -y ca-certificates curl

echo "=== Adding Docker GPG key ==="
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "=== Adding Docker repository (Debian Bullseye ARM64) ==="
echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bullseye stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

echo "=== Updating package lists ==="
sudo apt-get update

echo "=== Installing Docker ==="
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "=== Adding user to docker group ==="
sudo usermod -aG docker $USER

echo "=== Starting Docker ==="
sudo systemctl enable docker
sudo systemctl start docker

echo ""
echo "=== Docker installed successfully! ==="
echo "Log out and back in for group changes to take effect."
echo "Test with: sudo docker run hello-world"
