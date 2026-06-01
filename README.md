# pytest-api-core

> A reusable pytest API automation framework with fluent assertions, built-in auth strategies, environment-aware configuration, and a beautiful custom HTML report — packaged for Artifactory distribution.

## Features

- **`APIClient`** — `requests.Session` wrapper with retry, timeout, and structured logging
- **Fluent response assertions** — `assert_that(response).status_is(200).json_path("$.id").equals(1)`
- **Auth strategies** — Bearer token, Basic, API Key (header/query), OAuth2 client credentials
- **Environment config** — Python `settings.py` classes + `.env` file + `ENV_VAR` overrides via `api_config` fixture
- **Custom HTML report** — self-contained report with charts, filterable table, captured logs, and request/response details
- **Auto-registered pytest fixtures** — zero boilerplate in consuming projects

---

## Installation

### From private PyPI

```bash
pip install pytest-api-core \
  --index-url https://pypi.example.com/simple/
```

With `.env` support (optional but recommended):

```bash
pip install "pytest-api-core[dotenv]"
```

Or add to `requirements.txt` / `pyproject.toml`:

```
pytest-api-core==1.0.0
```

---

## Quick Start

### 1. Create environment settings

```python
# config/settings.py
import os
from pytest_api_core.config.base_settings import BaseSettings

class DevSettings(BaseSettings):
    base_url = "https://api.dev.example.com"
    timeout  = 30
    verify_ssl = True
    headers  = {"Accept": "application/json", "Content-Type": "application/json"}

class StagingSettings(DevSettings):
    base_url = os.environ.get("API_BASE_URL", "https://api.staging.example.com")
    timeout  = 60

ENVIRONMENTS = {
    "dev":     DevSettings,
    "staging": StagingSettings,
}
```

### 2. Store secrets in `.env` (never commit this file)

```ini
# .env
BEARER_TOKEN=eyJhbGciOiJIUzI1NiIs...
API_KEY=super-secret-key
```

### 3. Configure pytest.ini

```ini
[pytest]

# ── Framework ────────────────────────────────────────────────────────────────
api_env             = dev
api_settings_module = config.settings
api_dotenv_file     = .env

# ── Report ───────────────────────────────────────────────────────────────────
addopts = --api-html-report=reports/{env}/report_{timestamp}.html -v
api_html_theme      = dark            # or "light"
api_html_title      = API Test Report # browser tab title
api_html_header     = API Test Report # page header text

# ── Logging ──────────────────────────────────────────────────────────────────
api_log_level       = INFO
log_cli             = true
log_cli_level       = INFO
log_cli_format      = %(asctime)s [%(levelname)-8s] %(name)s: %(message)s
log_cli_date_format = %H:%M:%S
```

### 4. Write tests

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

### 5. Run with HTML report

```bash
pytest tests/ --api-env=staging
```

The report is written to `reports/staging/report_<timestamp>.html`.

---

## Configuration

### Resolution order (highest → lowest priority)

| Priority | Source |
|---|---|
| 1 | Shell / CI environment variables (`API_BASE_URL`, `API_TOKEN`, …) |
| 2 | `--api-base-url` CLI flag |
| 3 | `ENVIRONMENTS[env]` class in `settings_module` |
| 4 | Built-in defaults (`http://localhost`, timeout 30 s, …) |

### pytest.ini options

| Option | Description | Default |
|---|---|---|
| `api_env` | Active environment name | `dev` |
| `api_settings_module` | Dotted path to settings module | — |
| `api_dotenv_file` | Path to `.env` file | `.env` |
| `api_log_level` | Log level for framework internals | `WARNING` |
| `api_html_report` | Output path for HTML report (supports `{env}`, `{timestamp}`) | — |
| `api_html_theme` | Report theme: `light` or `dark` | `dark` |
| `api_html_title` | Browser tab title text | `API Test Report` |
| `api_html_header` | Page header text | `API Test Report` |

### CLI flags

| Flag | Description |
|---|---|
| `--api-env` | Override active environment |
| `--api-base-url` | Override `base_url` |
| `--api-log-level` | Override framework log level |
| `--api-html-report` | Override HTML report path |

### Environment variables

| Variable | Purpose |
|---|---|
| `API_BASE_URL` | Override `base_url` |
| `API_TOKEN` | Inject Bearer token (auto-applied by `api_client`) |
| `API_ENV` | Select environment |
| `API_TIMEOUT` | Override request timeout |
| `API_VERIFY_SSL` | Override SSL verification |

---

## Fixtures

| Fixture | Scope | Description |
|---|---|---|
| `api_config` | session | Resolved config dict for the active env |
| `api_client` | session | Configured `APIClient` instance |
| `api_bearer_auth` | function | `BearerAuth` built from `API_TOKEN` env var |
| `api_basic_auth` | function | `BasicAuth` built from `API_USERNAME` / `API_PASSWORD` |
| `api_key_auth` | function | `APIKeyAuth` built from `API_KEY_NAME` / `API_KEY_VALUE` |

### Overriding `api_client` per project

```python
# tests/conftest.py
import pytest
from pytest_api_core.auth.auth_handlers import BearerAuth
from pytest_api_core.client.api_client import APIClient
from pytest_api_core.config.env_loader import get_env

@pytest.fixture(scope="session")
def api_client(api_config):
    token = get_env("BEARER_TOKEN", required=True)
    client = APIClient(
        base_url=api_config["base_url"],
        auth=BearerAuth(token),
        timeout=api_config.get("timeout", 30),
        verify_ssl=api_config.get("verify_ssl", True),
        default_headers=api_config.get("headers"),
    )
    yield client
    client.close()
```

---

## Publishing

```bash
# Build
python -m build

# Upload via twine
twine upload \
  --repository-url https://pypi.example.com \
  -u <user> -p <token> \
  dist/*
```

---

## Project Layout

```
src/
└── pytest_api_core/
    ├── plugin.py           # pytest entry-point
    ├── client/             # HTTP client + response wrapper
    ├── auth/               # Auth strategy classes
    ├── config/             # Config manager, BaseSettings, env_loader
    ├── fixtures/           # Auto-registered pytest fixtures
    ├── assertions/         # Fluent response assertion API
    └── reporters/          # Custom HTML report plugin
config/
└── settings.py             # Project environment settings (not shipped in wheel)
tests/                      # Package self-tests
```

---

## License

See [LICENSE](LICENSE).
