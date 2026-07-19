import pytest

from authentication import (
    AuthenticationConfigurationError,
    configured_credentials,
    credentials_match,
)


def test_environment_credentials_take_precedence_over_streamlit_secrets():
    result = configured_credentials(
        environment={"WLHL_AUTH_USERNAME": "env-user", "WLHL_AUTH_PASSWORD": "env-pass"},
        secrets={"auth": {"username": "cloud-user", "password": "cloud-pass"}},
    )
    assert result == ("env-user", "env-pass")


def test_streamlit_auth_shape_and_matching():
    username, password = configured_credentials(
        environment={}, secrets={"auth": {"username": "nick", "password": "strong"}}
    )
    assert credentials_match("nick", "strong", username, password)
    assert not credentials_match("nick", "wrong", username, password)
    assert not credentials_match("wrong", "strong", username, password)


def test_missing_auth_configuration_is_rejected():
    with pytest.raises(AuthenticationConfigurationError):
        configured_credentials(environment={}, secrets={})


def test_missing_streamlit_secrets_file_is_rejected_cleanly():
    class MissingSecrets:
        def get(self, _name, _default=None):
            raise FileNotFoundError("secrets.toml")

    with pytest.raises(AuthenticationConfigurationError):
        configured_credentials(environment={}, secrets=MissingSecrets())


def test_streamlit_cloud_secret_format_supports_database_and_auth(tmp_path):
    secrets = {
        "TURSO_DATABASE_URL": "libsql://cloud",
        "TURSO_AUTH_TOKEN": "token",
        "auth": {"username": "user", "password": "pass"},
    }
    from database_connection import get_config

    assert get_config(environment={}, secrets=secrets, dotenv_path=tmp_path / "missing").database_url == "libsql://cloud"
    assert configured_credentials(environment={}, secrets=secrets) == ("user", "pass")
