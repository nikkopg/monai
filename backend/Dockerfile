FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# App code
COPY backend/ ./backend/

EXPOSE 8001

# 0.0.0.0 so the port is reachable; host networking is used in compose but this
# keeps the image usable under bridge networking too.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8001"]
