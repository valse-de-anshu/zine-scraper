#!/usr/bin/env bash
# Zine Scraper - Universal Run Script
# This guarantees the scraper always runs inside its virtual environment

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [ ! -d "$ROOT_DIR/venv" ]; then
    echo "[-] Virtual environment not found! Please run install.sh first."
    exit 1
fi

echo "[+] Booting Zine Scraper inside isolated VENV..."
"$ROOT_DIR/venv/bin/python" "$ROOT_DIR/orchestrator.py"
