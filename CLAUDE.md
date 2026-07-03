# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

`pytest-api-core` is a **pytest plugin** distributed as a Python package. It is not a test suite itself — it is a reusable framework that consuming projects install and use. The package auto-registers its fixtures via `pytest11` entry-point, so users never need to import anything in their `conftest.py`.

## Commands

```bash
# Set up development environment
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,dotenv]"

# Run all tests (unit + sample API tests)
pytest tests/

# Run only unit tests (no network)
pytest tests/unit/

# Run only e2e tests (hits jsonplaceholder.typicode.com)
pytest tests/e2e/ --api-env=dev

# Run a single test
pytest tests/unit/test_unit.py::TestAssertionsHappyPath::test_assertion_status_is -v

# Run with HTML report
pytest tests/ --api-html-report=reports/report_{timestamp}.html

# Linting and formatting
black src/ tests/
isort src/ tests/
mypy src/

# Build distribution
python -m build

# Upload to PyPI
twine upload dist/*
```

## Architecture

The plugin has five primary subsystems, each in its own package under `src/pytest_api_core/`:

### Plugin Entry Point (`plugin.py`)
Registered via `[project.entry-points."pytest11"]`. Runs on pytest startup to:
1. Register CLI options (`--api-env`, `--api-base-url`, `--api-html-report`, `--api-log-level`) and ini options
2. Load the `.env` file early via `load_env_file()` so env vars are set before fixtures run
3. Conditionally register `HTMLReporter` if a report path is configured

### Config System (`config/`)
Three-layer config resolution (highest priority first):
1. Shell env vars (`API_BASE_URL`, `API_TOKEN`, `API_ENV`, `API_TIMEOUT`, `API_VERIFY_SSL`)
2. CLI flags (`--api-base-url`)
3. `ENVIRONMENTS[env]` class in the consumer's `settings_module`
4. Built-in defaults

Consumers define environment classes by subclassing `BaseSettings` and registering them in an `ENVIRONMENTS` dict. `ConfigManager.load()` merges all layers and caches the result. `BaseSettings.as_dict()` uses MRO traversal so subclasses properly inherit parent settings.

### HTTP Client (`client/`)
`APIClient` wraps `requests.Session` with:
- Retry via `urllib3.Retry` (3 retries on 5xx, GET/HEAD/OPTIONS only, 0.3s backoff)
- Structured `__API_CALL__` debug log lines (JSON sentinels) parsed by `HTMLReporter`
- Returns `APIResponse` objects (thin wrapper around `requests.Response` adding `elapsed_ms`)

Auth tokens are **never logged** — filtered in `_request()` before emitting the sentinel.

### Fluent Assertions (`assertions/`)
`assert_that(response)` returns a `ResponseAssertions` chain. Key design points:
- `json_path()` uses a built-in path resolver (`_resolve_path`) — no `jsonpath-ng` dependency required. Supported: `$.key`, `$.key.nested`, `$.items[0].id`, `$[0].id`. Not supported: wildcards, filter expressions, recursive descent, slices.
- `json_path()` stores the extracted value in `_json_path_value`; `.equals()` / `.matches()` / `.is_not_none()` consume it and reset to `_UNSET`.
- Each assertion emits a `__API_ASSERT__` debug sentinel parsed by `HTMLReporter` to display pass/fail in the report.

### Auth Handlers (`auth/`)
All handlers subclass `requests.auth.AuthBase`. Available strategies:
- `BearerAuth(token)` — injects `Authorization: Bearer <token>`
- `BasicAuth(username, password)` — delegates to `requests.HTTPBasicAuth`
- `APIKeyAuth(name, value, location)` — header or query param
- `OAuth2ClientCredentials(token_url, client_id, client_secret)` — client credentials flow with auto-refresh 30s before expiry

### HTML Reporter (`reporters/`)
A second pytest plugin registered dynamically (only when a report path is configured). It:
- Listens to `pytest_runtest_logreport` and `pytest_runtest_logfinish` hooks
- Parses `__API_CALL__` and `__API_ASSERT__` sentinels from captured DEBUG logs
- Renders a self-contained HTML file from a Jinja2 template in `reporters/templates/`

The template is shipped in the wheel via `[tool.setuptools.package-data]`.

## Fixtures

All fixtures are session-scoped except auth fixtures (function-scoped). The `api_client` fixture auto-applies `BearerAuth` if `API_TOKEN` env var or `api_config["_token"]` is set.

Consuming projects override `api_client` in their own `conftest.py` to inject project-specific auth or headers — the default fixture is intentionally minimal.

## Testing the Framework

Unit tests in `tests/unit/test_unit.py` use the `responses` library to mock HTTP — no network needed. E2e tests in `tests/e2e/test_sample_api.py` hit `jsonplaceholder.typicode.com`.

When writing tests for new framework features, mock HTTP with `@responses.activate` and assert on `APIResponse` attributes or `ResponseAssertions` behavior.

## Code Style

- `black` with `line-length = 100`
- `isort` with `profile = "black"`
- `mypy` in strict mode (`strict = true`)
- Python 3.9+ compatibility required (use `from __future__ import annotations` for PEP 604 union types)
