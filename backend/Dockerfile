FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# App code
COPY backend/ ./backend/

# Alembic config + migrations live at the repo root, not inside backend/.
# entrypoint.sh runs `alembic upgrade head` from WORKDIR /app, and
# alembic.ini declares `script_location = alembic` (relative to CWD), so
# both must land at /app/alembic.ini and /app/alembic/.
COPY alembic.ini ./alembic.ini
COPY alembic/ ./alembic/

EXPOSE 8001

# Copy and make the entrypoint executable — runs migrations before uvicorn.
COPY backend/entrypoint.sh ./backend/entrypoint.sh
RUN chmod +x backend/entrypoint.sh

# Entrypoint runs `alembic upgrade head` then starts uvicorn.
# docker-compose depends_on with service_healthy ensures Postgres is ready.
CMD ["./backend/entrypoint.sh"]
