"""Small compatibility helpers shared by sqlite3 and the libsql DB-API driver."""
from __future__ import annotations

import sqlite3


def execute_script(connection, script: str) -> None:
    """Execute a SQL script even when a DB-API connection lacks executescript."""
    method = getattr(connection, "executescript", None)
    if callable(method):
        method(script)
        return
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            sql = statement.strip()
            if sql:
                connection.execute(sql)
            statement = ""
    if statement.strip():
        connection.execute(statement)


def is_fts_unavailable(error: BaseException) -> bool:
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "fts5", "no such module", "no such table: unified_episode_search", "no such function: bm25",
            "virtual table", "virtual tables", "not supported", "unsupported",
        )
    )


def row_field(row, name: str, position: int):
    """Read named DB-API rows while tolerating drivers that return tuples."""
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return row[position]
