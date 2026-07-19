#!/usr/bin/env python3
"""One-way migration of an explicit local WLHL SQLite database to Turso.

The script uses Turso's HTTP pipeline endpoint, so it has no package dependency.
It intentionally does not print credentials or transcript contents.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_STATEMENTS = 75
MAX_PAYLOAD_BYTES = 750_000
DERIVED_SEARCH_TABLES = {
    "episode_search",
    "enrichment_search",
    "unified_episode_search",
    "unified_search_documents",
    "unified_search_meta",
}


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def pipeline_url(database_url: str) -> str:
    if not database_url.startswith("libsql://"):
        raise ValueError("TURSO_DATABASE_URL must begin with libsql://")
    return "https://" + database_url.removeprefix("libsql://").rstrip("/") + "/v2/pipeline"


def encode_arg(value) -> dict:
    """Encode a Python value as a Hrana (Turso HTTP pipeline) typed value.

    The pipeline endpoint rejects raw JSON scalars with a 400 error; every
    argument must be an internally tagged ``Value`` object. Integers are sent as
    strings (they may exceed JSON's safe range) and blobs as base64.
    """
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "blob", "base64": base64.b64encode(bytes(value)).decode("ascii")}
    return {"type": "text", "value": str(value)}


def request(endpoint: str, token: str, requests: list[dict]) -> list[dict]:
    payload = json.dumps({"requests": requests}, separators=(",", ":")).encode()
    req = urllib.request.Request(
        endpoint,
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip()
        raise RuntimeError(f"Turso rejected the request ({exc.code}): {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Turso: {exc.reason}") from exc
    for item in result.get("results", []):
        if item.get("type") == "error":
            raise RuntimeError(f"Turso rejected a statement: {item.get('error', {}).get('message', item)}")
    return result.get("results", [])


def execute_batch(endpoint: str, token: str, statements: list[tuple[str, list]]) -> None:
    # Each pipeline request is an independent session, so a PRAGMA set in an
    # earlier request does not carry over. Disable foreign keys at the start of
    # every batch: data batches insert tables in name order (children before
    # parents), which would otherwise trip FOREIGN KEY constraints.
    requests = [{"type": "execute", "stmt": {"sql": "PRAGMA foreign_keys=OFF", "args": []}}]
    requests.extend(
        {"type": "execute", "stmt": {"sql": sql, "args": [encode_arg(value) for value in args]}}
        for sql, args in statements
    )
    request(endpoint, token, [*requests, {"type": "close"}])


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def visible_columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in db.execute(f"PRAGMA table_xinfo({qident(table)})") if row[6] == 0]


def chunks(statements: list[tuple[str, list]]):
    batch: list[tuple[str, list]] = []
    size = 0
    for statement in statements:
        statement_size = len(json.dumps(statement, separators=(",", ":")).encode())
        if batch and (len(batch) >= MAX_STATEMENTS or size + statement_size > MAX_PAYLOAD_BYTES):
            yield batch
            batch, size = [], 0
        batch.append(statement)
        size += statement_size
    if batch:
        yield batch


def migration_statements(db: sqlite3.Connection) -> tuple[list[tuple[str, list]], list[tuple[str, list]]]:
    objects = db.execute("""
        SELECT type, name, tbl_name, sql FROM sqlite_master
        WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
        ORDER BY CASE type WHEN 'table' THEN 1 WHEN 'index' THEN 2 WHEN 'trigger' THEN 3 ELSE 4 END, name
    """).fetchall()
    shadow_tables = {row[1] for row in db.execute("PRAGMA table_list") if row[2] == "shadow"}
    excluded = shadow_tables | DERIVED_SEARCH_TABLES
    primary = [
        (kind, name, table, sql)
        for kind, name, table, sql in objects
        if name not in excluded and table not in excluded
    ]
    ddl = [("PRAGMA foreign_keys=OFF", [])]
    ddl.extend((sql, []) for kind, _name, _table, sql in primary if kind == "table")
    data: list[tuple[str, list]] = []
    for kind, table, _owner, _sql in primary:
        if kind != "table":
            continue
        columns = visible_columns(db, table)
        if not columns:
            continue
        names = ", ".join(qident(column) for column in columns)
        placeholders = ", ".join("?" for _ in columns)
        insert_sql = f"INSERT INTO {qident(table)} ({names}) VALUES ({placeholders})"
        for row in db.execute(f"SELECT {names} FROM {qident(table)}"):
            data.append((insert_sql, list(row)))
    ddl.extend((sql, []) for kind, _name, _table, sql in primary if kind in {"index", "trigger"})
    ddl.append(("PRAGMA foreign_keys=ON", []))
    return ddl, data


def validate_source(db: sqlite3.Connection, source: Path) -> int:
    table = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='episodes'"
    ).fetchone()
    if not table:
        raise ValueError(f"Migration source {source.name} does not contain an episodes table.")
    count = int(db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0])
    if count < 1:
        raise ValueError(f"Migration source {source.name} contains no episodes; refusing an empty migration.")
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="Explicit local SQLite source. Runtime never reads this file.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate and count the local migration without contacting Turso.")
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")
    source = args.source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Local migration source not found: {source}")
    with sqlite3.connect(source) as db:
        episode_count = validate_source(db, source)
        ddl, data = migration_statements(db)
    print(
        f"Validated {episode_count} episodes; prepared {len(ddl)} schema statements "
        f"and {len(data)} rows from {source.name}."
    )
    if args.dry_run:
        return 0
    database_url = os.getenv("TURSO_DATABASE_URL", "")
    token = os.getenv("TURSO_AUTH_TOKEN", "")
    if not database_url or not token:
        raise RuntimeError("Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN in .env before a live migration.")
    endpoint = pipeline_url(database_url)
    # HTTP pipeline requests do not share a transaction across requests. Each
    # individual pipeline request is atomic, and batching keeps request bodies
    # comfortably below Turso's HTTP size limit.
    for batch in chunks(ddl):
        execute_batch(endpoint, token, batch)
    for batch in chunks(data):
        execute_batch(endpoint, token, batch)
    print("Migration completed successfully. The local database was not modified.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
