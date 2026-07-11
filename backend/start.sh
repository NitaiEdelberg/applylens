#!/usr/bin/env bash
# Run from backend/ so `src` is importable. Binds $PORT (Render/host) or 8000 locally.
cd "$(dirname "$0")" && exec uvicorn src.server:app --host 0.0.0.0 --port "${PORT:-8000}"
