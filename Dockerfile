FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WLHL_SQLITE_PATH=/data/wlhl.sqlite

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

# Runtime data lives on a volume mounted here; seeded from database-init.sqlite.
VOLUME ["/data"]

EXPOSE 8501

# Invoked through `sh` so it runs even when a bind mount shadows the exec bit.
ENTRYPOINT ["sh", "docker-entrypoint.sh"]
