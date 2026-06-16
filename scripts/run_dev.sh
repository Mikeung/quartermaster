#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

if [ ! -f ".env" ]; then
    echo "No .env found — copying from .env.example"
    cp .env.example .env
fi

echo "Starting Quartermaster (dev mode)..."
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
