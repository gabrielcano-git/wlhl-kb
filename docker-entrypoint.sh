#!/bin/sh
# Seed the persistent SQLite database on first boot, then start Streamlit.
#
# WLHL_SQLITE_PATH points at a file on a Docker volume so writes survive
# container rebuilds and `docker compose down`. The bundled database-init.sqlite
# is only used to seed an empty volume; existing data is never overwritten.
set -e

: "${WLHL_SQLITE_PATH:=/data/wlhl.sqlite}"
export WLHL_SQLITE_PATH

if [ ! -f "$WLHL_SQLITE_PATH" ]; then
    echo "Seeding new WLHL database at $WLHL_SQLITE_PATH from database-init.sqlite"
    mkdir -p "$(dirname "$WLHL_SQLITE_PATH")"
    cp /app/database-init.sqlite "$WLHL_SQLITE_PATH"
fi

exec streamlit run app.py --server.address=0.0.0.0 --server.port=8501
