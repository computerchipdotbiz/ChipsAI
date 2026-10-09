#!/bin/bash
set -e

echo "=== Extracting ChipAI Codebase ==="
sudo mkdir -p /opt/chipai
sudo tar -xzf /tmp/chipai_deploy.tar.gz -C /opt/chipai
sudo chown -R $(whoami):$(whoami) /opt/chipai

cd /opt/chipai
echo "=== Setting up Python Virtual Environment ==="
if [ ! -d "/opt/chipai/venv" ]; then
    python3 -m venv /opt/chipai/venv
fi

source /opt/chipai/venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# Install Playwright and browser dependencies
echo "=== Installing Playwright and Chromium on Linux ==="
pip install playwright
playwright install-deps chromium
playwright install chromium

echo "=== Deployment dependencies ready! ==="
python --version
