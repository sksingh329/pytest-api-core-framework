"""
Unit tests for the APIClient, APIResponse, assertions, auth, and config.
Uses 'responses' library to mock HTTP calls — no real network needed.
"""

import json

import pytest
import responses as rsps_lib

from pytest_api_core.assertions import (
    assert_contains,
    assert_equal,
    assert_equal_ignore_case,
    assert_is_empty,
    assert_is_not_empty,
    assert_matches,
    assert_matches_schema,
    assert_not_equal,
    assert_that,
)
from pytest_api_core.auth.auth_handlers import APIKeyAuth, BearerAuth
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


class TestAPIClient:
    pytestmark = pytest.mark.unit

    @rsps_lib.activate
    def test_client_get(self, client):
        rsps_lib.add(rsps_lib.GET, "https://api.example.com/items", json={"id": 1}, status=200)
        resp = client.get("/items")
        assert resp.status_code == 200
        assert resp.json() == {"id": 1}

    @rsps_lib.activate
    def test_client_post(self, client):
        rsps_lib.add(rsps_lib.POST, "https://api.example.com/items", json={"id": 2}, status=201)
        resp = client.post("/items", json={"name": "test"})
        assert resp.status_code == 201

    @rsps_lib.activate
    def test_client_resolves_absolute_url(self, client):
        rsps_lib.add(rsps_lib.GET, "https://other.example.com/data", json={}, status=200)
        resp = client.get("https://other.example.com/data")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Assertions — happy paths
# ---------------------------------------------------------------------------


class TestAssertionsHappyPath:
    pytestmark = pytest.mark.unit

    @rsps_lib.activate
    def test_assertion_status_is(self, client):
        rsps_lib.add(rsps_lib.GET, "https://api.example.com/ok", json={}, status=200)
        resp = client.get("/ok")
        assert_that(resp).status_is(200)

    @rsps_lib.activate
    def test_assertion_has_key(self, client):
        rsps_lib.add(
            rsps_lib.GET,
            "https://api.example.com/user",
            json={"id": 1, "name": "Alice"},
            status=200,
        )
        resp = client.get("/user")
        assert_that(resp).has_key("id").has_key("name")

    @rsps_lib.activate
    def test_assertion_json_path(self, client):
        rsps_lib.add(
            rsps_lib.GET, "https://api.example.com/user", json={"user": {"id": 42}}, status=200
        )
        resp = client.get("/user")
        assert_that(resp).json_path("$.user.id").equals(42)

    @rsps_lib.activate
    def test_assertion_json_path_array(self, client):
        rsps_lib.add(
            rsps_lib.GET, "https://api.example.com/items", json=[{"id": 1}, {"id": 2}], status=200
        )
        resp = client.get("/items")
        assert_that(resp).json_path("$[0].id").equals(1)

    @rsps_lib.activate
    def test_assertion_is_success(self, client):
        rsps_lib.add(rsps_lib.GET, "https://api.example.com/ok", json={}, status=200)
        resp = client.get("/ok")
        assert_that(resp).is_success()

    @rsps_lib.activate
    def test_assertion_response_time_under(self, client):
        rsps_lib.add(rsps_lib.GET, "https://api.example.com/fast", json={}, status=200)
        resp = client.get("/fast")
        assert_that(resp).response_time_under(10_000)  # 10 seconds — always passes in mocked tests


# ---------------------------------------------------------------------------
# Assertions — failure paths
# ---------------------------------------------------------------------------


class TestAssertionsFailurePaths:
    pytestmark = pytest.mark.unit

    @rsps_lib.activate
    def test_assertion_status_is_fails(self, client):
        rsps_lib.add(rsps_lib.GET, "https://api.example.com/bad", json={}, status=404)
        resp = client.get("/bad")
        with pytest.raises(AssertionError, match="Expected status 200"):
            assert_that(resp).status_is(200)

    @rsps_lib.activate
    def test_assertion_missing_key_fails(self, client):
        rsps_lib.add(rsps_lib.GET, "https://api.example.com/user", json={"id": 1}, status=200)
        resp = client.get("/user")
        with pytest.raises(AssertionError, match="name"):
            assert_that(resp).has_key("name")


# ---------------------------------------------------------------------------
# Generic assert utils
# ---------------------------------------------------------------------------


