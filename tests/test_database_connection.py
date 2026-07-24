from __future__ import annotations

from pathlib import Path

import pytest

from database_connection import (
    ROOT,
    ConnectionAdapter,
    DatabaseConfigurationError,
    DatabaseSchemaError,
    SqliteConfig,
    connect,
    get_config,
    safe_connection_message,
    validate_schema,
)


def _touch(path: Path) -> Path:
    path.write_bytes(b"")
    return path


def test_config_precedence_prefers_environment_then_secrets_then_dotenv(tmp_path):
    env_db = _touch(tmp_path / "env.sqlite")
    secret_db = _touch(tmp_path / "secret.sqlite")
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"WLHL_SQLITE_PATH={_touch(tmp_path / 'dotenv.sqlite')}\n")

    config = get_config(
        environment={"WLHL_SQLITE_PATH": str(env_db)},
        secrets={"WLHL_SQLITE_PATH": str(secret_db)},
        dotenv_path=dotenv,
    )
    assert config == SqliteConfig(database_path=str(env_db))


def test_config_reads_dotenv_when_other_sources_are_empty(tmp_path):
    db = _touch(tmp_path / "dotenv.sqlite")
    dotenv = tmp_path / ".env"
    dotenv.write_text(f'WLHL_SQLITE_PATH="{db}"\n')
    assert get_config(environment={}, secrets={}, dotenv_path=dotenv) == SqliteConfig(str(db))


def test_config_defaults_to_bundled_seed_when_unset(tmp_path):
    config = get_config(environment={}, secrets={}, dotenv_path=tmp_path / "missing")
    assert config.database_path == str(ROOT / "database-init.sqlite")


def test_config_rejects_a_path_that_does_not_exist(tmp_path):
    with pytest.raises(DatabaseConfigurationError, match="WLHL_SQLITE_PATH"):
        get_config(
            environment={"WLHL_SQLITE_PATH": str(tmp_path / "nope.sqlite")},
            secrets={},
            dotenv_path=tmp_path / "missing",
        )


def test_connect_opens_sqlite_with_wal_and_named_rows(wlhl_db, tmp_path):
    # wlhl_db already seeded a database file; reuse its path through connect().
    database_file = wlhl_db.execute("PRAGMA database_list").fetchone()["file"]
    connection = connect(SqliteConfig(database_file))
    try:
        assert isinstance(connection, ConnectionAdapter)
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        row = connection.execute(
            "SELECT episode_id, episode_title FROM episodes ORDER BY id LIMIT 1"
        ).fetchone()
        assert row["episode_id"] and row["episode_title"]
    finally:
        connection.close()


def test_connection_adapter_named_rows_commit_rollback_and_close():
    class Cursor:
        description = (("episode_id", None), ("episode_title", None))
        lastrowid = 9

        def __init__(self):
            self.rows = [("EP-001", "First")]

        def fetchone(self):
            return self.rows.pop(0) if self.rows else None

        def fetchall(self):
            rows, self.rows = self.rows, []
            return rows

    class RawConnection:
        def __init__(self):
            self.calls = []

        def execute(self, sql, parameters=None):
            self.calls.append((sql, parameters))
            return Cursor()

        def commit(self): self.calls.append("commit")
        def rollback(self): self.calls.append("rollback")
        def close(self): self.calls.append("close")

    raw = RawConnection()
    connection = ConnectionAdapter(raw)
    row = connection.execute("SELECT episode_id,episode_title FROM episodes").fetchone()
    assert row[0] == row["episode_id"] == "EP-001"
    assert row["EPISODE_TITLE"] == "First"
    assert row.keys() == ["episode_id", "episode_title"]
    assert dict(row) == {"episode_id": "EP-001", "episode_title": "First"}
    connection.commit(); connection.rollback(); connection.close()
    assert raw.calls[-3:] == ["commit", "rollback", "close"]


def test_connection_adapter_iterates_a_non_iterable_cursor():
    class NativeCursor:
        description = (("name", None),)

        def __init__(self):
            self.rows = [("episodes",), ("quotes",)]

        def fetchone(self):
            return self.rows.pop(0) if self.rows else None

        def fetchall(self):
            rows, self.rows = self.rows, []
            return rows

    class NativeConnection:
        def execute(self, _sql):
            return NativeCursor()

    rows = list(ConnectionAdapter(NativeConnection()).execute("PRAGMA table_list"))
    assert [row["name"] for row in rows] == ["episodes", "quotes"]


def test_safe_message_for_missing_file_points_at_the_setting():
    message = safe_connection_message(Exception("unable to open database file"))
    assert "WLHL_SQLITE_PATH" in message


def test_safe_message_for_locked_database_suggests_retry():
    assert "busy" in safe_connection_message(Exception("database is locked")).lower()


def test_safe_message_for_corruption_reports_invalid_database():
    assert "not a valid" in safe_connection_message(Exception("file is not a database"))


def test_validate_schema_reports_missing_tables(wlhl_db):
    assert validate_schema(wlhl_db) == 127
    wlhl_db.execute("DROP TABLE quotes")
    with pytest.raises(DatabaseSchemaError, match="quotes"):
        validate_schema(wlhl_db)
