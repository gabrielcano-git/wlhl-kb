"""Small compatibility helpers shared by sqlite3 and the libsql DB-API driver."""
from __future__ import annotations

import sqlite3


def iter_statements(script: str):
    """Yield individual SQL statements from a multi-statement script.

    Splitting on ``;`` boundaries and confirming each candidate with
    :func:`sqlite3.complete_statement` keeps quoted semicolons intact and,
    unlike line-based splitting, separates statements that share one line so
    each is executed on its own (sqlite3 and remote libsql both reject a
    multi-statement ``execute``).
    """
    buffer = ""
    for chunk in script.split(";"):
        buffer += chunk + ";"
        if sqlite3.complete_statement(buffer):
            sql = buffer.strip()
            if sql and sql != ";":
                yield sql
            buffer = ""
    tail = buffer.strip().rstrip(";").strip()
    if tail:
        yield tail


def execute_script(connection, script: str) -> None:
    """Execute a SQL script even when a DB-API connection lacks executescript."""
    method = getattr(connection, "executescript", None)
    if callable(method):
        method(script)
        return
    for statement in iter_statements(script):
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
