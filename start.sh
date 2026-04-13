#!/usr/bin/env bash
set -e

echo ""
echo "  ========================================"
echo "    IDEA FACTORY v4.0 - Local Deploy"
echo "  ========================================"
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python 3 is not installed."
    echo "  macOS:  brew install python3"
    echo "  Linux:  sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

# Create venv if missing
if [ ! -d "venv" ]; then
    echo "[1/3] Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install deps
echo "[2/3] Installing dependencies..."
pip install -q -r backend/requirements.txt

# Check .env
if [ ! -f "backend/.env" ]; then
    echo ""
    echo "[!] No .env file found. Creating from template..."
    cp backend/.env.template backend/.env
    echo ""
    echo "  *** IMPORTANT ***"
    echo "  Edit backend/.env and add your API keys before running."
    echo "  At minimum you need ANTHROPIC_API_KEY."
    echo ""
    echo "  Run:  nano backend/.env   (or open in any text editor)"
    echo ""
    exit 1
fi

# Start server
echo "[3/3] Starting Idea Factory..."
echo ""
echo "  App running at:  http://localhost:8000"
echo "  Press Ctrl+C to stop."
echo ""

# Try to open browser
if command -v open &>/dev/null; then
    open http://localhost:8000 &
elif command -v xdg-open &>/dev/null; then
    xdg-open http://localhost:8000 &
fi

cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
