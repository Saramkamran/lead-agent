#!/bin/bash
set -e

echo "Setting up backend..."
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..

echo "Setting up frontend..."
cd frontend
npm install
cd ..

echo "Copying env file..."
cp .env.example .env

echo ""
echo "Done. Fill in .env then run:"
echo "  cd backend && alembic upgrade head"
echo "  cd backend && uvicorn main:app --reload --port 8000"
echo "  cd frontend && npm run dev"
