#!/bin/bash
set -e

echo "=== Preparing GCP Debian VM for Sarahzine 800 ==="

# 1. Swapfile setup
if [ ! -f /swapfile ]; then
    echo "[1/4] Creating 2GB swapfile..."
    fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo "/swapfile none swap sw 0 0" >> /etc/fstab
    echo "Swap created successfully."
else
    echo "[1/4] Swapfile already exists."
fi

# 2. Update and install system dependencies
echo "[2/4] Updating package repositories and installing base packages..."
apt-get update -y
apt-get install -y git python3-pip python3-venv python3-dev build-essential curl rsync tar

# 3. Create app directory
echo "[3/4] Creating /opt/chipai directory..."
mkdir -p /opt/chipai
chown -R $SUDO_USER:$SUDO_USER /opt/chipai || chown -R $USER:$USER /opt/chipai

echo "[4/4] System packages and directories ready."
free -h
