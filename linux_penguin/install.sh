#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "[1/5] Installing Linux packages..."
sudo apt update
sudo apt install -y usbmuxd libimobiledevice-utils python3 python3-venv python3-pip

echo "[2/5] Restarting usbmuxd..."
if command -v service >/dev/null 2>&1; then
  sudo service usbmuxd restart || true
else
  echo "service command not available in this Crostini image; continuing."
fi

echo "[3/5] Creating Python environment..."
python3 -m venv tetherloc-env
source tetherloc-env/bin/activate

echo "[4/5] Installing Python packages..."
python -m pip install -U pip
python -m pip install -r requirements.txt

echo
echo "[5/5] Installed. Plug in and trust the iPhone, then run:"
echo "  bash run.sh devices"
