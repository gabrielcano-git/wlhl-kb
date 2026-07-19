from __future__ import annotations

import sqlite3

import pytest

from scripts.migrate_to_turso import main, migration_statements, validate_source


def make_source(path, episodes=True, row=True):
    connection = sqlite3.connect(path)
    if episodes:
        connection.execute("CREATE TABLE episodes(id INTEGER PRIMARY KEY, title TEXT)")
        if row:
            connection.execute("INSERT INTO episodes(title) VALUES('one')")
    connection.commit()
    return connection


def test_valid_source_dry_run_does_not_require_credentials(tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite"
    make_source(source).close()
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr("scripts.migrate_to_turso.ROOT", tmp_path)
    assert main(["--source", str(source), "--dry-run"]) == 0


def test_source_without_episodes_or_with_zero_episodes_is_rejected(tmp_path):
    missing = tmp_path / "missing.sqlite"
    with make_source(missing, episodes=False) as connection:
        with pytest.raises(ValueError, match="episodes table"):
            validate_source(connection, missing)
    empty = tmp_path / "empty.sqlite"
    with make_source(empty, row=False) as connection:
        with pytest.raises(ValueError, match="no episodes"):
            validate_source(connection, empty)


def test_live_migration_requires_credentials(tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite"
    make_source(source).close()
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr("scripts.migrate_to_turso.ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="TURSO_DATABASE_URL"):
        main(["--source", str(source)])


def test_fts_shadow_tables_are_filtered(tmp_path):
    source = tmp_path / "fts.sqlite"
    with make_source(source) as connection:
        try:
            connection.execute("CREATE VIRTUAL TABLE episode_search USING fts5(body)")
        except sqlite3.OperationalError:
            pytest.skip("SQLite build lacks FTS5")
        ddl, _data = migration_statements(connection)
    sql = "\n".join(item[0] for item in ddl)
    assert "episode_search_data" not in sql
    assert "episode_search_idx" not in sql
