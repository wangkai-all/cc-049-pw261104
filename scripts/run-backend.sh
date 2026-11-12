#!/usr/bin/env bash
# Start the FastAPI + DuckDB backend (serves the built frontend too).
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r backend/requirements.txt
fi
export SAMPLER_DATA_DIR="${SAMPLER_DATA_DIR:-$(pwd)/data}"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend
