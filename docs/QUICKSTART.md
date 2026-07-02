# pytest-api-core — Setup Guide

## 1. Create the project

```bash
mkdir my-api-tests && cd my-api-tests
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

---

## 2. Install the plugin

```bash
pip install pytest-api-core==1.0.3
```

With `.env` file support (recommended):

```bash
pip install "pytest-api-core[dotenv]==1.0.3"
```

### Pin in `requirements.txt`

```
pytest-api-core[dotenv]==1.0.3
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
│   ├── conftest.py        ← override auth_provider with your auth
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
    api_retry_total = 5              # staging is flakier — retry more (default: 3)
    api_retry_backoff_factor = 1.0   # and wait longer between attempts (default: 0.3)


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

## 7. Override auth — `tests/conftest.py`

The built-in `api_client` fixture auto-applies `BearerAuth` if `API_TOKEN` is set. For
any other auth strategy, override the `auth_provider` fixture it depends on — you don't
need to redeclare `api_client` (and re-specify `base_url`/`timeout`/`verify_ssl`/retry)
just to swap auth:

```python
import pytest
from pytest_api_core.auth.auth_handlers import BearerAuth
from pytest_api_core.config.env_loader import get_env


@pytest.fixture(scope="session")
def auth_provider():
    """Bearer token auth, read from .env / shell."""
    token = get_env("BEARER_TOKEN", required=True)
    return BearerAuth(token)
```

That's it — `api_client` picks up whatever `auth_provider` returns.

### Other auth overrides

**Basic auth:**

```python
import os
from pytest_api_core.auth.auth_handlers import BasicAuth

@pytest.fixture(scope="session")
def auth_provider():
    return BasicAuth(
        username=os.environ["API_USERNAME"],
        password=os.environ["API_PASSWORD"],
    )
```

**API key (header):**

```python
import os
from pytest_api_core.auth.auth_handlers import APIKeyAuth

@pytest.fixture(scope="session")
def auth_provider():
    return APIKeyAuth(name="x-api-key", value=os.environ["API_KEY"])
```

**OAuth2 client credentials (auto-refresh):**

```python
import os
from pytest_api_core.auth.auth_handlers import OAuth2ClientCredentials

@pytest.fixture(scope="session")
def auth_provider():
    return OAuth2ClientCredentials(
        token_url="https://auth.mycompany.com/oauth/token",
        client_id=os.environ["CLIENT_ID"],
        client_secret=os.environ["CLIENT_SECRET"],
    )
```

If you need to change `base_url`/`timeout`/`verify_ssl`/retries too, override `api_client`
itself instead — its default implementation shows the full parameter list:

```python
import pytest
from pytest_api_core.client.api_client import APIClient

@pytest.fixture(scope="session")
def api_client(api_config, auth_provider):
    client = APIClient(
        base_url=api_config["base_url"],
        auth=auth_provider,
        timeout=45,  # e.g. a longer timeout for this suite
        verify_ssl=api_config.get("verify_ssl", True),
    )
    yield client
    client.close()
```

### Custom auth handlers

For anything the framework doesn't ship out of the box — an OAuth2 **refresh-token**
flow (as opposed to the client-credentials flow `OAuth2ClientCredentials` implements),
HMAC-signed requests, mTLS client certs, etc. — subclass `requests.auth.AuthBase`
directly. It only needs one method: `__call__(self, r) -> PreparedRequest`. All of the
framework's own auth classes (`BearerAuth`, `BasicAuth`, `APIKeyAuth`,
`OAuth2ClientCredentials`) are just examples of this same pattern — see
`src/pytest_api_core/auth/auth_handlers.py` for reference.

**OAuth2 refresh-token flow:**

```python
import time
import requests
from requests.auth import AuthBase

class OAuth2RefreshTokenAuth(AuthBase):
    def __init__(self, token_url: str, refresh_token: str, client_id: str) -> None:
        self._token_url = token_url
        self._refresh_token = refresh_token
        self._client_id = client_id
        self._access_token: str | None = None
        self._expires_at = 0.0

    def _refresh(self) -> None:
        resp = requests.post(
            self._token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
            },
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._access_token = payload["access_token"]
        self._refresh_token = payload.get("refresh_token", self._refresh_token)
        self._expires_at = time.monotonic() + payload.get("expires_in", 3600)

    def __call__(self, r: requests.PreparedRequest) -> requests.PreparedRequest:
        if self._access_token is None or time.monotonic() >= self._expires_at - 30:
            self._refresh()
        r.headers["Authorization"] = f"Bearer {self._access_token}"
        return r
```

