#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head

if [ "${DEMO_RESET_ON_START:-false}" = "true" ]; then
  # Public demo: every start (free hosting wakes from sleep) begins with fresh demo data
  echo "Resetting demo data..."
  python -m app.ingestion reset --yes
fi

if [ "${SEED_DEMO_DATA:-true}" = "true" ]; then
  # Loads the synthetic dataset unless it is already present.
  # A demo-data problem should not stop the API from serving.
  python -m app.ingestion load datasets/synthetic || echo "WARNING: synthetic dataset was not loaded (see error above)"
fi

# Hosting platforms (Render, Railway, ...) tell the app which port to use
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
