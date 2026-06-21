FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# App code
COPY backend/ ./backend/

EXPOSE 8001

# Copy and make the entrypoint executable — runs migrations before uvicorn.
COPY backend/entrypoint.sh ./backend/entrypoint.sh
RUN chmod +x backend/entrypoint.sh

# Entrypoint runs `alembic upgrade head` then starts uvicorn.
# docker-compose depends_on with service_healthy ensures Postgres is ready.
CMD ["./backend/entrypoint.sh"]
