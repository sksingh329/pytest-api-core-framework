# pytest-api-core — Setup Guide

## 1. Create the project

```bash
mkdir my-api-tests && cd my-api-tests
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

---

## 2. Install the plugin

```bash
pip install pytest-api-core==1.0.2
```

With `.env` file support (recommended):

```bash
pip install "pytest-api-core[dotenv]==1.0.2"
```

### Pin in `requirements.txt`

```
pytest-api-core[dotenv]==1.0.2
```

```bash
pip install -r requirements.txt
```

---

## 3. Project layout

```
my-api-tests/
├── config/
│   └── settings.py        ← environment definitions
├── tests/
│   ├── conftest.py        ← override api_client with your auth
│   └── test_users.py
├── .env                   ← secrets (never commit this)
└── pytest.ini
```

---

## 4. Define environments — `config/settings.py`

```python
import os
from pytest_api_core.config.base_settings import BaseSettings


class DevSettings(BaseSettings):
    base_url   = "https://api.dev.mycompany.com"
    timeout    = 30
    verify_ssl = True
    headers    = {"Accept": "application/json", "Content-Type": "application/json"}


class StagingSettings(DevSettings):
    base_url = os.environ.get("API_BASE_URL", "https://api.staging.mycompany.com")
    timeout  = 60


class ProdSettings(BaseSettings):
    base_url   = os.environ.get("API_BASE_URL", "https://api.mycompany.com")
    timeout    = 60
    verify_ssl = True
    headers    = {"Accept": "application/json", "Content-Type": "application/json"}


ENVIRONMENTS = {
    "dev":     DevSettings,
    "staging": StagingSettings,
    "prod":    ProdSettings,
}
```

---

## 5. Store secrets — `.env`

```ini
# .env  — never commit this file
BEARER_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
API_BASE_URL=https://api.staging.mycompany.com
```

Add `.env` to `.gitignore`:

```
.env
```

---

## 6. Configure pytest — `pytest.ini`

```ini
[pytest]

# ── Environment ───────────────────────────────────────────────────────────────
api_env             = dev
api_settings_module = config.settings
api_dotenv_file     = .env

# ── Report ────────────────────────────────────────────────────────────────────
addopts             = --api-html-report=reports/{env}/report_{timestamp}.html -v
api_html_theme      = dark
api_html_title      = My API Tests
api_html_header     = My API Tests

# ── Logging ───────────────────────────────────────────────────────────────────
api_log_level       = INFO
log_cli             = true
log_cli_level       = INFO
log_cli_format      = %(asctime)s [%(levelname)-8s] %(name)s: %(message)s
log_cli_date_format = %H:%M:%S
```

| Option | Description |
|---|---|
| `api_env` | Which key from `ENVIRONMENTS` to load |
| `api_settings_module` | Dotted path to your `settings.py` |
| `api_dotenv_file` | Path to your `.env` file (loaded before fixtures run) |
| `api_html_report` | Output path; `{env}` and `{timestamp}` are expanded automatically |
| `api_html_theme` | `dark` or `light` |
| `api_log_level` | Log level for framework internals (`DEBUG`/`INFO`/`WARNING`) |

---

## 7. Override `api_client` with Bearer token — `tests/conftest.py`

The built-in `api_client` fixture auto-applies `BearerAuth` if `API_TOKEN` is set, but for full control override it explicitly:

```python
import os
import pytest
from pytest_api_core.auth.auth_handlers import BearerAuth
from pytest_api_core.client.api_client import APIClient
from pytest_api_core.config.env_loader import get_env


@pytest.fixture(scope="session")
def api_client(api_config):
    """Session-scoped client with Bearer token auth."""
    token = get_env("BEARER_TOKEN", required=True)   # reads from .env / shell

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

### Other auth overrides

**Basic auth:**

```python
from pytest_api_core.auth.auth_handlers import BasicAuth

@pytest.fixture(scope="session")
def api_client(api_config):
    client = APIClient(
        base_url=api_config["base_url"],
        auth=BasicAuth(
            username=os.environ["API_USERNAME"],
            password=os.environ["API_PASSWORD"],
        ),
    )
    yield client
    client.close()
```

**API key (header):**

```python
from pytest_api_core.auth.auth_handlers import APIKeyAuth

@pytest.fixture(scope="session")
def api_client(api_config):
    client = APIClient(
        base_url=api_config["base_url"],
        auth=APIKeyAuth(name="x-api-key", value=os.environ["API_KEY"]),
    )
    yield client
    client.close()
```

**OAuth2 client credentials (auto-refresh):**

