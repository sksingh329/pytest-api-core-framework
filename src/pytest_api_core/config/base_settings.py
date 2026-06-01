"""
Base class for environment settings.

Consumer projects subclass this, define class-level attributes,
and register them in an ENVIRONMENTS dict.

Example
-------
    from pytest_api_core.config.base_settings import BaseSettings
    import os

    class DevSettings(BaseSettings):
        base_url = "https://api.dev.mycompany.com"
        timeout = 30
        verify_ssl = True
        headers = {"Accept": "application/json"}

    class StagingSettings(DevSettings):      # inherit defaults, override what changes
        base_url = "https://api.staging.mycompany.com"
        timeout = 60

    class ProdSettings(BaseSettings):
        base_url = os.environ.get("API_BASE_URL", "https://api.mycompany.com")
        timeout = 60
        verify_ssl = True

    ENVIRONMENTS = {
        "dev":     DevSettings,
        "staging": StagingSettings,
        "prod":    ProdSettings,
    }
"""
from __future__ import annotations

from typing import Any


class BaseSettings:
    """Base class for environment-specific API settings."""

    base_url: str = "http://localhost"
    timeout: int = 30
    verify_ssl: bool = True
    headers: dict[str, str] = {}

    @classmethod
    def as_dict(cls) -> dict[str, Any]:
        """Return settings as a plain dict, respecting MRO for inheritance."""
        result: dict[str, Any] = {}
        for klass in reversed(cls.__mro__):
            for k, v in vars(klass).items():
                if not k.startswith("_") and not callable(v) and not isinstance(v, (classmethod, staticmethod)):
                    result[k] = v
        return result
