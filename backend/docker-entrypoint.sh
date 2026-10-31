#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head

if [ "${SEED_DEMO_DATA:-true}" = "true" ]; then
  # Loads the synthetic dataset unless it is already present
  # A demo-data problem should not stop the API from serving
  python -m app.ingestion load datasets/synthetic || echo "WARNING: synthetic dataset was not loaded (see error above)"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