```python
from pytest_api_core.auth.auth_handlers import OAuth2ClientCredentials

@pytest.fixture(scope="session")
def api_client(api_config):
    auth = OAuth2ClientCredentials(
        token_url="https://auth.mycompany.com/oauth/token",
        client_id=os.environ["CLIENT_ID"],
        client_secret=os.environ["CLIENT_SECRET"],
    )
    client = APIClient(base_url=api_config["base_url"], auth=auth)
    yield client
    client.close()
```

---

## 8. Write tests — `tests/test_users.py`

```python
import pytest
from pytest_api_core.assertions import assert_that


@pytest.mark.api
def test_get_user(api_client):
    response = api_client.get("/users/1")

    assert_that(response).status_is(200).content_type_contains("application/json")
    assert_that(response).json_path("$.id").equals(1)
    assert_that(response).json_path("$.name").is_not_none()
    assert_that(response).response_time_under(1000)


@pytest.mark.api
def test_create_user(api_client):
    payload = {"name": "Alice", "email": "alice@example.com"}
    response = api_client.post("/users", json=payload)

    assert_that(response).status_is(201).has_key("id")


@pytest.mark.api
def test_list_users(api_client):
    response = api_client.get("/users")

    assert_that(response).status_is(200).is_json_list().list_length_gte(1)
```

---

## 9. Run tests

```bash
# Use the environment defined in pytest.ini
pytest tests/

# Override environment at runtime
pytest tests/ --api-env=staging

# Override base URL
pytest tests/ --api-base-url=https://api.staging.mycompany.com

# Verbose debug output (shows full request/response)
pytest tests/ --api-log-level=DEBUG -s

# Run a single test
pytest tests/test_users.py::test_get_user -v

# Run only tests tagged @pytest.mark.api
pytest tests/ -m api
```

---

## 10. Environment variable overrides (CI / shell)

Shell env vars take highest priority and always override `settings.py` values.

| Variable | Effect |
|---|---|
| `API_ENV` | Selects the environment (same as `--api-env`) |
| `API_BASE_URL` | Overrides `base_url` from settings |
| `API_TIMEOUT` | Overrides `timeout` (integer seconds) |
| `API_VERIFY_SSL` | Set to `false` / `0` / `no` to disable SSL verification |
| `BEARER_TOKEN` | Read by the `conftest.py` override above |
| `API_TOKEN` | Read by the built-in `api_client` fixture (if not overriding) |
| `API_USERNAME` / `API_PASSWORD` | Read by `api_basic_auth` fixture |
| `API_KEY_VALUE` | Read by `api_key_auth` fixture |

---

## 11. GitHub Actions

```yaml
- name: Install dependencies
  run: pip install "pytest-api-core[dotenv]==1.0.2"

- name: Run API tests
  run: pytest tests/ -v
  env:
    API_ENV:      staging
    BEARER_TOKEN: ${{ secrets.STAGING_BEARER_TOKEN }}
    API_BASE_URL: ${{ secrets.STAGING_BASE_URL }}

- name: Upload HTML report
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: api-test-report
    path: reports/
    retention-days: 14
```

---

## Assertion quick reference

```python
from pytest_api_core.assertions import assert_that

# Status
assert_that(r).status_is(200)
assert_that(r).status_in(200, 201)
assert_that(r).is_success()          # 2xx
assert_that(r).is_client_error()     # 4xx
assert_that(r).is_server_error()     # 5xx

# JSON keys (top-level)
assert_that(r).has_key("id").has_key("name")
assert_that(r).key_equals("status", "active")

# JSON path
assert_that(r).json_path("$.id").equals(1)
assert_that(r).json_path("$.user.name").equals("Alice")
assert_that(r).json_path("$.items[0].price").equals(9.99)
assert_that(r).json_path("$.status").matches(r"^(active|pending)$")
assert_that(r).json_path("$.token").is_not_none()

# Headers
assert_that(r).has_header("x-request-id")
assert_that(r).content_type_contains("application/json")
assert_that(r).header_equals("x-rate-limit-remaining", "99")

# Body text
assert_that(r).body_contains("success")

# Lists
assert_that(r).is_json_list().list_length(5)
assert_that(r).is_json_list().list_length_gte(1)

# Schema
assert_that(r).matches_schema({
    "type": "object",
    "required": ["id", "name"],
    "properties": {
        "id":   {"type": "integer"},
        "name": {"type": "string"},
    },
})

# Performance
assert_that(r).response_time_under(500)   # ms

# Chain everything
(
    assert_that(r)
    .status_is(200)
    .content_type_contains("application/json")
    .json_path("$.id").equals(1)
    .response_time_under(1000)
)
```
