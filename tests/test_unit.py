"""
Unit tests for the APIClient, APIResponse, assertions, auth, and config.
Uses 'responses' library to mock HTTP calls — no real network needed.
"""
import pytest
import responses as rsps_lib
from responses import matchers

from pytest_api_core.assertions import assert_that
from pytest_api_core.auth.auth_handlers import APIKeyAuth, BasicAuth, BearerAuth
from pytest_api_core.client.api_client import APIClient
from pytest_api_core.config.config_manager import ConfigManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    return APIClient(base_url="https://api.example.com", retry=None)


# ---------------------------------------------------------------------------
# APIClient
# ---------------------------------------------------------------------------


@rsps_lib.activate
def test_client_get(client):
    rsps_lib.add(rsps_lib.GET, "https://api.example.com/items", json={"id": 1}, status=200)
    resp = client.get("/items")
    assert resp.status_code == 200
    assert resp.json() == {"id": 1}


@rsps_lib.activate
def test_client_post(client):
    rsps_lib.add(rsps_lib.POST, "https://api.example.com/items", json={"id": 2}, status=201)
    resp = client.post("/items", json={"name": "test"})
    assert resp.status_code == 201


@rsps_lib.activate
def test_client_resolves_absolute_url(client):
    rsps_lib.add(rsps_lib.GET, "https://other.example.com/data", json={}, status=200)
    resp = client.get("https://other.example.com/data")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Assertions — happy paths
# ---------------------------------------------------------------------------


@rsps_lib.activate
def test_assertion_status_is(client):
    rsps_lib.add(rsps_lib.GET, "https://api.example.com/ok", json={}, status=200)
    resp = client.get("/ok")
    assert_that(resp).status_is(200)


@rsps_lib.activate
def test_assertion_has_key(client):
    rsps_lib.add(rsps_lib.GET, "https://api.example.com/user", json={"id": 1, "name": "Alice"}, status=200)
    resp = client.get("/user")
    assert_that(resp).has_key("id").has_key("name")


@rsps_lib.activate
def test_assertion_json_path(client):
    rsps_lib.add(rsps_lib.GET, "https://api.example.com/user", json={"user": {"id": 42}}, status=200)
    resp = client.get("/user")
    assert_that(resp).json_path("$.user.id").equals(42)


@rsps_lib.activate
def test_assertion_json_path_array(client):
    rsps_lib.add(rsps_lib.GET, "https://api.example.com/items", json=[{"id": 1}, {"id": 2}], status=200)
    resp = client.get("/items")
    assert_that(resp).json_path("$[0].id").equals(1)


@rsps_lib.activate
def test_assertion_is_success(client):
    rsps_lib.add(rsps_lib.GET, "https://api.example.com/ok", json={}, status=200)
    resp = client.get("/ok")
    assert_that(resp).is_success()


@rsps_lib.activate
def test_assertion_response_time_under(client):
    rsps_lib.add(rsps_lib.GET, "https://api.example.com/fast", json={}, status=200)
    resp = client.get("/fast")
    assert_that(resp).response_time_under(10_000)  # 10 seconds — always passes in mocked tests


# ---------------------------------------------------------------------------
# Assertions — failure paths
# ---------------------------------------------------------------------------


@rsps_lib.activate
def test_assertion_status_is_fails(client):
    rsps_lib.add(rsps_lib.GET, "https://api.example.com/bad", json={}, status=404)
    resp = client.get("/bad")
    with pytest.raises(AssertionError, match="Expected status 200"):
        assert_that(resp).status_is(200)


@rsps_lib.activate
def test_assertion_missing_key_fails(client):
    rsps_lib.add(rsps_lib.GET, "https://api.example.com/user", json={"id": 1}, status=200)
    resp = client.get("/user")
    with pytest.raises(AssertionError, match="name"):
        assert_that(resp).has_key("name")


# ---------------------------------------------------------------------------
# Auth handlers
# ---------------------------------------------------------------------------


@rsps_lib.activate
def test_bearer_auth_injects_header():
    rsps_lib.add(rsps_lib.GET, "https://api.example.com/secure", json={}, status=200)
    client = APIClient("https://api.example.com", auth=BearerAuth("my-token"), retry=None)
    client.get("/secure")
    assert rsps_lib.calls[0].request.headers["Authorization"] == "Bearer my-token"


@rsps_lib.activate
def test_api_key_header_auth():
    rsps_lib.add(rsps_lib.GET, "https://api.example.com/secure", json={}, status=200)
    client = APIClient("https://api.example.com", auth=APIKeyAuth("x-api-key", "secret"), retry=None)
    client.get("/secure")
    assert rsps_lib.calls[0].request.headers["x-api-key"] == "secret"


# ---------------------------------------------------------------------------
# Config manager
# ---------------------------------------------------------------------------


def test_config_defaults_only(tmp_path):
    """ConfigManager returns defaults when no YAML file is found."""
    mgr = ConfigManager(env="nonexistent", config_dir=str(tmp_path))
    cfg = mgr.load()
    assert cfg["base_url"] == "http://localhost"
    assert cfg["timeout"] == 30


def test_config_loads_yaml(tmp_path):
    yaml_file = tmp_path / "test.yaml"
    yaml_file.write_text("base_url: https://test.example.com\ntimeout: 60\n")
    mgr = ConfigManager(env="test", config_dir=str(tmp_path))
    cfg = mgr.load()
    assert cfg["base_url"] == "https://test.example.com"
    assert cfg["timeout"] == 60


def test_config_env_var_override(tmp_path, monkeypatch):
    yaml_file = tmp_path / "dev.yaml"
    yaml_file.write_text("base_url: https://dev.example.com\n")
    monkeypatch.setenv("API_BASE_URL", "https://override.example.com")
    mgr = ConfigManager(env="dev", config_dir=str(tmp_path))
    cfg = mgr.load()
    assert cfg["base_url"] == "https://override.example.com"
