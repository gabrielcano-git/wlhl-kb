from __future__ import annotations

import sqlite3

from db_compat import execute_script, iter_statements, row_field


def test_iter_statements_splits_statements_that_share_one_line():
    # Regression: line-based splitting passed a whole multi-statement line to a
    # single execute(), which sqlite3 and remote libsql both reject.
    script = "CREATE TABLE a(id INTEGER); INSERT INTO a VALUES(1);"
    assert list(iter_statements(script)) == [
        "CREATE TABLE a(id INTEGER);",
        "INSERT INTO a VALUES(1);",
    ]


def test_iter_statements_keeps_quoted_semicolons_intact():
    script = "INSERT INTO t VALUES('a;b'); SELECT 1"
    assert list(iter_statements(script)) == ["INSERT INTO t VALUES('a;b');", "SELECT 1;"]


def test_execute_script_runs_one_complete_statement_per_execute():
    calls: list[str] = []

    class OnlyExecute:
        def execute(self, sql, params=()):
            calls.append(sql)

    execute_script(OnlyExecute(), "CREATE TABLE a(id INTEGER); INSERT INTO a VALUES(1);")
    assert calls == ["CREATE TABLE a(id INTEGER);", "INSERT INTO a VALUES(1);"]
    assert all(sqlite3.complete_statement(sql) for sql in calls)


def test_execute_script_uses_native_executescript_when_available():
    connection = sqlite3.connect(":memory:")
    try:
        execute_script(connection, "CREATE TABLE a(id INTEGER); INSERT INTO a VALUES(7);")
        assert connection.execute("SELECT id FROM a").fetchone()[0] == 7
    finally:
        connection.close()


def test_row_field_reads_by_name_then_falls_back_to_position():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        named = connection.execute("SELECT 5 AS name").fetchone()
        assert row_field(named, "name", 0) == 5
    finally:
        connection.close()
    assert row_field((11, 22), "missing", 1) == 22
