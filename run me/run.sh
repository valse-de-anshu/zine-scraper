#!/usr/bin/env bash
# Zine Scraper - Universal Run Script
# This guarantees the scraper always runs inside its virtual environment

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [ ! -d "$ROOT_DIR/venv" ]; then
    echo "[-] Virtual environment not found! Please run install.sh first."
    exit 1
fi

if [ $# -eq 0 ]; then
    echo "[+] Booting Zine Scraper inside isolated VENV..."
fi
exec "$ROOT_DIR/venv/bin/python" "$ROOT_DIR/orchestrator.py" "$@"
