# pytest-api-core

> A reusable pytest API automation framework with fluent assertions, built-in auth strategies, environment-aware configuration, and a beautiful custom HTML report — packaged for Artifactory distribution.

## Features

- **`APIClient`** — `requests.Session` wrapper with retry, timeout, and structured logging
- **Fluent response assertions** — `assert_that(response).status_is(200).json_path("$.id").equals(1)`
- **Auth strategies** — Bearer token, Basic, API Key (header/query), OAuth2 client credentials
- **Environment config** — YAML files + `ENV_VAR` overrides via `api_config` fixture
- **Custom HTML report** — self-contained report with charts, filterable table, and request/response details
- **Auto-registered pytest fixtures** — zero boilerplate in consuming projects

---

## Installation

### From Artifactory (PyPI proxy)

```bash
pip install pytest-api-core \
  --index-url https://<user>:<token>@<your-org>.jfrog.io/artifactory/api/pypi/<repo>/simple
```

Or add to `requirements.txt` / `pyproject.toml`:

```
pytest-api-core==1.0.0
```

And configure pip via `pip.conf` or environment:

```ini
[global]
index-url = https://<user>:<token>@<your-org>.jfrog.io/artifactory/api/pypi/<repo>/simple
```

---

## Quick Start

### 1. Create environment config

```yaml
# config/env/dev.yaml
base_url: https://jsonplaceholder.typicode.com
timeout: 30
verify_ssl: true
headers:
  Accept: application/json
```

### 2. Write tests

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

### 3. Run with HTML report

```bash
pytest tests/ --api-html-report=reports/report.html --api-env=dev
```

---

## Configuration

### pytest.ini / pyproject.toml

```ini
[pytest]
api_env = dev
api_config_dir = config/env
api_html_report = reports/report.html
```

### Environment Variables

| Variable | Purpose |
|---|---|
| `API_BASE_URL` | Override `base_url` |
| `API_TOKEN` | Inject Bearer token |
| `API_ENV` | Select environment config |

---

## Fixtures

| Fixture | Scope | Description |
|---|---|---|
| `api_client` | session | Configured `APIClient` instance |
| `api_config` | session | Resolved config dict for the active env |
| `api_bearer_auth` | function | Bearer token auth handler |
| `api_basic_auth` | function | Basic auth handler |

---

## Publishing to Artifactory

```bash
# Build
python -m build

# Upload via twine
twine upload \
  --repository-url https://<org>.jfrog.io/artifactory/api/pypi/<repo> \
  -u <user> -p <token> \
  dist/*
```

See `scripts/publish.sh` for CI/CD integration.

---

## Project Layout

```
src/
└── pytest_api_core/
    ├── plugin.py           # pytest entry-point
    ├── client/             # HTTP client + response wrapper
    ├── auth/               # Auth strategy classes
    ├── config/             # YAML + env-var config manager
    ├── fixtures/           # Auto-registered pytest fixtures
    ├── assertions/         # Fluent response assertion API
    └── reporters/          # Custom HTML report plugin + template
tests/                      # Package self-tests
config/env/                 # Sample environment configs
scripts/                    # Build & publish helpers
```

---

## License

See [LICENSE](LICENSE).
