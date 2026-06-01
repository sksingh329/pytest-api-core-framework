"""
.env file loader and typed environment-variable accessor.

The framework calls :func:`load_env_file` once at session start
(``pytest_configure``), so any values defined in the .env file are
available to ``settings.py``, fixtures, and test code via
:func:`get_env` — or directly through ``os.environ``.

Resolution order (highest → lowest priority)
---------------------------------------------
1. Real environment variables already set in the shell / CI secrets
2. Values loaded from the ``.env`` file  (``override=False`` keeps 1 winning)

Usage in tests
--------------
    from pytest_api_core.config.env_loader import get_env

    def test_protected(api_client):
        token = get_env("BEARER_TOKEN", required=True)
        api_client.get("/me", headers={"Authorization": f"Bearer {token}"})

Usage in settings.py
--------------------
    import os  # .env already loaded by framework before settings are read
    from pytest_api_core.config.base_settings import BaseSettings

    class StagingSettings(BaseSettings):
        base_url = os.environ.get("API_BASE_URL", "https://api.staging.example.com")
        headers  = {"Authorization": f"Bearer {os.environ.get('BEARER_TOKEN', '')}"}
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("pytest_api_core.config")

try:
    from dotenv import load_dotenv as _load_dotenv

    _HAS_DOTENV = True
except ImportError:  # python-dotenv is an optional dependency
    _HAS_DOTENV = False


def load_env_file(path: str | Path = ".env") -> None:
    """
    Load a ``.env`` file into ``os.environ``.

    - Silently skips if the file does not exist.
    - ``override=False`` ensures real shell / CI environment variables always
      take precedence over values defined in the file.
    - Requires ``python-dotenv``; logs a debug message and returns without
      error if the package is not installed.

    Parameters
    ----------
    path:
        Path to the ``.env`` file.  Relative paths are resolved from the
        current working directory (the project root when pytest runs).
    """
    if not _HAS_DOTENV:
        log.debug(
            "python-dotenv is not installed — .env file loading skipped. "
            "Install it with: pip install python-dotenv"
        )
        return

    dotenv_path = Path(path)
    if not dotenv_path.is_file():
        log.debug("No .env file found at '%s' — skipping", dotenv_path.resolve())
        return

    _load_dotenv(dotenv_path=dotenv_path, override=False)
    log.debug("Loaded .env file from '%s'", dotenv_path.resolve())


def get_env(key: str, default: str | None = None, required: bool = False) -> str | None:
    """
    Read a value from ``os.environ`` (which includes any values loaded by
    :func:`load_env_file`).

    Parameters
    ----------
    key:
        Environment variable name (e.g. ``"BEARER_TOKEN"``).
    default:
        Value to return when the variable is not set.
    required:
        When ``True`` and the variable is not set (and no ``default`` is
        given), raise :class:`ValueError` with a descriptive message.

    Returns
    -------
    str or None
        The variable value, or ``default`` if not set.

    Raises
    ------
    ValueError
        If ``required=True`` and the variable is absent with no default.
    """
    value = os.environ.get(key, default)
    if required and value is None:
        raise ValueError(
            f"Required environment variable '{key}' is not set. "
            f"Add it to your .env file or export it in your shell / CI secrets."
        )
    return value
