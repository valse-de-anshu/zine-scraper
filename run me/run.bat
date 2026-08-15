@echo off
setlocal

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%\.."

if not exist "venv\Scripts\python.exe" (
    echo [-] Virtual environment not found! Please run install.bat first.
    pause
    exit /b 1
)

echo [+] Booting Zine Scraper inside isolated VENV...
"venv\Scripts\python.exe" orchestrator.py
pause
