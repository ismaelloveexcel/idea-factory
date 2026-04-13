@echo off
title Idea Factory v4.0
echo.
echo  ========================================
echo    IDEA FACTORY v4.0 - Local Deploy
echo  ========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Download it from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

:: Create venv if missing
if not exist "venv" (
    echo [1/3] Creating virtual environment...
    python -m venv venv
)

:: Activate venv
call venv\Scripts\activate.bat

:: Install deps
echo [2/3] Installing dependencies...
pip install -q -r backend\requirements.txt

:: Check .env
if not exist "backend\.env" (
    echo.
    echo [!] No .env file found. Creating from template...
    copy backend\.env.template backend\.env
    echo.
    echo  *** IMPORTANT ***
    echo  Edit backend\.env and add your API keys before running.
    echo  At minimum you need ANTHROPIC_API_KEY.
    echo  Open backend\.env in Notepad and fill in your keys.
    echo.
    notepad backend\.env
    pause
)

:: Start server
echo [3/3] Starting Idea Factory...
echo.
echo  App running at:  http://localhost:8000
echo  Press Ctrl+C to stop.
echo.
start "" http://localhost:8000
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
pause
