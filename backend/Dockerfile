FROM python:3.12-slim

WORKDIR /app

# Phase 41: stdio MCP servers run npx/uvx inside this container, as uid 10001
# through setpriv (util-linux, already in the base image), never as root. The
# backend itself stays root (no USER line), which is what lets it drop the
# child. Caches live on the monai_ext volume so a cold npx/uvx start (about
# 9.5 s) happens once. The image grows by roughly 200 MB: run `df -h /` first.
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-slim /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /uvx /usr/local/bin/
RUN useradd --system --uid 10001 --no-create-home --home-dir /var/lib/monai-ext monai-ext \
 && mkdir -p /var/lib/monai-ext/home /var/lib/monai-ext/tmp /var/lib/monai-ext/npm \
             /var/lib/monai-ext/uv /var/lib/monai-ext/xdg /var/lib/monai-ext/work \
 && chown -R 10001:10001 /var/lib/monai-ext
ENV MONAI_EXT_HOME=/var/lib/monai-ext

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
