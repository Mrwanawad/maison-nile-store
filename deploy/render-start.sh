#!/usr/bin/env bash
# Render native Python start: migrations and bootstrap (demo seed / first admin) are idempotent.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD/src/backend"
alembic upgrade head
python -m scripts.bootstrap
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 \
  --proxy-headers --forwarded-allow-ips='*'
