from __future__ import annotations

import sqlite3

import pytest

from scripts.migrate_to_turso import (
    encode_arg,
    execute_batch,
    main,
    migration_statements,
    validate_source,
)


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
    assert "CREATE VIRTUAL TABLE episode_search" not in sql


def test_application_derived_search_tables_are_not_migrated(wlhl_db):
    ddl, data = migration_statements(wlhl_db)
    sql = "\n".join(statement for statement, _args in ddl)
    data_sql = "\n".join(statement for statement, _args in data)
    for table in ("episode_search", "enrichment_search", "unified_episode_search", "unified_search_documents"):
        assert table not in sql
        assert table not in data_sql


def test_encode_arg_emits_typed_hrana_values():
    # Regression: the pipeline endpoint returns HTTP 400 for raw JSON scalars;
    # every argument must be an internally tagged Value object.
    assert encode_arg(None) == {"type": "null"}
    assert encode_arg(True) == {"type": "integer", "value": "1"}
    assert encode_arg(5) == {"type": "integer", "value": "5"}
    assert encode_arg(1.5) == {"type": "float", "value": 1.5}
    assert encode_arg("hi") == {"type": "text", "value": "hi"}
    blob = encode_arg(b"ab")
    assert blob["type"] == "blob" and blob["base64"] == "YWI="


def test_execute_batch_disables_foreign_keys_and_encodes_args(monkeypatch):
    captured = {}

    def fake_request(endpoint, token, requests):
        captured["requests"] = requests
        return []

    monkeypatch.setattr("scripts.migrate_to_turso.request", fake_request)
    execute_batch("https://db/v2/pipeline", "token", [("INSERT INTO t(a,b) VALUES(?,?)", ["hi", 3])])
    requests = captured["requests"]
    # Each pipeline request is an independent session, so every batch must turn
    # foreign keys off itself (children are inserted before their parents).
    assert requests[0]["stmt"]["sql"] == "PRAGMA foreign_keys=OFF"
    assert requests[1]["stmt"]["args"] == [
        {"type": "text", "value": "hi"},
        {"type": "integer", "value": "3"},
    ]
    assert requests[-1] == {"type": "close"}
