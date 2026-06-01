# pytest-api-core — Usage Guide

## Installation

Install from the private registry:

```bash
pip install pytest-api-core \
  --index-url https://pyuser:PASSWORD@pypi.subodhsingh.in/simple/
```

Or pin in `requirements.txt` / `pyproject.toml`:

```toml
# pyproject.toml
[project]
dependencies = ["pytest-api-core>=1.0.0"]

[tool.pytest.ini_options]
# tells pip where extra packages come from (place in pip.conf instead if private)
```

---

## Project layout for a consumer repo

```
my-api-tests/
├── config/
│   └── env/
│       ├── dev.yaml
│       ├── staging.yaml
│       └── prod.yaml
├── tests/
│   ├── conftest.py        ← optional project-level fixtures
│   └── test_users.py
└── pytest.ini
```

---

## Configuration

### Environment YAML

Each environment file lives in `config/env/<name>.yaml`:

```yaml
# config/env/staging.yaml
base_url: https://api.staging.mycompany.com
timeout: 60
verify_ssl: true
headers:
  Accept: application/json
  Content-Type: application/json
```

Supported keys:

| Key | Type | Default | Description |
|---|---|---|---|
| `base_url` | string | — | Root URL prepended to all request paths |
| `timeout` | int | `30` | Request timeout in seconds |
| `verify_ssl` | bool | `true` | Verify TLS certificates |
| `headers` | dict | `{}` | Default headers merged into every request |

### `pytest.ini`

```ini
[pytest]
api_env        = staging          ; name of the YAML file to load
api_config_dir = config/env       ; folder containing env YAMLs
api_log_level  = INFO             ; DEBUG / INFO / WARNING / ERROR / CRITICAL
api_html_report = reports/report.html
addopts = -v
```

### CLI overrides

```bash
pytest tests/ \
  --api-env=prod \
  --api-base-url=https://api.override.com \
  --api-log-level=DEBUG \
  --api-html-report=reports/run.html
```

### Environment variable overrides

| Variable | Overrides |
|---|---|
| `API_ENV` | `api_env` |
| `API_BASE_URL` | `base_url` in YAML |
| `API_TIMEOUT` | `timeout` in YAML |
| `API_VERIFY_SSL` | `verify_ssl` in YAML |
| `API_TOKEN` | Token used by `api_bearer_auth` fixture |
| `API_USERNAME` | Username for `api_basic_auth` |
| `API_PASSWORD` | Password for `api_basic_auth` |

---

## Fixtures

All fixtures are auto-registered — no `conftest.py` import needed.

### `api_config` _(session scope)_

Returns the fully-resolved config dict for the active environment.

```python
def test_base_url_is_set(api_config):
    assert "mycompany.com" in api_config["base_url"]
```

### `api_client` _(session scope)_

A ready-to-use `APIClient` instance configured from `api_config`.

```python
def test_get_user(api_client):
    response = api_client.get("/users/1")
    assert response.status_code == 200
```

### `api_bearer_auth` _(function scope)_

`BearerAuth` instance. Reads token from `API_TOKEN` env var or `api_config["token"]`.

```python
def test_protected_endpoint(api_client, api_bearer_auth):
    response = api_client.get("/me", auth=api_bearer_auth)
    assert response.status_code == 200
```

### `api_basic_auth` _(function scope)_

`BasicAuth` instance. Reads from `API_USERNAME` / `API_PASSWORD` env vars.

```python
def test_basic_auth(api_client, api_basic_auth):
    response = api_client.get("/admin/stats", auth=api_basic_auth)
    assert response.status_code == 200
```

### `api_key_auth` _(function scope)_

`APIKeyAuth` instance using header injection. Reads key from `api_config["api_key"]`.

```python
def test_api_key(api_client, api_key_auth):
    response = api_client.get("/data", auth=api_key_auth)
    assert response.status_code == 200
```

---

## APIClient

### Direct instantiation

Use this when you need a client pointed at a different host than the default fixture, or with custom auth.

```python
from pytest_api_core.client.api_client import APIClient
from pytest_api_core.auth.auth_handlers import BearerAuth

client = APIClient(
    base_url="https://api.mycompany.com/v2",
    auth=BearerAuth("my-token"),
    timeout=60,
    verify_ssl=True,
    default_headers={"x-request-id": "test-run-001"},
)

response = client.get("/users/1")
response = client.post("/orders", json={"item": "book", "qty": 2})
client.close()
```

### As a context manager

```python
with APIClient(base_url="https://api.mycompany.com") as client:
    response = client.get("/health")
```

### Supported HTTP methods

```python
client.get("/users")
client.post("/users", json={"name": "Alice"})
client.put("/users/1", json={"name": "Alice Updated"})
client.patch("/users/1", json={"name": "Alice Patched"})
client.delete("/users/1")
client.head("/users/1")
client.options("/users")
```

Any keyword argument accepted by `requests.Session.request` is passed through:

```python
client.get("/search", params={"q": "test", "page": 1})
client.post("/upload", files={"file": open("data.csv", "rb")})
client.get("/resource", headers={"x-custom": "value"})
```

### Retries

By default, `GET`, `HEAD`, and `OPTIONS` are retried up to 3 times on 5xx errors with exponential back-off. Disable retries:

```python
client = APIClient(base_url="...", retry=None)
```

Custom retry policy:

```python
from urllib3.util.retry import Retry

client = APIClient(
    base_url="...",
    retry=Retry(total=5, backoff_factor=1.0, status_forcelist=(429, 500, 503)),
)
```

