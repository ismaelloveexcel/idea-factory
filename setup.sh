#!/bin/bash

echo "🏭 Idea Factory — Setup Script"
echo "================================"
echo ""

# Check if .env exists
if [ -f .env ]; then
    echo "✓ .env file already exists"
else
    echo "📝 Creating .env file from template..."
    cp .env.example .env
    echo "⚠️  Please edit .env and add your ANTHROPIC_API_KEY"
    echo ""
fi

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "🐍 Python version: $python_version"

# Create virtual environment
echo ""
echo "📦 Creating virtual environment..."
cd backend
python3 -m venv venv

# Activate and install
echo "📥 Installing dependencies..."
source venv/bin/activate
pip install --quiet -r requirements.txt

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env and add your Claude API key"
echo "2. Run: cd backend && source venv/bin/activate"
echo "3. Run: uvicorn main:app --reload"
echo "4. Open: http://localhost:8000/docs"
echo ""
echo "Or use Docker: docker-compose up"
