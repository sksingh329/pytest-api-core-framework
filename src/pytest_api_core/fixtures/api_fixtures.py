"""
Auto-registered pytest fixtures provided by pytest-api-core.

These fixtures are available in every test suite that has the package
installed — no ``conftest.py`` import required.

Fixtures
--------
api_config      (session)  — resolved config dict for the target environment
auth_provider   (session)  — auth strategy passed to APIClient (override this
                              alone to swap auth without redeclaring api_client)
api_client      (session)  — configured APIClient instance, depends on auth_provider
api_bearer_auth (function) — BearerAuth instance (token from cfg or API_TOKEN)
api_basic_auth  (function) — BasicAuth instance (from API_USERNAME / API_PASSWORD)
api_key_auth    (function) — APIKeyAuth instance
"""

from __future__ import annotations

import os
from typing import Any, Generator

import pytest

from pytest_api_core.auth.auth_handlers import APIKeyAuth, BasicAuth, BearerAuth
from pytest_api_core.client.api_client import APIClient
from pytest_api_core.config.config_manager import ConfigManager

# ---------------------------------------------------------------------------
# Config fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def api_config(request: pytest.FixtureRequest) -> dict[str, Any]:
    """
    Returns the fully-resolved configuration dict for the active environment.

    Override via CLI: ``--api-env=staging``
    Override via ini: ``api_env = staging``
    Override via env-var: ``API_ENV=staging``

    Retry policy (``api_retry_total``, ``api_retry_backoff_factor``,
    ``api_retry_methods``) follows the same precedence — env var >
    ``--api-retry-*`` CLI flag > settings class attribute > built-in default.
    """
    env: str | None = (
        request.config.getoption("--api-env", default=None)
        or request.config.getini("api_env")
        or None
    )
    base_url_override: str | None = request.config.getoption("--api-base-url", default=None)
    retry_total_override: int | None = request.config.getoption("--api-retry-total", default=None)
    retry_backoff_override: float | None = request.config.getoption(
        "--api-retry-backoff-factor", default=None
    )
    retry_methods_override: str | None = request.config.getoption(
        "--api-retry-methods", default=None
    )
    settings_module: str | None = request.config.getini("api_settings_module") or None

    cli_overrides: dict[str, Any] = {}
    if base_url_override:
        cli_overrides["base_url"] = base_url_override
    if retry_total_override is not None:
        cli_overrides["api_retry_total"] = retry_total_override
    if retry_backoff_override is not None:
        cli_overrides["api_retry_backoff_factor"] = retry_backoff_override
    if retry_methods_override:
        cli_overrides["api_retry_methods"] = [
            m.strip().upper() for m in retry_methods_override.split(",") if m.strip()
        ]

    manager = ConfigManager(
        env=env,
        cli_overrides=cli_overrides or None,
        settings_module=settings_module,
    )
    return manager.load()


# ---------------------------------------------------------------------------
# Auth provider fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def auth_provider(api_config: dict[str, Any]) -> Any:
    """
    Auth strategy used by ``api_client``, split out so it can be overridden
    on its own — without redeclaring ``api_client`` and re-specifying
    timeout/verify_ssl/base_url/retry just to swap the auth strategy. Most
    ``conftest.py`` auth overrides only need this fixture, e.g.::

        @pytest.fixture(scope="session")
        def auth_provider():
            return BearerAuth(os.environ["BEARER_TOKEN"])

    Defaults to a ``BearerAuth`` built from ``API_TOKEN`` env-var or
    ``api_config["_token"]``, or ``None`` (no auth) if neither is set.
    """
    token = api_config.pop("_token", None) or os.environ.get("API_TOKEN")
    if token:
        return BearerAuth(token)
    return None


# ---------------------------------------------------------------------------
# Client fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def api_client(api_config: dict[str, Any], auth_provider: Any) -> Generator[APIClient, None, None]:
    """
    Session-scoped APIClient built from *api_config* and *auth_provider*.

    To override just the auth strategy, override ``auth_provider`` instead of
    this fixture — see its docstring for an example.
    """
    client = APIClient(
        base_url=api_config["base_url"],
        auth=auth_provider,
        timeout=api_config.get("timeout", 30),
        verify_ssl=api_config.get("verify_ssl", True),
        default_headers=api_config.get("headers"),
        retry_total=api_config.get("api_retry_total", 3),
        retry_backoff_factor=api_config.get("api_retry_backoff_factor", 0.3),
        retry_methods=api_config.get("api_retry_methods", ("GET", "HEAD", "OPTIONS")),
    )
    yield client
    client.close()


# ---------------------------------------------------------------------------
# Auth fixtures (function-scoped so tests can customise per-test)
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_bearer_auth(api_config: dict[str, Any]) -> BearerAuth:
    """
    BearerAuth built from ``API_TOKEN`` env-var or ``api_config["token"]``.
    Raises if no token is available.
    """
    token = os.environ.get("API_TOKEN") or api_config.get("token")
    if not token:
        raise ValueError(
            "api_bearer_auth requires an API token. "
            "Set the API_TOKEN environment variable or add 'token' to your env config."
        )
    return BearerAuth(token)


@pytest.fixture()
def api_basic_auth() -> BasicAuth:
    """
    BasicAuth built from ``API_USERNAME`` / ``API_PASSWORD`` env-vars.
    Raises if either is missing.
    """
    username = os.environ.get("API_USERNAME", "")
    password = os.environ.get("API_PASSWORD", "")
    if not username or not password:
        raise ValueError(
            "api_basic_auth requires API_USERNAME and API_PASSWORD environment variables."
        )
    return BasicAuth(username, password)


@pytest.fixture()
def api_key_auth() -> APIKeyAuth:
    """
    APIKeyAuth built from ``API_KEY_NAME`` / ``API_KEY_VALUE`` / ``API_KEY_LOCATION`` env-vars.
    """
    name = os.environ.get("API_KEY_NAME", "x-api-key")
    value = os.environ.get("API_KEY_VALUE", "")
    location = os.environ.get("API_KEY_LOCATION", "header")
    if not value:
        raise ValueError("api_key_auth requires API_KEY_VALUE environment variable.")
    return APIKeyAuth(name, value, location)
