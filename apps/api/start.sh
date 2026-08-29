#!/usr/bin/env bash
set -euo pipefail
export PYTHONUNBUFFERED=1
PORT="${PORT:-8080}"

cd /app

echo "Waiting for database to be ready..."
sleep 10

if command -v alembic >/dev/null 2>&1; then
  echo "Running database migrations..."
  alembic upgrade head || echo "Migration failed or none to apply; continuing..."
else
  echo "Alembic not installed; skipping migrations."
fi

echo "Smoke-import the app to expose import-time errors..."
python - <<'PY'
import traceback
try:
    import app.main as m
    print("APP_IMPORT_OK")
except Exception as e:
    print("APP_IMPORT_FAIL:", e)
    traceback.print_exc()
    raise
PY

echo "Starting Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"