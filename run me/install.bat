@echo off
setlocal

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%\.."

echo [+] Starting Zine Scraper Installation for Windows...

echo [+] Checking for OS dependencies via Winget...
where winget >nul 2>nul
if %errorlevel% neq 0 (
    echo [-] Winget not found! Please install ffmpeg, aria2, and deno manually.
) else (
    echo [+] Installing ffmpeg, aria2, and deno...
    winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    winget install -e --id aria2.aria2 --accept-source-agreements --accept-package-agreements
    winget install -e --id DenoLand.Deno --accept-source-agreements --accept-package-agreements
)

echo [+] Checking for Python...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [-] Error: Python is not installed. Please install Python 3.10+ and add it to your PATH.
    pause
    exit /b 1
)

echo [+] Creating virtual environment...
python -m venv venv

echo [+] Upgrading pip...
call venv\Scripts\python.exe -m pip install --upgrade pip

echo [+] Installing Python dependencies from requirements.txt...
call venv\Scripts\pip.exe install -r requirements.txt

echo [+] Installing Playwright browser binaries...
call venv\Scripts\python.exe -m playwright install chromium

echo [+] Installation complete! Booting the Zine Scraper 1-Time Setup Wizard...
call venv\Scripts\python.exe wizard\setup.py
pause
