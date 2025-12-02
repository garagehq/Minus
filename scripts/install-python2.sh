#!/bin/bash
# Install Python 2.7 on Ubuntu 24.04 (Noble) which removed Python 2
# Required for Rockchip SDK u-boot compilation

set -e

echo "=== Installing Python 2.7 from Ubuntu 22.04 packages ==="

cd /tmp

# Download packages
wget -q http://archive.ubuntu.com/ubuntu/pool/universe/p/python2.7/libpython2.7-minimal_2.7.18-13ubuntu1_amd64.deb
wget -q http://archive.ubuntu.com/ubuntu/pool/universe/p/python2.7/libpython2.7-stdlib_2.7.18-13ubuntu1_amd64.deb
wget -q http://archive.ubuntu.com/ubuntu/pool/universe/p/python2.7/python2.7-minimal_2.7.18-13ubuntu1_amd64.deb
wget -q http://archive.ubuntu.com/ubuntu/pool/universe/p/python2.7/python2.7_2.7.18-13ubuntu1_amd64.deb

# Install in dependency order
sudo dpkg -i libpython2.7-minimal_2.7.18-13ubuntu1_amd64.deb
sudo dpkg -i libpython2.7-stdlib_2.7.18-13ubuntu1_amd64.deb
sudo dpkg -i python2.7-minimal_2.7.18-13ubuntu1_amd64.deb
sudo dpkg -i python2.7_2.7.18-13ubuntu1_amd64.deb

# Create python2 symlink
sudo ln -sf /usr/bin/python2.7 /usr/bin/python2

# Cleanup
rm -f /tmp/libpython2.7-*.deb /tmp/python2.7*.deb

echo "=== Python 2.7 installed ==="
python2 --version
