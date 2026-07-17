"""Database connection configuration for the Streamlit application.

The production application is intentionally remote-only: data reads and writes go
to Turso rather than to the repository's SQLite snapshot.
"""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st


ROOT = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """Load local development credentials without adding a dotenv dependency."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _setting(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    # Streamlit Community Cloud and other Streamlit deployments commonly use
    # secrets.toml rather than process environment variables.
    try:
        return str(st.secrets.get(name, ""))
    except FileNotFoundError:
        return ""


def connect():
    """Open a DB-API-compatible connection to the configured Turso database."""
    _load_dotenv()
    database_url = _setting("TURSO_DATABASE_URL")
    auth_token = _setting("TURSO_AUTH_TOKEN")
    if not database_url or not auth_token:
        raise RuntimeError(
            "Turso is not configured. Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN "
            "as environment variables or Streamlit secrets."
        )
    if not database_url.startswith(("libsql://", "https://", "http://")):
        raise RuntimeError("TURSO_DATABASE_URL must be a libsql:// or HTTPS Turso URL.")

    try:
        import libsql
    except ImportError as exc:
        raise RuntimeError("The Turso driver is unavailable. Install dependencies from requirements.txt.") from exc

    connection = libsql.connect(database=database_url, auth_token=auth_token)
    # libsql follows sqlite3's DB-API. Setting this keeps the application's
    # existing named-column access (row[\"episode_id\"]) working.
    try:
        import sqlite3
        connection.row_factory = sqlite3.Row
    except (AttributeError, TypeError):
        pass
    return connection
