"""
pytest plugin entry-point.
Registered via [project.entry-points."pytest11"] in pyproject.toml so pytest
auto-discovers and loads it without any conftest.py changes in consuming projects.
"""
from __future__ import annotations

import datetime
import logging

import pytest

from pytest_api_core.config.env_loader import load_env_file
from pytest_api_core.fixtures.api_fixtures import (
    api_config,
    api_client,
    api_bearer_auth,
    api_basic_auth,
    api_key_auth,
)
from pytest_api_core.reporters.html_reporter import HTMLReporter


# ---------------------------------------------------------------------------
# CLI options
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("pytest-api-core", "API framework options")
    group.addoption(
        "--api-env",
        action="store",
        default=None,
        help="Target environment name (maps to config/env/<name>.yaml)",
    )
    group.addoption(
        "--api-config-dir",
        action="store",
        default="config/env",
        help="Directory containing environment YAML files (default: config/env)",
    )
    group.addoption(
        "--api-html-report",
        action="store",
        default=None,
        metavar="PATH",
        help="Path for the custom HTML report (e.g. reports/report.html)",
    )
    group.addoption(
        "--api-base-url",
        action="store",
        default=None,
        help="Override base_url from config",
    )
    group.addoption(
        "--api-log-level",
        action="store",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Log level for pytest-api-core internals (default: WARNING)",
    )
    # Register ini options to suppress "Unknown config option" warnings
    parser.addini("api_env", help="Default environment (e.g. dev, staging, prod)", default="dev")
    parser.addini("api_html_report", help="Output path for the custom HTML report", default=None)
    parser.addini("api_log_level", help="Log level for pytest-api-core (DEBUG/INFO/WARNING/ERROR/CRITICAL)", default="WARNING")
    parser.addini("api_settings_module", help="Dotted module path to settings (e.g. config.settings)", default=None)
    parser.addini("api_dotenv_file", help="Path to .env file loaded at session start (default: .env)", default=".env")


# ---------------------------------------------------------------------------
# ini options (allow pytest.ini / pyproject.toml [tool.pytest.ini_options])
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "api: mark test as an API test")

    # Load .env file before anything else so os.environ is fully populated
    # for settings.py class attributes and fixtures
    dotenv_path = config.getini("api_dotenv_file") or ".env"
    load_env_file(dotenv_path)

    # Configure the framework logger level from CLI option or ini
    log_level = (
        config.getoption("--api-log-level", default=None)
        or config.getini("api_log_level")
        or "WARNING"
    )
    logging.getLogger("pytest_api_core").setLevel(log_level.upper())

    report_path = config.getoption("--api-html-report", default=None)
    if not report_path:
        report_path = config.getini("api_html_report")
    if report_path:
        env = (
            config.getoption("--api-env", default=None)
            or config.getini("api_env")
            or "default"
        )
        report_path = _resolve_report_path(report_path, env)
        plugin = HTMLReporter(report_path)
        config.pluginmanager.register(plugin, "api-html-reporter")


def _resolve_report_path(path: str, env: str) -> str:
    """Expand {timestamp} and {env} placeholders in the report path."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return path.format(timestamp=timestamp, env=env)


# ---------------------------------------------------------------------------
# Re-export fixtures so pytest can discover them from this module
# ---------------------------------------------------------------------------

__all__ = [
    "api_config",
    "api_client",
    "api_bearer_auth",
    "api_basic_auth",
    "api_key_auth",
]
