#!/bin/sh
# Docker entrypoint: run Alembic migrations before starting the backend server.
# Alembic upgrade head is idempotent — safe to run on every container start.
set -e

echo "[monai] Running database migrations..."
alembic upgrade head
echo "[monai] Starting backend..."
exec uvicorn backend.main:app --host 0.0.0.0 --port 8001
