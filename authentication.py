"""Authentication configuration and constant-time credential checks."""
from __future__ import annotations

import hmac
import os
from typing import Any, Mapping


class AuthenticationConfigurationError(RuntimeError):
    pass


def configured_credentials(
    *, environment: Mapping[str, str] | None = None, secrets: Mapping[str, Any] | None = None
) -> tuple[str, str]:
    environment = os.environ if environment is None else environment
    secrets = {} if secrets is None else secrets
    env_username = environment.get("WLHL_AUTH_USERNAME", "")
    env_password = environment.get("WLHL_AUTH_PASSWORD", "")
    if env_username and env_password:
        return str(env_username), str(env_password)
    try:
        auth = secrets.get("auth", {}) if hasattr(secrets, "get") else {}
    except Exception:
        auth = {}
    username = str(env_username or auth.get("username") or "")
    password = str(env_password or auth.get("password") or "")
    if not username or not password:
        raise AuthenticationConfigurationError(
            "Login is not configured. Set WLHL_AUTH_USERNAME and WLHL_AUTH_PASSWORD, or [auth] in Streamlit Secrets."
        )
    return username, password


def credentials_match(username: str, password: str, configured_username: str, configured_password: str) -> bool:
    return hmac.compare_digest(username.encode(), configured_username.encode()) and hmac.compare_digest(
        password.encode(), configured_password.encode()
    )
