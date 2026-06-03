# pytest-api-core

[![PyPI version](https://img.shields.io/pypi/v/pytest-api-core)](https://pypi.org/project/pytest-api-core/)
[![Python](https://img.shields.io/pypi/pyversions/pytest-api-core)](https://pypi.org/project/pytest-api-core/)
[![License](https://img.shields.io/pypi/l/pytest-api-core)](LICENSE)

> A reusable pytest plugin for API automation — fluent assertions, built-in auth strategies, environment-aware configuration, and a self-contained HTML report.

## Features

- **`APIClient`** — `requests.Session` wrapper with retry, timeout, and structured logging
- **Fluent assertions** — `assert_that(response).status_is(200).json_path("$.id").equals(1)`
- **Auth strategies** — Bearer token, Basic, API Key (header/query), OAuth2 client credentials
- **Environment config** — Python `settings.py` classes + `.env` file + env var overrides
- **Custom HTML report** — self-contained file with charts, filterable table, and request/response details
- **Auto-registered fixtures** — zero boilerplate in consuming projects

---

## Installation

```bash
pip install pytest-api-core==1.0.2
```

With `.env` file support (recommended):

```bash
pip install "pytest-api-core[dotenv]==1.0.2"
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

### Key `pytest.ini` options

| Option | Description | Default |
|---|---|---|
| `api_env` | Active environment name | `dev` |
| `api_settings_module` | Dotted path to your settings module | — |
| `api_dotenv_file` | Path to `.env` file | `.env` |
| `api_log_level` | Framework log level | `WARNING` |
| `api_html_report` | HTML report path (supports `{env}`, `{timestamp}`) | — |
| `api_html_theme` | Report theme: `light` or `dark` | `dark` |

### CLI flags

| Flag | Description |
|---|---|
| `--api-env` | Override active environment |
| `--api-base-url` | Override `base_url` |
| `--api-log-level` | Override framework log level |
| `--api-html-report` | Override HTML report path |

---

## Fixtures

All fixtures are auto-registered — no imports needed in `conftest.py`.

| Fixture | Scope | Description |
|---|---|---|
| `api_config` | session | Resolved config dict for the active env |
| `api_client` | session | Configured `APIClient` instance |
| `api_bearer_auth` | function | `BearerAuth` from `API_TOKEN` env var |
| `api_basic_auth` | function | `BasicAuth` from `API_USERNAME` / `API_PASSWORD` |
| `api_key_auth` | function | `APIKeyAuth` from `API_KEY_NAME` / `API_KEY_VALUE` |

Override `api_client` in your project's `conftest.py` to inject custom auth — see [docs/QUICKSTART.md](docs/QUICKSTART.md#7-override-api_client-with-bearer-token----testsconftestpy).

---

## License

See [LICENSE](LICENSE).
