# pytest-api-core

[![PyPI version](https://img.shields.io/pypi/v/pytest-api-core)](https://pypi.org/project/pytest-api-core/)
[![Python](https://img.shields.io/pypi/pyversions/pytest-api-core)](https://pypi.org/project/pytest-api-core/)
[![License](https://img.shields.io/pypi/l/pytest-api-core)](LICENSE)

> A reusable pytest plugin for API automation — fluent assertions, built-in auth strategies, environment-aware configuration, and a self-contained HTML report.

## Features

- **`APIClient`** — `requests.Session` wrapper with retry, timeout, and structured logging
- **Fluent assertions** — `assert_that(response).status_is(200).json_path("$.id").equals(1)`
  (`json_path()` supports a small dot/bracket-index subset, not full JSONPath — see [docs/QUICKSTART.md](docs/QUICKSTART.md#json_path-syntax);
  `response_time_under()` measures the whole request including any retries, not just the final attempt)
- **Auth strategies** — Bearer token, Basic, API Key (header/query), OAuth2 client credentials
  (need something else, like an OAuth2 refresh-token flow or signed requests? subclass `AuthBase` — see [docs/QUICKSTART.md](docs/QUICKSTART.md#custom-auth-handlers))
- **Standalone assertion helpers** — `assert_equal`, `assert_contains`, `assert_matches`, `assert_matches_schema`, etc. for values outside an `APIResponse` — see [docs/QUICKSTART.md](docs/QUICKSTART.md#standalone-assertion-helpers)
- **Configurable retry policy** — max attempts, backoff factor, and retryable methods, overridable per environment (see below)
- **Environment config** — Python `settings.py` classes + `.env` file + env var overrides
- **Custom HTML report** — self-contained file with charts, filterable table, and request/response details
- **Auto-registered fixtures** — zero boilerplate in consuming projects

---

## Installation

```bash
pip install pytest-api-core==1.0.4
```

With `.env` file support (recommended):

```bash
pip install "pytest-api-core[dotenv]==1.0.4"
```

---

## Quick start

```python
# tests/test_posts.py
from pytest_api_core.assertions import assert_that

def test_get_post(api_client):
    response = api_client.get("/posts/1")
    assert_that(response).status_is(200).json_path("$.id").equals(1)

def test_create_post(api_client):
    payload = {"title": "foo", "body": "bar", "userId": 1}
    response = api_client.post("/posts", json=payload)
    assert_that(response).status_is(201).has_key("id")
```

```bash
pytest tests/ --api-env=staging
```

For full setup instructions — including `pytest.ini`, `config/settings.py`, `conftest.py` auth overrides, and CI integration — see **[docs/QUICKSTART.md](docs/QUICKSTART.md)**.

---

## Configuration

### Resolution order (highest → lowest priority)

| Priority | Source |
|---|---|
| 1 | Shell / CI environment variables (`API_BASE_URL`, `API_TOKEN`, …) |
| 2 | `--api-base-url` CLI flag |
| 3 | `ENVIRONMENTS[env]` class in `settings_module` |
| 4 | Built-in defaults (`http://localhost`, timeout 30 s) |

### Retry policy

`APIClient` retries idempotent requests (`GET`, `HEAD`, `OPTIONS`) on `500/502/503/504`
responses using `urllib3.Retry`. All three knobs follow the same env var → CLI flag →
`settings_module` → built-in default precedence as `base_url`:

| Setting | `settings_module` attribute | CLI flag | Env var | Default |
|---|---|---|---|---|
| Max retry attempts | `api_retry_total` | `--api-retry-total` | `API_RETRY_TOTAL` | `3` |
| Backoff factor | `api_retry_backoff_factor` | `--api-retry-backoff-factor` | `API_RETRY_BACKOFF_FACTOR` | `0.3` |
| Retryable methods | `api_retry_methods` | `--api-retry-methods` (comma-separated) | `API_RETRY_METHODS` (comma-separated) | `GET,HEAD,OPTIONS` |

Backoff factor `0.3` produces sleeps of `0s, 0.3s, 0.6s, 1.2s, ...` between attempts.

Example — a flakier staging environment gets more retries and a longer backoff:

```python
# settings.py
class StagingSettings(BaseSettings):
    base_url = "https://api.staging.mycompany.com"
    api_retry_total = 5
    api_retry_backoff_factor = 1.0
```

Or per-run, without touching code:

```bash
pytest tests/ --api-env=staging --api-retry-total=5 --api-retry-backoff-factor=1.0
```

To disable retries entirely, pass `retry=None` directly when constructing an
`APIClient` yourself (not available as a config option, since "no retries" isn't
something you'd want to toggle per environment).

### Key `pytest.ini` options

| Option | Description | Default |
|---|---|---|
| `api_env` | Active environment name | `dev` |
| `api_settings_module` | Dotted path to your settings module | — |
| `api_dotenv_file` | Path to `.env` file | `.env` |
| `api_log_level` | Framework log level | `WARNING` |
| `api_html_report` | HTML report path (supports `{env}`, `{timestamp}`) | — |
| `api_html_theme` | Report theme: `light` or `dark` | `dark` |
| `api_html_title` | Report browser tab title | `API Test Report` |
| `api_html_header` | Report page header text | `API Test Report` |

### CLI flags

| Flag | Description |
|---|---|
| `--api-env` | Override active environment |
| `--api-base-url` | Override `base_url` |
| `--api-log-level` | Override framework log level |
| `--api-html-report` | Override HTML report path |
| `--api-retry-total` | Override max retry attempts (default: `3`) |
| `--api-retry-backoff-factor` | Override retry backoff factor (default: `0.3`) |
| `--api-retry-methods` | Override retryable HTTP methods, comma-separated (default: `GET,HEAD,OPTIONS`) |

---

## Fixtures

All fixtures are auto-registered — no imports needed in `conftest.py`.

| Fixture | Scope | Description |
|---|---|---|
| `api_config` | session | Resolved config dict for the active env |
| `auth_provider` | session | Auth strategy passed to `api_client` — override this alone to swap auth |
| `api_client` | session | Configured `APIClient` instance, depends on `auth_provider` |
| `api_bearer_auth` | function | `BearerAuth` from `API_TOKEN` env var |
| `api_basic_auth` | function | `BasicAuth` from `API_USERNAME` / `API_PASSWORD` |
| `api_key_auth` | function | `APIKeyAuth` from `API_KEY_NAME` / `API_KEY_VALUE` |

Override `auth_provider` in your project's `conftest.py` to inject custom auth without
redeclaring `api_client` — see [docs/QUICKSTART.md](docs/QUICKSTART.md#7-override-auth--testsconftestpy).

---

## Project structure

```
pytest-api-core-framework/
├── src/pytest_api_core/
│   ├── plugin.py               # pytest11 entry point — CLI/ini options, .env loading, reporter registration
│   ├── assertions/
│   │   ├── response_assertions.py   # assert_that(response) fluent chain
│   │   └── assert_utils.py          # standalone helpers: assert_equal, assert_contains, ...
│   ├── auth/
│   │   └── auth_handlers.py    # BearerAuth, BasicAuth, APIKeyAuth, OAuth2ClientCredentials
│   ├── client/
│   │   ├── api_client.py       # APIClient (requests.Session wrapper, retry, __API_CALL__ logging)
│   │   └── api_response.py     # APIResponse wrapper (adds elapsed_ms)
│   ├── config/
│   │   ├── base_settings.py    # BaseSettings — subclass to define environments
│   │   ├── config_manager.py   # ConfigManager — merges env vars / CLI / settings_module / defaults
│   │   └── env_loader.py       # .env file loading
│   ├── fixtures/
│   │   └── api_fixtures.py     # api_config, auth_provider, api_client, api_*_auth fixtures
│   └── reporters/
│       ├── html_reporter.py    # parses __API_CALL__/__API_ASSERT__ sentinels, renders HTML report
│       └── templates/report.html
├── tests/
│   ├── unit/test_unit.py       # mocked HTTP tests (responses library)
│   └── e2e/test_e2e_jsonplaceholder.py  # live tests against jsonplaceholder.typicode.com
├── docs/QUICKSTART.md          # full setup guide (settings.py, conftest.py, CI)
├── config/settings.py          # example ENVIRONMENTS settings module
└── pyproject.toml
```

---

## License

See [LICENSE](LICENSE).
