#!/bin/zsh
# Run the AltStreet FastAPI backend from any directory.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/backend" || exit 1
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
