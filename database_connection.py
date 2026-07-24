"""SQLite configuration and DB-API connection helpers.

The application runs against a local SQLite database file at runtime.  The path
is resolved from ``WLHL_SQLITE_PATH`` (environment, Streamlit secrets, or
``.env``) and defaults to the bundled ``database-init.sqlite`` seed.
"""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from db_compat import iter_statements


ROOT = Path(__file__).resolve().parent
REQUIRED_TABLES = {
    "episodes",
    "episode_enrichment",
    "enrichment_values",
    "episode_terms",
    "episode_topics",
    "topics",
    "quotes",
    "email_ideas",
    "short_hooks",
    "processing_issues",
}


class DatabaseConfigurationError(RuntimeError):
    """Raised when the SQLite database path is absent or does not exist."""


class DatabaseConnectionError(RuntimeError):
    """Raised with a safe, user-facing connection message."""


class DatabaseSchemaError(RuntimeError):
    """Raised when the configured database is not a WLHL database."""


@dataclass(frozen=True)
class SqliteConfig:
    database_path: str


class NamedRow(Sequence):
    """Driver-neutral row supporting both integer and column-name access."""

    __slots__ = ("_values", "_names", "_positions")

    def __init__(self, names, values):
        self._values = tuple(values)
        self._names = tuple(str(name) for name in names)
        self._positions = {name.lower(): index for index, name in enumerate(self._names)}

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                key = self._positions[key.lower()]
            except KeyError as exc:
                raise IndexError(f"No item with that key: {key}") from exc
        return self._values[key]

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self) -> Iterator:
        return iter(self._values)

    def keys(self) -> list[str]:
        return list(self._names)

    def __repr__(self) -> str:
        return f"NamedRow({dict(self)!r})"


class CursorAdapter:
    """Add sqlite3.Row-like results to drivers without row_factory support."""

    def __init__(self, cursor):
        self._cursor = cursor

    def _row(self, row):
        if row is None or isinstance(row, NamedRow):
            return row
        if hasattr(row, "keys"):
            names = list(row.keys())
            return NamedRow(names, [row[name] for name in names])
        description = getattr(self._cursor, "description", None) or ()
        names = [
            column if isinstance(column, str) else getattr(column, "name", None) or column[0]
            for column in description
        ]
        return NamedRow(names, row) if names else row

    def fetchone(self):
        return self._row(self._cursor.fetchone())

    def fetchall(self):
        return [self._row(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        # libsql's native Cursor is not iterable. Its remote implementation is
        # also more consistent when a result set is consumed with fetchall()
        # than through repeated fetchone() calls.
        for row in self._cursor.fetchall():
            yield self._row(row)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class ConnectionAdapter:
    """DB-API facade over sqlite3, kept driver-neutral for test doubles."""

    def __init__(self, connection):
        self.raw_connection = connection

    def execute(self, sql, parameters=None):
        cursor = (
            self.raw_connection.execute(sql)
            if parameters is None
            else self.raw_connection.execute(sql, parameters)
        )
        return CursorAdapter(cursor)

    def executescript(self, script: str):
        # Remote libsql versions may expose executescript while rejecting
        # multi-statement requests. Execute complete statements one by one so
        # the same code works locally and through Turso's remote protocol.
        for statement in iter_statements(script):
            self.execute(statement)

    def commit(self):
        return self.raw_connection.commit()

    def rollback(self):
        return self.raw_connection.rollback()

    def close(self):
        return self.raw_connection.close()

    def __getattr__(self, name):
        return getattr(self.raw_connection, name)


def read_dotenv(path: Path = ROOT / ".env") -> dict[str, str]:
    """Read the simple KEY=VALUE format used by local Docker development."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _streamlit_secrets() -> Mapping[str, Any]:
    try:
        import streamlit as st

        return st.secrets
    except (ImportError, FileNotFoundError, RuntimeError):
        return {}


def _value(name: str, environment: Mapping[str, str], secrets: Mapping[str, Any], dotenv: Mapping[str, str]) -> str:
    """Resolve settings with environment > Streamlit secrets > .env precedence."""
    environment_value = environment.get(name)
    if environment_value:
        return str(environment_value).strip()
    try:
        secret_value = secrets.get(name)
    except Exception:
        secret_value = None
    return str(secret_value or dotenv.get(name) or "").strip()


def get_config(
    *,
    environment: Mapping[str, str] | None = None,
    secrets: Mapping[str, Any] | None = None,
    dotenv_path: Path | None = None,
) -> SqliteConfig:
    environment = os.environ if environment is None else environment
    secrets = _streamlit_secrets() if secrets is None else secrets
    dotenv = read_dotenv(ROOT / ".env" if dotenv_path is None else dotenv_path)
    raw_path = _value("WLHL_SQLITE_PATH", environment, secrets, dotenv)
    path = Path(raw_path).expanduser() if raw_path else ROOT / "database-init.sqlite"
    if not path.is_file():
        raise DatabaseConfigurationError(
            f"SQLite database not found at {path}. Set WLHL_SQLITE_PATH to an existing WLHL database file."
        )
    return SqliteConfig(database_path=str(path))


def safe_connection_message(error: BaseException) -> str:
    """Classify driver errors into safe, user-facing connection messages."""
    text = str(error).lower()
    if any(marker in text for marker in ("no such file", "unable to open", "cannot open", "not found")):
        return "The SQLite database file could not be opened. Check WLHL_SQLITE_PATH."
    if "permission" in text or "readonly" in text or "read-only" in text:
        return "The SQLite database file is not accessible. Check its file permissions."
    if "locked" in text or "busy" in text:
        return "The SQLite database is busy. Try again in a moment."
    if any(marker in text for marker in ("malformed", "not a database", "corrupt", "file is encrypted")):
        return "The SQLite database file is not a valid WLHL database."
    return "The SQLite database connection failed. Check the deployment configuration and try again."


def connect(config: SqliteConfig | None = None):
    """Open a DB-API-compatible connection to the local SQLite database.

    WAL journaling keeps concurrent readers from blocking, and ``busy_timeout``
    makes competing writers wait for the lock instead of raising immediately.
    """
    config = config or get_config()
    try:
        connection = sqlite3.connect(config.database_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        return ConnectionAdapter(connection)
    except Exception as exc:
        raise DatabaseConnectionError(safe_connection_message(exc)) from exc


def validate_schema(connection, required_tables: set[str] | None = None) -> int:
    """Verify connectivity and the runtime schema, returning the episode count."""
    required = REQUIRED_TABLES if required_tables is None else required_tables
    try:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        existing = {row[0] for row in rows}
        missing = sorted(required - existing)
        if missing:
            raise DatabaseSchemaError(
                "The configured database is missing required WLHL tables: " + ", ".join(missing) + "."
            )
        return int(connection.execute("SELECT COUNT(*) FROM episodes").fetchone()[0])
    except DatabaseSchemaError:
        raise
    except Exception as exc:
        raise DatabaseConnectionError(safe_connection_message(exc)) from exc
