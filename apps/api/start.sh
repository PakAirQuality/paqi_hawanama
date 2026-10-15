#!/usr/bin/env bash
set -euo pipefail
export PYTHONUNBUFFERED=1
PORT="${PORT:-8080}"

cd /app

if command -v alembic >/dev/null 2>&1; then
  echo "Running database migrations..."
  alembic upgrade head || echo "Migration failed or none to apply; continuing..."
else
  echo "Alembic not installed; skipping migrations."
fi

# Provenance is asserted at image build time (Dockerfile) and import errors surface
# when uvicorn imports the app, so there is no separate smoke import here: it doubled
# the startup time of every new instance.

echo "Starting Uvicorn..."
# --proxy-headers: honour X-Forwarded-Proto from Cloud Run so redirects stay https://
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --proxy-headers --forwarded-allow-ips="*"