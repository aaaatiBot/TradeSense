@echo off
title TradeSense Desktop App
echo =========================================================
echo       Starting TradeSense Platform (Desktop Edition)
echo =========================================================

cd /d "%~dp0"

:: Check if virtual environment exists
if not exist ".venv\Scripts\python.exe" (
    echo [*] Setting up Python virtual environment...
    python -m venv .venv
    echo [*] Installing required dependencies...
    .venv\Scripts\pip install -r requirements.txt
)

:: Run database setup
echo [*] Checking database migrations...
.venv\Scripts\python -c "from app import create_app; from app.extensions import db; from app.services.disclaimer_service import DisclaimerService; app = create_app('development'); app.app_context().push(); db.create_all(); DisclaimerService.seed_disclaimers()"

:: Launch application
echo [*] Launching TradeSense...
.venv\Scripts\python desktop.py

pause
