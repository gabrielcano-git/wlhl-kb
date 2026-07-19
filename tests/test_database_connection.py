from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from database_connection import (
    ConnectionAdapter,
    DatabaseConfigurationError,
    DatabaseConnectionError,
    DatabaseSchemaError,
    TursoConfig,
    connect,
    get_config,
    safe_connection_message,
    validate_schema,
)


def test_config_precedence_and_dotenv(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("TURSO_DATABASE_URL=libsql://dotenv\nTURSO_AUTH_TOKEN=dotenv-token\n")
    config = get_config(
        environment={"TURSO_DATABASE_URL": "libsql://environment"},
        secrets={"TURSO_DATABASE_URL": "libsql://secret", "TURSO_AUTH_TOKEN": "secret-token"},
        dotenv_path=dotenv,
    )
    assert config.database_url == "libsql://environment"
    assert config.auth_token == "secret-token"


def test_config_reads_dotenv_when_other_sources_are_empty(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text('TURSO_DATABASE_URL="libsql://dotenv"\nTURSO_AUTH_TOKEN="token"\n')
    assert get_config(environment={}, secrets={}, dotenv_path=dotenv) == TursoConfig("libsql://dotenv", "token")


def test_missing_streamlit_secrets_file_becomes_clear_configuration_error(tmp_path):
    class MissingSecrets:
        def get(self, _name, _default=None):
            raise FileNotFoundError("secrets.toml")

    with pytest.raises(DatabaseConfigurationError, match="TURSO_DATABASE_URL"):
        get_config(environment={}, secrets=MissingSecrets(), dotenv_path=tmp_path / "missing")


@pytest.mark.parametrize(
    "environment",
    [{}, {"TURSO_DATABASE_URL": "file:local.sqlite", "TURSO_AUTH_TOKEN": "token"}],
)
def test_invalid_or_missing_config_is_rejected(environment, tmp_path):
    with pytest.raises(DatabaseConfigurationError):
        get_config(environment=environment, secrets={}, dotenv_path=tmp_path / "missing")


def test_connect_passes_driver_arguments_and_wraps_connection(monkeypatch):
    fake_connection = SimpleNamespace()
    calls = {}

    def fake_connect(**kwargs):
        calls.update(kwargs)
        return fake_connection

    monkeypatch.setitem(sys.modules, "libsql", SimpleNamespace(connect=fake_connect))
    result = connect(TursoConfig("libsql://example", "private-token"))
    assert isinstance(result, ConnectionAdapter)
    assert result.raw_connection is fake_connection
    assert calls == {"database": "libsql://example", "auth_token": "private-token"}


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

        def __iter__(self):
            return iter(self.rows)

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


def test_connect_import_error_is_controlled(monkeypatch):
    monkeypatch.delitem(sys.modules, "libsql", raising=False)
    monkeypatch.setattr("database_connection.importlib.import_module", lambda _name: (_ for _ in ()).throw(ImportError()))
    with pytest.raises(DatabaseConfigurationError, match="driver"):
        connect(TursoConfig("libsql://example", "secret"))


def test_driver_error_never_leaks_url_or_token(monkeypatch):
    secret = "do-not-leak"
    url = "libsql://private-host"
    driver = SimpleNamespace(connect=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError(f"401 {secret} {url}")))
    monkeypatch.setitem(sys.modules, "libsql", driver)
    with pytest.raises(DatabaseConnectionError) as caught:
        connect(TursoConfig(url, secret))
    assert secret not in str(caught.value)
    assert url not in str(caught.value)
    assert "credentials" in str(caught.value)


def test_safe_network_message_does_not_echo_original_error():
    message = safe_connection_message(RuntimeError("network timeout at libsql://secret"))
    assert "unreachable" in message
    assert "secret" not in message


def test_connection_attribute_error_is_not_misreported_as_network_failure():
    message = safe_connection_message(AttributeError("libsql.Connection has no attribute row_factory"))
    assert "temporarily unreachable" not in message
    assert "connection failed" in message


def test_validate_schema_reports_missing_tables_without_credentials(wlhl_db):
    assert validate_schema(wlhl_db) == 127
    wlhl_db.execute("DROP TABLE quotes")
    with pytest.raises(DatabaseSchemaError, match="quotes"):
        validate_schema(wlhl_db)