class TestAssertUtils:
    pytestmark = pytest.mark.unit

    def test_assert_equal_passes(self):
        assert_equal("hello", "hello")

    def test_assert_equal_fails(self):
        with pytest.raises(AssertionError, match="Expected 'hello'"):
            assert_equal("world", "hello")

    def test_assert_not_equal_passes(self):
        assert_not_equal("world", "hello")

    def test_assert_not_equal_fails(self):
        with pytest.raises(AssertionError, match="Expected value to differ"):
            assert_not_equal("hello", "hello")

    def test_assert_equal_ignore_case_passes(self):
        assert_equal_ignore_case("HELLO", "hello")

    def test_assert_equal_ignore_case_fails(self):
        with pytest.raises(AssertionError, match="case-insensitive"):
            assert_equal_ignore_case("world", "hello")

    def test_assert_contains_passes(self):
        assert_contains("hello world", "world")

    def test_assert_contains_fails(self):
        with pytest.raises(AssertionError, match="to contain"):
            assert_contains("hello world", "missing")

    def test_assert_matches_passes(self):
        assert_matches("abc123", r"^\w+\d+$")

    def test_assert_matches_fails(self):
        with pytest.raises(AssertionError, match="to match"):
            assert_matches("abc", r"^\d+$")

    def test_assert_is_empty_passes(self):
        assert_is_empty("")

    def test_assert_is_empty_fails(self):
        with pytest.raises(AssertionError, match="Expected empty string"):
            assert_is_empty("not empty")

    def test_assert_is_not_empty_passes(self):
        assert_is_not_empty("not empty")

    def test_assert_is_not_empty_fails(self):
        with pytest.raises(AssertionError, match="Expected non-empty string"):
            assert_is_not_empty("")

    def test_assert_equal_custom_message(self):
        with pytest.raises(AssertionError, match="Usernames must match"):
            assert_equal("bob", "alice", message="Usernames must match")

    def test_assert_matches_schema_passes(self):
        schema = {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        }
        assert_matches_schema({"id": 42}, schema)

    def test_assert_matches_schema_fails_with_all_errors(self):
        schema = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
            "required": ["id", "name"],
        }
        with pytest.raises(AssertionError, match="2 error\\(s\\)"):
            assert_matches_schema({"id": "not-an-int"}, schema)

    def test_assert_matches_schema_custom_message(self):
        schema = {"type": "object", "required": ["id"]}
        with pytest.raises(AssertionError, match="Payload must include id"):
            assert_matches_schema({}, schema, message="Payload must include id")

    def test_assert_matches_schema_sentinel_includes_schema_and_actual(self, caplog):
        schema = {"type": "object", "required": ["id"]}
        with caplog.at_level("DEBUG", logger="pytest_api_core.assertions"):
            assert_matches_schema({"id": 1}, schema)

        sentinel_line = next(r for r in caplog.records if "__API_ASSERT__" in r.message)
        payload = json.loads(sentinel_line.message.split("__API_ASSERT__", 1)[1].strip())
        assert json.loads(payload["schema"]) == schema
        assert json.loads(payload["actual"]) == {"id": 1}


# ---------------------------------------------------------------------------
# Auth handlers
# ---------------------------------------------------------------------------


class TestAuthHandlers:
    pytestmark = pytest.mark.unit

    @rsps_lib.activate
    def test_bearer_auth_injects_header(self):
        rsps_lib.add(rsps_lib.GET, "https://api.example.com/secure", json={}, status=200)
        client = APIClient("https://api.example.com", auth=BearerAuth("my-token"), retry=None)
        client.get("/secure")
        assert rsps_lib.calls[0].request.headers["Authorization"] == "Bearer my-token"

    @rsps_lib.activate
    def test_api_key_header_auth(self):
        rsps_lib.add(rsps_lib.GET, "https://api.example.com/secure", json={}, status=200)
        client = APIClient(
            "https://api.example.com", auth=APIKeyAuth("x-api-key", "secret"), retry=None
        )
        client.get("/secure")
        assert rsps_lib.calls[0].request.headers["x-api-key"] == "secret"


# ---------------------------------------------------------------------------
# Config manager
# ---------------------------------------------------------------------------


class TestConfigManager:
    pytestmark = pytest.mark.unit

    def test_config_defaults_only(self):
        """ConfigManager returns defaults when no settings_module is configured."""
        mgr = ConfigManager(env="nonexistent", settings_module=None)
        cfg = mgr.load()
        assert cfg["base_url"] == "http://localhost"
        assert cfg["timeout"] == 30

    def test_config_loads_yaml(self, tmp_path):
        """ConfigManager loads settings from a settings module."""
        import sys
        import types

        mod = types.ModuleType("_test_settings")
        from pytest_api_core.config.base_settings import BaseSettings

        class TestEnvSettings(BaseSettings):
            base_url = "https://test.example.com"
            timeout = 60

        mod.ENVIRONMENTS = {"test": TestEnvSettings}
        sys.modules["_test_settings"] = mod
        try:
            mgr = ConfigManager(env="test", settings_module="_test_settings")
            cfg = mgr.load()
            assert cfg["base_url"] == "https://test.example.com"
            assert cfg["timeout"] == 60
        finally:
            del sys.modules["_test_settings"]

    def test_config_env_var_override(self, monkeypatch):
        import sys
        import types

        mod = types.ModuleType("_test_settings_override")
        from pytest_api_core.config.base_settings import BaseSettings

        class DevSettings(BaseSettings):
            base_url = "https://dev.example.com"

        mod.ENVIRONMENTS = {"dev": DevSettings}
        sys.modules["_test_settings_override"] = mod
        monkeypatch.setenv("API_BASE_URL", "https://override.example.com")
        try:
            mgr = ConfigManager(env="dev", settings_module="_test_settings_override")
            cfg = mgr.load()
            assert cfg["base_url"] == "https://override.example.com"
        finally:
            del sys.modules["_test_settings_override"]