**Signed requests (HMAC):**

```python
import hashlib
import hmac
import time
from requests.auth import AuthBase

class HMACSignedAuth(AuthBase):
    def __init__(self, key_id: str, secret: str) -> None:
        self._key_id = key_id
        self._secret = secret.encode()

    def __call__(self, r):
        timestamp = str(int(time.time()))
        message = f"{r.method}\n{r.path_url}\n{timestamp}".encode()
        signature = hmac.new(self._secret, message, hashlib.sha256).hexdigest()
        r.headers["X-Key-Id"] = self._key_id
        r.headers["X-Timestamp"] = timestamp
        r.headers["X-Signature"] = signature
        return r
```

Either way, plug it in via `auth_provider` (see [Step 7](#7-override-auth--testsconftestpy)) —
nothing else in the framework needs to know about your custom class:

```python
@pytest.fixture(scope="session")
def auth_provider():
    return OAuth2RefreshTokenAuth(
        token_url="https://auth.mycompany.com/oauth/token",
        refresh_token=os.environ["REFRESH_TOKEN"],
        client_id=os.environ["CLIENT_ID"],
    )
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

# Override retry policy (e.g. a flakier environment)
pytest tests/ --api-retry-total=5 --api-retry-backoff-factor=1.0

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
| `API_RETRY_TOTAL` | Overrides max retry attempts (default: `3`) |
| `API_RETRY_BACKOFF_FACTOR` | Overrides retry backoff factor (default: `0.3`) |
| `API_RETRY_METHODS` | Overrides retryable HTTP methods, comma-separated (default: `GET,HEAD,OPTIONS`) |
| `BEARER_TOKEN` | Read by the `conftest.py` override above |
| `API_TOKEN` | Read by the built-in `api_client` fixture (if not overriding) |
| `API_USERNAME` / `API_PASSWORD` | Read by `api_basic_auth` fixture |
| `API_KEY_VALUE` | Read by `api_key_auth` fixture |

---

## 11. GitHub Actions

```yaml
- name: Install dependencies
  run: pip install "pytest-api-core[dotenv]==1.0.3"

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

# JSON path — a small built-in subset, not full JSONPath (see below)
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

# Performance — includes any retry/backoff time, not just the final attempt
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

### `json_path()` syntax

`json_path()` implements a small built-in subset of dot/bracket-index navigation —
it is **not** a full JSONPath implementation, and there's no external dependency
required to use it.

**Supported:**
- `$.key` — top-level key
- `$.key.nested` — nested key
- `$.items[0].id` — array index
- `$[0].id` — root is an array

**Not supported:**
- Wildcards (`$.items[*].id`)
- Filter expressions (`$.items[?(@.price > 10)]`)
- Recursive descent (`$..id`)
- Slices (`$.items[0:2]`)

If you need the full JSONPath spec, extract the value with a library like
`jsonpath-ng` yourself and assert on the result directly, e.g.:

```python
from jsonpath_ng import parse

matches = [m.value for m in parse("$.items[*].id").find(r.json())]
assert matches == [1, 2, 3]
```

### Standalone assertion helpers

For comparing arbitrary values outside the `assert_that()` chain — e.g. a value
you've extracted yourself, or a non-HTTP value — use the standalone functions
instead. They're plain functions, not tied to an `APIResponse`, but still show up
in the HTML report the same way:

```python
from pytest_api_core.assertions import (
    assert_equal,
    assert_not_equal,
    assert_equal_ignore_case,
    assert_contains,
    assert_matches,
    assert_is_empty,
    assert_is_not_empty,
    assert_matches_schema,
)

assert_equal(actual, "expected-value")
assert_contains(actual, "substring")
assert_matches(actual, r"^\d+$")
assert_is_not_empty(actual)

# All of the above accept an optional custom message:
assert_equal(actual, "expected-value", message="Usernames must match")

# JSON Schema validation for any dict/value (not just a response body).
# Unlike assert_that(r).matches_schema(...), which stops at the first
# violation, this collects *all* validation errors into one AssertionError:
assert_matches_schema(payload, {
    "type": "object",
    "required": ["id", "name"],
    "properties": {
        "id":   {"type": "integer"},
        "name": {"type": "string"},
    },
})
```