---

## Authentication handlers

### BearerAuth

```python
from pytest_api_core.auth.auth_handlers import BearerAuth

auth = BearerAuth("eyJhbGciOiJIUzI1NiJ9...")
client = APIClient(base_url="...", auth=auth)
```

### BasicAuth

```python
from pytest_api_core.auth.auth_handlers import BasicAuth

auth = BasicAuth("admin", "secret")
client = APIClient(base_url="...", auth=auth)
```

### APIKeyAuth — header (default)

```python
from pytest_api_core.auth.auth_handlers import APIKeyAuth

auth = APIKeyAuth(name="x-api-key", value="abc123")
client = APIClient(base_url="...", auth=auth)
# Sends: x-api-key: abc123
```

### APIKeyAuth — query parameter

```python
auth = APIKeyAuth(name="api_key", value="abc123", location="query")
# Appends: ?api_key=abc123 to every request URL
```

### OAuth2 client credentials (auto-refresh)

```python
from pytest_api_core.auth.auth_handlers import OAuth2ClientCredentials

auth = OAuth2ClientCredentials(
    token_url="https://auth.mycompany.com/oauth/token",
    client_id="my-client",
    client_secret="my-secret",
)
client = APIClient(base_url="...", auth=auth)
# Token is fetched on first request and refreshed automatically on expiry
```

---

## Assertions

Import the entry-point:

```python
from pytest_api_core.assertions.response_assertions import assert_that
```

All methods return `self` — chain freely.

### Status code

```python
assert_that(response).status_is(200)
assert_that(response).status_in(200, 201)
assert_that(response).is_success()        # 2xx
assert_that(response).is_client_error()   # 4xx
assert_that(response).is_server_error()   # 5xx
```

### JSON body — top-level keys

```python
assert_that(response).has_key("id")
assert_that(response).has_key("id").has_key("name")
```

### JSON path

```python
assert_that(response).json_path("$.id").equals(1)
assert_that(response).json_path("$.user.name").equals("Alice")
assert_that(response).json_path("$.items[0].price").equals(9.99)
assert_that(response).json_path("$.status").matches(r"^(active|pending)$")
assert_that(response).json_path("$.token").is_not_none()
```

### Headers

```python
assert_that(response).has_header("content-type")
assert_that(response).header_equals("x-rate-limit-remaining", "99")
assert_that(response).content_type_contains("application/json")
```

### Performance

```python
assert_that(response).response_time_under(500)   # milliseconds
```

### Schema validation (JSON Schema)

```python
schema = {
    "type": "object",
    "required": ["id", "name", "email"],
    "properties": {
        "id":    {"type": "integer"},
        "name":  {"type": "string"},
        "email": {"type": "string", "format": "email"},
    },
}
assert_that(response).matches_schema(schema)
```

### List assertions

```python
assert_that(response).is_json_list()
assert_that(response).is_json_list().list_length(5)
assert_that(response).is_json_list().list_length_gte(1)
```

### Full chain example

```python
def test_get_user(api_client):
    response = api_client.get("/users/1")

    (
        assert_that(response)
        .status_is(200)
        .content_type_contains("application/json")
        .has_key("id")
        .json_path("$.id").equals(1)
        .json_path("$.name").is_not_none()
        .response_time_under(1000)
    )
```

---

## Logging

The framework logs all HTTP interactions under the `pytest_api_core` logger namespace.

### Log levels

| Level | Output |
|---|---|
| `INFO` | `← GET https://api.myco.com/users/1  200  (143.2 ms)` |
| `DEBUG` | + request headers, request body, response body |
| `WARNING` | Retried requests, SSL warnings |
| `ERROR` | Connection errors, timeouts |

### Configure via `pytest.ini`

```ini
[pytest]
api_log_level = INFO

; Show logs live in the terminal
log_cli       = true
log_cli_level = INFO
log_cli_format = %(asctime)s [%(levelname)s] %(name)s: %(message)s
```

### Override per run via CLI

```bash
pytest tests/ --api-log-level=DEBUG -s
```

(`-s` disables pytest's output capture so logs appear inline.)

### Fine-grained control in `conftest.py`

```python
import logging

def pytest_configure(config):
    # Show only INFO for the HTTP client, suppress auth noise
    logging.getLogger("pytest_api_core.client").setLevel(logging.INFO)
    logging.getLogger("pytest_api_core.auth").setLevel(logging.WARNING)
```

---

## HTML Report

```ini
[pytest]
api_html_report = reports/report.html
```

Or via CLI:

```bash
pytest tests/ --api-html-report=reports/my-run.html
```

Features of the generated report:
- SVG donut chart (pass / fail / skip / error)
- Dark / light mode toggle
- Filterable test table by status
- Expandable failure details with traceback
- Fully self-contained single HTML file (no external dependencies)

---

## GitHub Actions integration

```yaml
- name: Install dependencies
  run: |
    pip install \
      --index-url "https://${{ secrets.PYPI_USERNAME }}:${{ secrets.PYPI_PASSWORD }}@pypi.subodhsingh.in/simple/" \
      "pytest-api-core>=1.0.0" pytest

- name: Run API tests
  run: pytest tests/ -v --api-log-level=INFO
  env:
    API_ENV: staging
    API_BASE_URL: ${{ secrets.STAGING_BASE_URL }}
    API_TOKEN: ${{ secrets.STAGING_API_TOKEN }}

- name: Upload HTML report
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: api-test-report
    path: reports/report.html
```
