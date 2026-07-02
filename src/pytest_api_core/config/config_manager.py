"""
Environment-aware configuration manager.

Resolution order (highest → lowest priority):
  1. Environment variables  (API_BASE_URL, API_TOKEN, …)
  2. ``--api-base-url`` CLI flag
  3. settings.py  ENVIRONMENTS[env].as_dict()
  4. Built-in defaults

Usage
-----
    manager = ConfigManager(env="staging", settings_module="config.settings")
    cfg = manager.load()
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import Any

log = logging.getLogger("pytest_api_core.config")

_DEFAULTS: dict[str, Any] = {
    "base_url": "http://localhost",
    "timeout": 30,
    "verify_ssl": True,
    "headers": {},
    # Retry policy applied by APIClient — see api_retry_* below for how to
    # override these via settings.py / CLI flags / env vars.
    "api_retry_total": 3,
    "api_retry_backoff_factor": 0.3,
    "api_retry_methods": ["GET", "HEAD", "OPTIONS"],
}

# Maps env-var names → config keys
_ENV_VAR_MAP: dict[str, str] = {
    "API_BASE_URL": "base_url",
    "API_TIMEOUT": "timeout",
    "API_VERIFY_SSL": "verify_ssl",
    "API_TOKEN": "_token",  # consumed by fixtures, not stored in cfg directly
    "API_RETRY_TOTAL": "api_retry_total",
    "API_RETRY_BACKOFF_FACTOR": "api_retry_backoff_factor",
    "API_RETRY_METHODS": "api_retry_methods",
}


class ConfigManager:
    """
    Loads and merges configuration for a given environment name.

    Parameters
    ----------
    env:
        Environment label (e.g. ``"dev"``, ``"staging"``).
    cli_overrides:
        Extra key/value pairs from CLI options (e.g. ``--api-base-url``).
    settings_module:
        Dotted import path to a Python module that contains an
        ``ENVIRONMENTS`` dict mapping env names to ``BaseSettings``
        subclasses (e.g. ``"config.settings"``).
    """

    def __init__(
        self,
        env: str | None = None,
        cli_overrides: dict[str, Any] | None = None,
        settings_module: str | None = None,
    ) -> None:
        self._env = env or os.environ.get("API_ENV", "dev")
        self._cli_overrides: dict[str, Any] = cli_overrides or {}
        self._settings_module = settings_module
        self._cache: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def env(self) -> str:
        return self._env

    def load(self) -> dict[str, Any]:
        """Return the fully-resolved config dict (cached after first call)."""
        if self._cache is not None:
            return self._cache

        cfg: dict[str, Any] = dict(_DEFAULTS)

        # Layer 1: settings.py
        _deep_merge(cfg, self._load_settings())

        # Layer 2: CLI overrides
        _deep_merge(cfg, {k: v for k, v in self._cli_overrides.items() if v is not None})

        # Layer 3: Environment variables
        for env_var, cfg_key in _ENV_VAR_MAP.items():
            value = os.environ.get(env_var)
            if value is not None:
                cfg[cfg_key] = self._coerce(cfg_key, value)

        log.debug("Loaded config for env=%r: %s", self._env, cfg)
        self._cache = cfg
        return cfg

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_settings(self) -> dict[str, Any]:
        if not self._settings_module:
            log.warning("No api_settings_module configured — using defaults only")
            return {}
        try:
            module = importlib.import_module(self._settings_module)
        except ModuleNotFoundError:
            log.warning(
                "Settings module not found: %s — using defaults only", self._settings_module
            )
            return {}

        environments = getattr(module, "ENVIRONMENTS", None)
        if not environments:
            log.warning("No ENVIRONMENTS dict found in %s", self._settings_module)
            return {}

        settings_class = environments.get(self._env)
        if not settings_class:
            log.warning(
                "Environment %r not in ENVIRONMENTS %s — using defaults only",
                self._env,
                list(environments.keys()),
            )
            return {}

        return settings_class.as_dict()

    @staticmethod
    def _coerce(key: str, raw: str) -> Any:
        """Coerce env-var strings to appropriate Python types."""
        if key in ("timeout", "api_retry_total"):
            try:
                return int(raw)
            except ValueError:
                return float(raw)
        if key == "verify_ssl":
            return raw.lower() not in ("0", "false", "no")
        if key == "api_retry_backoff_factor":
            return float(raw)
        if key == "api_retry_methods":
            return [m.strip().upper() for m in raw.split(",") if m.strip()]
        return raw


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    """Recursively merge *override* into *base* in-place."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
