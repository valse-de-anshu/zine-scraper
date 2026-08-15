#!/usr/bin/env bash

# Zine Scraper Suite - Setup Script
# This script sets up the Python virtual environment, installs OS dependencies (ffmpeg, etc.), and installs Python packages.

set -e

echo "[+] Starting Zine Scraper Installation..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

# Handle permissions (Docker runs as root and might not have sudo)
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

# Install OS Dependencies
echo "[+] Checking for OS dependencies (ffmpeg, aria2, atomicparsley, curl, unzip)..."
if command -v brew &> /dev/null; then
    echo "[+] macOS (Homebrew) detected. Installing system packages..."
    brew install ffmpeg aria2 atomicparsley curl unzip
elif command -v apt-get &> /dev/null; then
    echo "[+] Debian/Ubuntu detected. Installing system packages..."
    $SUDO apt-get update
    $SUDO apt-get install -y ffmpeg aria2 atomicparsley python3-venv curl unzip
elif command -v pacman &> /dev/null; then
    echo "[+] Arch Linux detected. Installing system packages..."
    $SUDO pacman -Sy --noconfirm ffmpeg aria2 atomicparsley curl unzip
elif command -v dnf &> /dev/null; then
    echo "[+] Fedora/RHEL detected. Installing system packages..."
    $SUDO dnf install -y ffmpeg aria2 atomicparsley curl unzip
elif command -v zypper &> /dev/null; then
    echo "[+] openSUSE detected. Installing system packages..."
    $SUDO zypper install -y ffmpeg aria2 atomicparsley curl unzip python3-venv
elif command -v apk &> /dev/null; then
    echo "[+] Alpine Linux detected. Installing system packages..."
    $SUDO apk add ffmpeg aria2 atomicparsley curl unzip python3
else
    echo "[-] Warning: Could not detect package manager. Please manually install ffmpeg, aria2, atomicparsley, curl, and unzip."
fi

# Install Deno (Required for Hanime.tv Javascript Decryption)
echo "[+] Checking for Deno (Javascript Runtime)..."
if ! command -v deno &> /dev/null; then
    echo "[+] Installing Deno..."
    curl -fsSL https://deno.land/install.sh | sh -s -- -y
    export PATH="$HOME/.deno/bin:$PATH"
    echo 'export PATH="$HOME/.deno/bin:$PATH"' >> ~/.bashrc
else
    echo "[+] Deno is already installed."
fi

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "[-] Error: python3 is not installed."
    exit 1
fi

echo "[+] Creating virtual environment..."
rm -rf venv
python3 -m venv venv

echo "[+] Activating virtual environment..."
source venv/bin/activate

echo "[+] Upgrading pip..."
pip install --upgrade pip

echo "[+] Installing Python dependencies from requirements.txt..."
pip install -r requirements.txt

echo "[+] Installing Playwright browser binaries..."
python -m playwright install chromium

echo "[+] Installation complete! Booting the Zine Scraper 1-Time Setup Wizard..."
"$ROOT_DIR/venv/bin/python" "$ROOT_DIR/wizard/setup.py"
