"""
Unit tests for the APIClient, APIResponse, assertions, auth, and config.
Uses 'responses' library to mock HTTP calls — no real network needed.
"""

import json
import logging
import re

import pytest
import requests
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
    soft_assertions,
)
from pytest_api_core.auth.auth_handlers import APIKeyAuth, BearerAuth
from pytest_api_core.client.api_client import APIClient, RecordingRetry
from pytest_api_core.config.config_manager import ConfigManager
from pytest_api_core.reporters.html_reporter import (
    _endpoint_stats,
    _render_report,
    _TestRecord,
    _to_curl,
)
from pytest_api_core.security.redaction import REDACTED, register_secret, scrub_text

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

    def test_client_default_retry_policy(self):
        c = APIClient(base_url="https://api.example.com")
        retry = c._session.get_adapter("https://api.example.com").max_retries
        assert retry.total == 3
        assert retry.backoff_factor == 0.3
        assert retry.allowed_methods == {"GET", "HEAD", "OPTIONS"}

    def test_client_custom_retry_primitives(self):
        c = APIClient(
            base_url="https://api.example.com",
            retry_total=5,
            retry_backoff_factor=1.5,
            retry_methods=["GET", "POST"],
        )
        retry = c._session.get_adapter("https://api.example.com").max_retries
        assert retry.total == 5
        assert retry.backoff_factor == 1.5
        assert retry.allowed_methods == {"GET", "POST"}

    def test_client_retry_none_disables_retry(self):
        c = APIClient(base_url="https://api.example.com", retry=None)
        adapter = c._session.get_adapter("https://api.example.com")
        # Default HTTPAdapter's max_retries has total=0 (no retrying)
        assert adapter.max_retries.total == 0

    def test_client_explicit_retry_object_overrides_primitives(self):
        from urllib3.util.retry import Retry

        custom = Retry(total=9)
        c = APIClient(
            base_url="https://api.example.com",
            retry=custom,
            retry_total=1,  # should be ignored since retry= was passed explicitly
        )
        retry = c._session.get_adapter("https://api.example.com").max_retries
        # A plain Retry is converted to RecordingRetry so attempts reach the report,
        # but the caller's policy is kept as-is.
        assert isinstance(retry, RecordingRetry)
        assert retry.total == 9


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

    def test_field_name_and_value_in_sentinel(self, caplog):
        with caplog.at_level("DEBUG", logger="pytest_api_core.assertions"):
            assert_equal("Alice", "Alice", field="user.name")
            assert_contains("hello world", "world", field="greeting")

        eq, contains = _sentinels(caplog, "__API_ASSERT__")
        assert eq["field"] == "user.name"
        assert eq["expected"] == "Alice" and eq["actual"] == "Alice"
        assert contains["field"] == "greeting"
        assert contains["expected_substring"] == "world"

    def test_field_omitted_for_literal_argument(self, caplog):
        with caplog.at_level("DEBUG", logger="pytest_api_core.assertions"):
            assert_equal("a", "a")
        assert "field" not in _sentinels(caplog, "__API_ASSERT__")[0]

    def test_field_inferred_from_first_argument(self, caplog):
        body = {"user": {"name": "Alice"}}
        username = "Alice"
        with caplog.at_level("DEBUG", logger="pytest_api_core.assertions"):
            assert_equal(body["user"]["name"], "Alice")
            assert_contains(
                username,
                "Ali",
            )
        first, second = _sentinels(caplog, "__API_ASSERT__")
        assert first["field"] == 'body["user"]["name"]'
        assert second["field"] == "username"

    def test_inferred_field_in_failure_message(self):
        status = "inactive"
        with pytest.raises(AssertionError, match=r"\[status\] Expected 'active'"):
            assert_equal(status, "active")

    def test_inferred_sensitive_field_masks_values(self, caplog):
        body = {"access_token": "inferred-secret"}
        with caplog.at_level("DEBUG", logger="pytest_api_core.assertions"):
            assert_is_not_empty(body["access_token"])
        result = _sentinels(caplog, "__API_ASSERT__")[0]
        assert result["field"] == 'body["access_token"]'
        assert result["actual"] == REDACTED
        assert "inferred-secret" not in caplog.text

    def test_field_not_inferred_from_inline_literals(self, caplog):
        with caplog.at_level("DEBUG", logger="pytest_api_core.assertions"):
            assert_equal(str({"note": "inline-value"}), str({"note": "inline-value"}))
            assert_matches_schema({"note": "inline-value"}, {"type": "object"})
        assert all("field" not in s for s in _sentinels(caplog, "__API_ASSERT__"))

    def test_explicit_field_overrides_inferred(self, caplog):
        value = "x"
        with caplog.at_level("DEBUG", logger="pytest_api_core.assertions"):
            assert_equal(value, "x", field="custom")
        assert _sentinels(caplog, "__API_ASSERT__")[0]["field"] == "custom"

    def test_field_prefixes_failure_message(self):
        with pytest.raises(AssertionError, match=r"\[user\.name\] Expected 'Alice', got 'Bob'"):
            assert_equal("Bob", "Alice", field="user.name")

    def test_sensitive_field_name_masks_values(self, caplog):
        with caplog.at_level("DEBUG", logger="pytest_api_core.assertions"):
            with pytest.raises(AssertionError) as exc:
                assert_equal("tok-actual", "tok-expected", field="access_token")
        assert "tok-actual" not in str(exc.value) and "tok-actual" not in caplog.text
        result = _sentinels(caplog, "__API_ASSERT__")[0]
        assert result["field"] == "access_token"
        assert result["actual"] == REDACTED and result["expected"] == REDACTED

    @rsps_lib.activate
    def test_has_key_and_has_header_record_value(self, client, caplog):
        rsps_lib.add(
            rsps_lib.GET,
            "https://api.example.com/v",
            json={"name": "Alice", "token": "secret-val"},
            headers={"X-Request-Id": "req-1"},
        )
        resp = client.get("/v")
        with caplog.at_level("DEBUG", logger="pytest_api_core.assertions"):
            assert_that(resp).has_key("name").has_key("token").has_header("X-Request-Id")

        name, token, header = _sentinels(caplog, "__API_ASSERT__")
        assert name["key"] == "name" and name["actual"] == "Alice"
        assert token["actual"] == REDACTED
        assert header["header"] == "X-Request-Id" and header["actual"] == "req-1"
        assert "secret-val" not in caplog.text


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

    def test_config_retry_defaults(self):
        mgr = ConfigManager(env="nonexistent", settings_module=None)
        cfg = mgr.load()
        assert cfg["api_retry_total"] == 3
        assert cfg["api_retry_backoff_factor"] == 0.3
        assert cfg["api_retry_methods"] == ["GET", "HEAD", "OPTIONS"]

    def test_config_retry_settings_module_override(self):
        import sys
        import types

        mod = types.ModuleType("_test_settings_retry")
        from pytest_api_core.config.base_settings import BaseSettings

        class FlakyStagingSettings(BaseSettings):
            api_retry_total = 5
            api_retry_backoff_factor = 1.0

        mod.ENVIRONMENTS = {"staging": FlakyStagingSettings}
        sys.modules["_test_settings_retry"] = mod
        try:
            mgr = ConfigManager(env="staging", settings_module="_test_settings_retry")
            cfg = mgr.load()
            assert cfg["api_retry_total"] == 5
            assert cfg["api_retry_backoff_factor"] == 1.0
            # unspecified retry method list should still fall back to the default
            assert cfg["api_retry_methods"] == ["GET", "HEAD", "OPTIONS"]
        finally:
            del sys.modules["_test_settings_retry"]

    def test_config_retry_cli_override(self):
        mgr = ConfigManager(
            env="nonexistent",
            settings_module=None,
            cli_overrides={"api_retry_total": 7},
        )
        cfg = mgr.load()
        assert cfg["api_retry_total"] == 7

    def test_config_retry_env_var_override(self, monkeypatch):
        monkeypatch.setenv("API_RETRY_TOTAL", "10")
        monkeypatch.setenv("API_RETRY_BACKOFF_FACTOR", "2.5")
        monkeypatch.setenv("API_RETRY_METHODS", "get, post ,put")
        mgr = ConfigManager(env="nonexistent", settings_module=None)
        cfg = mgr.load()
        assert cfg["api_retry_total"] == 10
        assert cfg["api_retry_backoff_factor"] == 2.5
        assert cfg["api_retry_methods"] == ["GET", "POST", "PUT"]

    def test_config_retry_env_var_wins_over_cli_and_settings(self, monkeypatch):
        """Env var (highest priority) should win over a CLI override."""
        monkeypatch.setenv("API_RETRY_TOTAL", "99")
        mgr = ConfigManager(
            env="nonexistent",
            settings_module=None,
            cli_overrides={"api_retry_total": 7},
        )
        cfg = mgr.load()
        assert cfg["api_retry_total"] == 99


# ---------------------------------------------------------------------------
# HTML reporter — setup/teardown phase log capture
# ---------------------------------------------------------------------------

_phase_log = logging.getLogger("pytest_api_core.tests.phase_demo")


@pytest.fixture()
def logging_fixture():
    _phase_log.debug("fixture setup log line")
    yield "ready"
    _phase_log.debug("fixture teardown log line")


class TestReportPhaseLogging:
    pytestmark = pytest.mark.unit

    def test_setup_and_teardown_logs_are_captured(self, logging_fixture):
        """Exercises a fixture that logs during both setup and teardown.

        Used to verify HTMLReporter.pytest_runtest_logreport captures logs from
        all three pytest phases (setup/call/teardown), not just 'call'.
        """
        assert logging_fixture == "ready"


# ---------------------------------------------------------------------------
# Secret redaction — logs, sentinels, assertion messages
# ---------------------------------------------------------------------------


def _sentinels(caplog, marker):
    return [
        json.loads(r.getMessage().split(marker, 1)[1].strip())
        for r in caplog.records
        if marker in r.getMessage()
    ]


class TestSecretRedaction:
    pytestmark = pytest.mark.unit

    TOKEN = "s3cr3t-bearer-token-value"

    @rsps_lib.activate
    def test_api_call_sentinel_and_raw_log_never_contain_tokens(self, caplog):
        rsps_lib.add(
            rsps_lib.POST,
            "https://api.example.com/login",
            json={"access_token": "issued-access-token-123", "user": "alice"},
            headers={"Set-Cookie": "session=cookie-value-xyz"},
            status=200,
        )
        client = APIClient(
            "https://api.example.com",
            auth=BearerAuth(self.TOKEN),
            default_headers={"X-API-Key": "header-api-key-456"},
            retry=None,
        )
        with caplog.at_level("DEBUG", logger="pytest_api_core"):
            client.post(
                "/login?api_key=query-key-789", json={"username": "alice", "password": "hunter22"}
            )

        raw = caplog.text
        for secret in (
            self.TOKEN,
            "issued-access-token-123",
            "cookie-value-xyz",
            "header-api-key-456",
            "query-key-789",
            "hunter22",
        ):
            assert secret not in raw

        call = _sentinels(caplog, "__API_CALL__")[0]
        assert call["req_headers"]["Authorization"] == REDACTED
        assert call["req_headers"]["X-API-Key"] == REDACTED
        assert call["res_headers"]["Set-Cookie"] == REDACTED
        assert "api_key=" in call["url"] and "query-key-789" not in call["url"]
        assert json.loads(call["res_body"]) == {"access_token": REDACTED, "user": "alice"}
        assert json.loads(call["req_body"]) == {"username": "alice", "password": REDACTED}

    @rsps_lib.activate
    def test_key_equals_masks_sensitive_key_in_sentinel_and_error(self, client, caplog):
        rsps_lib.add(rsps_lib.GET, "https://api.example.com/t", json={"access_token": "abc-real-1"})
        resp = client.get("/t")
        with caplog.at_level("DEBUG", logger="pytest_api_core.assertions"):
            with pytest.raises(AssertionError) as exc:
                assert_that(resp).key_equals("access_token", "abc-expected-2")

        assert "abc-real-1" not in str(exc.value)
        assert "abc-expected-2" not in str(exc.value)
        result = _sentinels(caplog, "__API_ASSERT__")[0]
        assert result["actual"] == REDACTED and result["expected"] == REDACTED

    @rsps_lib.activate
    def test_header_equals_masks_sensitive_header(self, client, caplog):
        rsps_lib.add(
            rsps_lib.GET,
            "https://api.example.com/h",
            json={},
            headers={"X-Auth-Token": "resp-header-token"},
        )
        resp = client.get("/h")
        with caplog.at_level("DEBUG", logger="pytest_api_core.assertions"):
            assert_that(resp).header_equals("X-Auth-Token", "resp-header-token")

        assert "resp-header-token" not in caplog.text
        assert _sentinels(caplog, "__API_ASSERT__")[0]["actual"] == REDACTED

    @rsps_lib.activate
    def test_json_path_on_sensitive_path_is_masked(self, client, caplog):
        rsps_lib.add(
            rsps_lib.GET, "https://api.example.com/p", json={"data": {"refreshToken": "rt-999"}}
        )
        resp = client.get("/p")
        with caplog.at_level("DEBUG", logger="pytest_api_core.assertions"):
            assert_that(resp).json_path("$.data.refreshToken").is_not_none()

        assert "rt-999" not in caplog.text
        assert _sentinels(caplog, "__API_ASSERT__")[0]["actual"] == REDACTED

    @rsps_lib.activate
    def test_registered_secret_is_scrubbed_under_non_sensitive_key(self, client, caplog):
        register_secret("leaked-into-plain-field")
        rsps_lib.add(
            rsps_lib.GET, "https://api.example.com/e", json={"echo": "leaked-into-plain-field"}
        )
        resp = client.get("/e")
        with caplog.at_level("DEBUG", logger="pytest_api_core"):
            assert_that(resp).json_path("$.echo").equals("leaked-into-plain-field")

        assert "leaked-into-plain-field" not in caplog.text

    def test_non_sensitive_values_are_not_redacted(self, caplog):
        with caplog.at_level("DEBUG", logger="pytest_api_core.assertions"):
            assert_equal("alice", "alice", field="username")
        result = _sentinels(caplog, "__API_ASSERT__")[0]
        assert result["field"] == "username"
        assert result["actual"] == "alice" and result["expected"] == "alice"

    def test_assert_utils_sensitive_flag_masks_values(self, caplog):
        with caplog.at_level("DEBUG", logger="pytest_api_core.assertions"):
            with pytest.raises(AssertionError) as exc:
                assert_equal("plain-actual", "plain-expected", sensitive=True)
        assert "plain-actual" not in str(exc.value)
        assert "plain-actual" not in caplog.text
        assert "plain-expected" not in caplog.text

    def test_bearer_and_jwt_scrubbed_from_free_text(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl"
        text = scrub_text(f"Authorization: Bearer abc.def-ghi and token {jwt}")
        assert "abc.def-ghi" not in text and jwt not in text

    def test_quoted_sensitive_values_scrubbed_from_traceback_text(self):
        text = scrub_text(
            '            "token": "src-literal-value",\n'
            "instance = {'id': 1, 'token': 'dict-repr-value', 'label': 'kept'}\n"
            'client.login(password="kwarg-value", user="alice")'
        )
        for leaked in ("src-literal-value", "dict-repr-value", "kwarg-value"):
            assert leaked not in text
        assert "'label': 'kept'" in text and 'user="alice"' in text

    def test_schema_error_on_sensitive_field_hides_value(self):
        schema = {"type": "object", "properties": {"password": {"type": "integer"}}}
        with pytest.raises(AssertionError) as exc:
            assert_matches_schema({"password": "pw-should-not-leak"}, schema)
        assert "pw-should-not-leak" not in str(exc.value)

    @rsps_lib.activate
    def test_matches_schema_failure_does_not_chain_raw_validation_error(self, client):
        # Built at runtime so the literal isn't in the source lines the traceback shows.
        secret = "-".join(["pat", "token", "should", "not", "leak"])
        rsps_lib.add(
            rsps_lib.GET,
            "https://api.example.com/pat",
            json={"id": 1, "token": secret},
            status=200,
        )
        schema = {"type": "object", "required": ["label"]}
        resp = client.get("/pat")
        with pytest.raises(AssertionError) as exc:
            assert_that(resp).matches_schema(schema)
        assert exc.value.__cause__ is None
        assert exc.value.__suppress_context__
        assert secret not in str(exc.getrepr(chain=True))


# ---------------------------------------------------------------------------
# Failed requests in the report
# ---------------------------------------------------------------------------


class TestFailedRequestCapture:
    pytestmark = pytest.mark.unit

    @rsps_lib.activate
    def test_timeout_emits_error_sentinel_and_reraises(self, client, caplog):
        rsps_lib.add(
            rsps_lib.GET,
            "https://api.example.com/slow",
            body=requests.exceptions.ConnectTimeout("timed out for token=abc123secret"),
        )
        with caplog.at_level("DEBUG", logger="pytest_api_core.client"):
            with pytest.raises(requests.exceptions.ConnectTimeout):
                client.get("/slow", headers={"Authorization": "Bearer live-bearer-value"})

        call = _sentinels(caplog, "__API_CALL__")[0]
        assert call["status"] is None
        assert call["error"].startswith("ConnectTimeout")
        assert call["method"] == "GET" and call["url"].endswith("/slow")
        assert "abc123secret" not in caplog.text
        assert "live-bearer-value" not in caplog.text

    def test_report_renders_error_banner(self):
        rec = _TestRecord("tests/test_x.py::test_slow")
        rec.outcome = "failed"
        rec.api_calls = [
            {
                "method": "GET",
                "url": "https://api.example.com/slow",
                "req_headers": {},
                "req_body": "",
                "status": None,
                "elapsed_ms": 30001.0,
                "res_headers": {},
                "res_body": "",
                "error": "ReadTimeout: read timed out",
            }
        ]
        html = _render_report(
            [rec], __import__("datetime").datetime.now(), 1.0, "dark", "t", "h", []
        )
        assert "status-err" in html and ">ERROR<" in html
        assert "ReadTimeout: read timed out" in html

    @rsps_lib.activate
    def test_success_sentinel_flags_truncated_body(self, client, caplog):
        rsps_lib.add(rsps_lib.POST, "https://api.example.com/big", json={})
        with caplog.at_level("DEBUG", logger="pytest_api_core.client"):
            client.post("/big", data="x" * 2500)
        call = _sentinels(caplog, "__API_CALL__")[0]
        assert call["req_body_truncated"] is True and len(call["req_body"]) == 2000
        assert "error" not in call


# ---------------------------------------------------------------------------
# cURL export + endpoint performance
# ---------------------------------------------------------------------------


class TestReportExtras:
    pytestmark = pytest.mark.unit

    def test_to_curl_quotes_and_skips_content_length(self):
        cmd = _to_curl(
            {
                "method": "POST",
                "url": "https://api.example.com/users?q=a b",
                "req_headers": {
                    "Authorization": REDACTED,
                    "Content-Type": "application/json",
                    "Content-Length": "17",
                },
                "req_body": '{"name": "O\'Brien"}',
            }
        )
        assert cmd.startswith("curl -X POST 'https://api.example.com/users?q=a b'")
        assert f"-H 'Authorization: {REDACTED}'" in cmd
        assert "Content-Length" not in cmd
        assert '--data-raw \'{"name": "O\'"\'"\'Brien"}\'' in cmd
        assert "truncated" not in cmd

    def test_to_curl_notes_truncated_body(self):
        cmd = _to_curl({"method": "POST", "url": "u", "req_body": "x", "req_body_truncated": True})
        assert cmd.endswith("# body truncated in report")

    def test_endpoint_stats_groups_ids_and_computes_percentiles(self):
        rec = _TestRecord("t::a")
        rec.api_calls = [
            {
                "method": "GET",
                "url": f"https://h/users/{i}?x=1",
                "status": 200,
                "elapsed_ms": float(i),
            }
            for i in range(1, 21)
        ] + [
            {
                "method": "GET",
                "url": "https://h/users/3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "status": None,
                "elapsed_ms": 5.0,
                "error": "ConnectionError: x",
            },
            {"method": "POST", "url": "https://h/users", "status": 503, "elapsed_ms": 900.0},
        ]
        stats = {(s["method"], s["endpoint"]): s for s in _endpoint_stats([rec])}
        users = stats[("GET", "/users/{id}")]
        assert users["count"] == 21 and users["errors"] == 1
        assert users["min"] == 1.0 and users["max"] == 20.0
        assert users["p50"] == 10.0 and users["p95"] == 19.0
        assert stats[("POST", "/users")]["errors"] == 1
        # slowest p95 first
        assert _endpoint_stats([rec])[0]["endpoint"] == "/users"


# ---------------------------------------------------------------------------
# json_path matchers
# ---------------------------------------------------------------------------

_BODY = {
    "name": "Alice",
    "age": 30,
    "active": True,
    "tags": ["a", "b"],
    "meta": {"k": 1},
    "empty": [],
    "nothing": None,
    "data": {"token": "tok-secret-1"},
}


class TestJsonPathMatchers:
    pytestmark = pytest.mark.unit

    @pytest.fixture()
    def resp(self, client):
        with rsps_lib.RequestsMock() as rsps:
            rsps.add(rsps_lib.GET, "https://api.example.com/m", json=_BODY)
            yield client.get("/m")

    @pytest.mark.parametrize(
        "path, matcher, args",
        [
            ("$.name", "not_equals", ("Bob",)),
            ("$.name", "is_type", ("string",)),
            ("$.age", "is_type", (int,)),
            ("$.age", "is_type", ("number",)),
            ("$.nothing", "is_type", ("null",)),
            ("$.active", "is_type", (bool,)),
            ("$.name", "contains", ("lic",)),
            ("$.tags", "contains", ("b",)),
            ("$.meta", "contains", ("k",)),
            ("$.name", "is_in", (["Alice", "Bob"],)),
            ("$.tags", "has_length", (2,)),
            ("$.empty", "is_empty", ()),
            ("$.tags", "is_not_empty", ()),
            ("$.age", "greater_than", (18,)),
            ("$.age", "less_than", (31,)),
            ("$.age", "between", (30, 30)),
        ],
    )
    def test_matcher_passes(self, resp, path, matcher, args):
        getattr(assert_that(resp).json_path(path), matcher)(*args)

    @pytest.mark.parametrize(
        "path, matcher, args, message",
        [
            ("$.name", "not_equals", ("Alice",), "to differ"),
            ("$.active", "is_type", ("integer",), "type integer, got boolean"),
            ("$.active", "is_type", (int,), "type int, got boolean"),
            ("$.name", "contains", ("zzz",), "to contain"),
            ("$.age", "contains", (3,), "got integer"),
            ("$.name", "is_in", (["Bob"],), "one of"),
            ("$.tags", "has_length", (3,), "length 3, got 2"),
            ("$.age", "has_length", (1,), "got <integer>"),
            ("$.tags", "is_empty", (), "to be empty"),
            ("$.empty", "is_not_empty", (), "non-empty"),
            ("$.age", "greater_than", (30,), "> 30"),
            ("$.age", "less_than", (30,), "< 30"),
            ("$.age", "between", (31, 40), "in [31, 40]"),
            ("$.name", "greater_than", (1,), "got string"),
        ],
    )
    def test_matcher_fails(self, resp, path, matcher, args, message):
        with pytest.raises(AssertionError, match=re.escape(message)):
            getattr(assert_that(resp).json_path(path), matcher)(*args)

    def test_unknown_json_type_name_raises_value_error(self, resp):
        with pytest.raises(ValueError, match="Unknown JSON type"):
            assert_that(resp).json_path("$.name").is_type("str")

    def test_matcher_requires_json_path_first(self, resp):
        with pytest.raises(RuntimeError, match=r"before \.contains\(\)"):
            assert_that(resp).contains("x")

    def test_has_path_and_not_has_path(self, resp):
        assert_that(resp).has_path("$.tags[1]").has_path("$.nothing").not_has_path("$.missing")
        with pytest.raises(AssertionError, match="to exist"):
            assert_that(resp).has_path("$.tags[5]")
        with pytest.raises(AssertionError, match="to be absent"):
            assert_that(resp).not_has_path("$.name")

    def test_sensitive_path_values_masked(self, resp, caplog):
        with caplog.at_level("DEBUG", logger="pytest_api_core.assertions"):
            with pytest.raises(AssertionError) as exc:
                assert_that(resp).json_path("$.data.token").contains("nope")
            with pytest.raises(AssertionError):
                assert_that(resp).json_path("$.data.token").greater_than(1)
        assert "tok-secret-1" not in caplog.text and "tok-secret-1" not in str(exc.value)
        assert all(s["actual"] == REDACTED for s in _sentinels(caplog, "__API_ASSERT__"))


# ---------------------------------------------------------------------------
# Soft assertions
# ---------------------------------------------------------------------------


class TestSoftAssertions:
    pytestmark = pytest.mark.unit

    @pytest.fixture()
    def resp(self, client):
        with rsps_lib.RequestsMock() as rsps:
            rsps.add(rsps_lib.GET, "https://api.example.com/s", json={"name": "Alice", "age": 30})
            yield client.get("/s")

    def test_collects_all_failures_and_raises_once(self, resp, caplog):
        with caplog.at_level("DEBUG", logger="pytest_api_core.assertions"):
            with pytest.raises(AssertionError) as exc:
                with soft_assertions():
                    assert_that(resp).status_is(404).json_path("$.name").equals("Bob")
                    assert_that(resp).json_path("$.age").greater_than(40)
                    assert_equal("x", "y", field="other")
        text = str(exc.value)
        assert text.startswith("4 soft assertion(s) failed:")
        for fragment in ("Expected status 404", "'Bob'", "> 40", "[other]"):
            assert fragment in text
        # every assertion still reaches the report
        assert [s["passed"] for s in _sentinels(caplog, "__API_ASSERT__")] == [False] * 4

    def test_passing_block_does_not_raise(self, resp):
        with soft_assertions():
            assert_that(resp).status_is(200).json_path("$.name").equals("Alice")

    def test_failed_json_path_reported_once(self, resp):
        with pytest.raises(AssertionError) as exc:
            with soft_assertions():
                assert_that(resp).json_path("$.missing.deep").equals(1).has_key("name")
        assert str(exc.value).startswith("1 soft assertion(s) failed:")
        assert "missing" in str(exc.value)

    def test_nested_blocks_raise_once_from_outer(self):
        with pytest.raises(AssertionError) as exc:
            with soft_assertions():
                with soft_assertions():
                    assert_equal("a", "b")
                assert_equal("c", "d")
        assert str(exc.value).startswith("2 soft assertion(s) failed:")

    def test_other_exception_propagates_unchanged(self):
        with pytest.raises(KeyError):
            with soft_assertions():
                assert_equal("a", "b")
                raise KeyError("boom")

    def test_hard_mode_unchanged_outside_block(self, resp):
        with pytest.raises(AssertionError, match="Expected status 404"):
            assert_that(resp).status_is(404).json_path("$.name").equals("Bob")


# ---------------------------------------------------------------------------
# Report polish (1.1.1)
# ---------------------------------------------------------------------------


class TestReportPolish:
    pytestmark = pytest.mark.unit

    def test_soft_assertion_traceback_hides_framework_frames(self, tmp_path):
        import subprocess
        import sys

        test_file = tmp_path / "test_soft_tb.py"
        test_file.write_text(
            "from pytest_api_core.assertions import assert_equal, soft_assertions\n"
            "\n"
            "def test_it():\n"
            "    with soft_assertions():\n"
            "        assert_equal('a', 'b')\n"
        )
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file), "-p", "no:cacheprovider", "-q"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        out = result.stdout
        assert "1 soft assertion(s) failed" in out
        assert "with soft_assertions():" in out
        assert "contextlib" not in out
        assert "_collector" not in out  # soft.py internals not shown

    def test_soft_assertions_still_nest_and_propagate(self):
        with pytest.raises(AssertionError, match="2 soft assertion"):
            with soft_assertions():
                with soft_assertions():
                    assert_equal("a", "b")
                assert_equal("c", "d")
        with pytest.raises(KeyError):
            with soft_assertions():
                assert_equal("a", "b")
                raise KeyError("boom")
        with soft_assertions():  # reusable after a failure: no leftover state
            assert_equal("x", "x")

    def _render(self, assertions, theme="dark"):
        rec = _TestRecord("t::a")
        rec.outcome = "passed"
        rec.assertions = assertions
        return _render_report(
            [rec], __import__("datetime").datetime.now(), 0.1, theme, "t", "h", []
        )

    def test_actual_value_not_red_on_passed_assertion(self):
        html = self._render(
            [
                {"name": "status_is", "passed": True, "expected": 200, "actual": 200},
                {"name": "status_is", "passed": False, "expected": 201, "actual": 200},
            ]
        )
        assert 'actual=<span class="exp">200</span>' in html
        assert 'actual=<span class="got">200</span>' in html

    @pytest.mark.parametrize("theme, label", [("dark", "☀️ Light"), ("light", "🌙 Dark")])
    def test_theme_button_label_names_target_theme(self, theme, label):
        html = self._render([], theme=theme)
        assert f'id="themeBtn" onclick="toggleTheme()">{label}</button>' in html
        assert "getElementById('themeBtn')" in html
        assert "querySelector('.theme-btn').textContent" not in html

    def test_token_type_is_not_redacted(self):
        from pytest_api_core.security.redaction import is_sensitive_key, redact

        body = redact({"access_token": "real-secret", "token_type": "Bearer", "expires_in": 60})
        assert body == {"access_token": REDACTED, "token_type": "Bearer", "expires_in": 60}
        assert not is_sensitive_key("TOKEN-TYPE")
        for key in ("x-token-type", "refresh_token", "id_token", "token"):
            assert is_sensitive_key(key), key
        text = scrub_text('{"token_type": "Bearer", "access_token": "abc.def"}')
        assert '"token_type": "Bearer"' in text and "abc.def" not in text

    def test_add_sensitive_keys_overrides_safe_list(self):
        from pytest_api_core.security import redaction

        try:
            redaction.add_sensitive_keys("token_type")
            assert redaction.is_sensitive_key("token_type")
        finally:
            redaction._extra_keys.discard("tokentype")


# ---------------------------------------------------------------------------
# Retry visibility + configurable retry statuses
# ---------------------------------------------------------------------------

_FLAKY = "https://api.example.com/flaky"


def _report_html(calls):
    rec = _TestRecord("tests/test_x.py::test_flaky")
    rec.outcome = "passed"
    rec.api_calls = calls
    return _render_report([rec], __import__("datetime").datetime.now(), 1.0, "dark", "t", "h", [])


class TestRetryVisibility:
    pytestmark = pytest.mark.unit

    @rsps_lib.activate(registry=rsps_lib.registries.OrderedRegistry)
    def test_call_that_passes_on_retry_is_shown_in_report(self, caplog):
        """A 503 -> 200 call must not look like a single clean 200."""
        rsps_lib.get(_FLAKY, status=503, json={"error": "unavailable"})
        rsps_lib.get(_FLAKY, status=200, json={"ok": True})
        client = APIClient("https://api.example.com", retry_backoff_factor=0)

        with caplog.at_level("DEBUG", logger="pytest_api_core.client"):
            resp = client.get("/flaky")

        assert resp.status_code == 200
        assert len(rsps_lib.calls) == 2

        call = _sentinels(caplog, "__API_CALL__")[0]
        assert call["status"] == 200
        assert [(r["attempt"], r["status"]) for r in call["retries"]] == [(1, 503)]
        assert 0 <= call["retries"][0]["at_ms"] <= call["elapsed_ms"]

        # Raw logs: one WARNING per retried attempt, in order, before the final line.
        messages = [r.getMessage() for r in caplog.records if r.name == "pytest_api_core.client"]
        warn = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warn) == 1
        assert warn[0].getMessage() == f"↻ GET {_FLAKY}  503  — attempt 1 failed, retrying"
        assert messages.index(warn[0].getMessage()) < next(
            i for i, m in enumerate(messages) if m.startswith("← GET")
        )

        html = _report_html([call])
        assert "↻ 2 attempts" in html
        assert "Attempts (2)" in html
        assert "503 — retried" in html and "200 — final" in html
        assert "Retried calls" in html

    @rsps_lib.activate
    def test_call_without_retry_has_no_retry_markup(self, caplog):
        rsps_lib.get(_FLAKY, status=200, json={})
        client = APIClient("https://api.example.com", retry_backoff_factor=0)
        with caplog.at_level("DEBUG", logger="pytest_api_core.client"):
            client.get("/flaky")
        call = _sentinels(caplog, "__API_CALL__")[0]
        assert "retries" not in call
        html = _report_html([call])
        assert "retry-chip" not in html.split("</style>", 1)[1]
        assert "Retried calls" not in html

    @rsps_lib.activate(registry=rsps_lib.registries.OrderedRegistry)
    def test_exhausted_retries_return_final_status_with_all_attempts(self, caplog):
        for _ in range(3):
            rsps_lib.get(_FLAKY, status=502)
        client = APIClient("https://api.example.com", retry_total=2, retry_backoff_factor=0)
        with caplog.at_level("DEBUG", logger="pytest_api_core.client"):
            resp = client.get("/flaky")
        assert resp.status_code == 502
        call = _sentinels(caplog, "__API_CALL__")[0]
        assert [r["status"] for r in call["retries"]] == [502, 502]
        assert "502 — final" in _report_html([call])

    def test_connection_error_attempt_is_recorded_and_scrubbed(self):
        # `responses` raises connection errors above urllib3, so drive increment() directly.
        from urllib3.exceptions import NewConnectionError

        from pytest_api_core.client import api_client as mod

        attempts: list = []
        token = mod._retry_attempts.set(attempts)
        try:
            RecordingRetry(total=2).increment(
                "GET", "/flaky", error=NewConnectionError(None, "refused token=abc123secret")
            )
        finally:
            mod._retry_attempts.reset(token)
        (entry,) = attempts
        assert entry["status"] is None
        assert entry["error"].startswith("NewConnectionError")
        assert "abc123secret" not in entry["error"]

    def test_real_urllib3_retry_against_local_server(self, caplog):
        """No mocks: a real HTTP server returns 503 then 200 over localhost."""
        import http.server
        import threading

        hits = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                hits.append(self.path)
                status = 503 if len(hits) == 1 else 200
                self.send_response(status)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            client = APIClient(f"http://127.0.0.1:{server.server_port}", retry_backoff_factor=0)
            with caplog.at_level("DEBUG", logger="pytest_api_core.client"):
                assert client.get("/flaky").status_code == 200
        finally:
            server.shutdown()
            server.server_close()
        assert len(hits) == 2
        call = _sentinels(caplog, "__API_CALL__")[0]
        assert [r["status"] for r in call["retries"]] == [503]

    @rsps_lib.activate(registry=rsps_lib.registries.OrderedRegistry)
    def test_429_not_retried_by_default(self, caplog):
        rsps_lib.get(_FLAKY, status=429)
        rsps_lib.get(_FLAKY, status=200)
        client = APIClient("https://api.example.com", retry_backoff_factor=0)
        with caplog.at_level("DEBUG", logger="pytest_api_core.client"):
            resp = client.get("/flaky")
        assert resp.status_code == 429
        assert len(rsps_lib.calls) == 1
        assert "retries" not in _sentinels(caplog, "__API_CALL__")[0]

    @rsps_lib.activate(registry=rsps_lib.registries.OrderedRegistry)
    def test_custom_retry_statuses_retry_429_but_not_500(self, caplog):
        rsps_lib.get(_FLAKY, status=429)
        rsps_lib.get(_FLAKY, status=200)
        rsps_lib.get("https://api.example.com/boom", status=500)
        client = APIClient("https://api.example.com", retry_backoff_factor=0, retry_statuses=[429])
        assert client.get("/flaky").status_code == 200
        assert client.get("/boom").status_code == 500
        assert len(rsps_lib.calls) == 3  # 429 + 200 retried; 500 not retried

    @rsps_lib.activate(registry=rsps_lib.registries.OrderedRegistry)
    def test_post_not_retried_by_default(self):
        rsps_lib.post(_FLAKY, status=503)
        rsps_lib.post(_FLAKY, status=200)
        client = APIClient("https://api.example.com", retry_backoff_factor=0)
        assert client.post("/flaky", json={}).status_code == 503
        assert len(rsps_lib.calls) == 1

    @rsps_lib.activate(registry=rsps_lib.registries.OrderedRegistry)
    def test_plain_retry_object_still_records_attempts(self, caplog):
        from urllib3.util.retry import Retry

        rsps_lib.get(_FLAKY, status=418)
        rsps_lib.get(_FLAKY, status=200)
        client = APIClient(
            "https://api.example.com",
            retry=Retry(total=1, status_forcelist=[418], raise_on_status=False),
        )
        with caplog.at_level("DEBUG", logger="pytest_api_core.client"):
            assert client.get("/flaky").status_code == 200
        assert _sentinels(caplog, "__API_CALL__")[0]["retries"][0]["status"] == 418

    def test_client_default_retry_statuses(self):
        c = APIClient("https://api.example.com")
        retry = c._session.get_adapter("https://api.example.com").max_retries
        assert retry.status_forcelist == {500, 502, 503, 504}

    def test_endpoint_stats_count_retried_calls(self):
        rec = _TestRecord("t::a")
        rec.api_calls = [
            {
                "method": "GET",
                "url": "https://h/users/1",
                "status": 200,
                "elapsed_ms": 5.0,
                "retries": [{"attempt": 1, "status": 503, "at_ms": 2.0}],
            },
            {"method": "GET", "url": "https://h/users/2", "status": 200, "elapsed_ms": 3.0},
        ]
        (stat,) = _endpoint_stats([rec])
        assert stat["retried"] == 1 and stat["errors"] == 0


class TestRetryStatusConfig:
    pytestmark = pytest.mark.unit

    def test_default(self):
        assert ConfigManager(env="dev").load()["api_retry_statuses"] == [500, 502, 503, 504]

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("API_RETRY_STATUSES", "429, 503,504")
        assert ConfigManager(env="dev").load()["api_retry_statuses"] == [429, 503, 504]

    def test_env_var_rejects_non_integers(self, monkeypatch):
        monkeypatch.setenv("API_RETRY_STATUSES", "429,abc")
        with pytest.raises(ValueError, match="comma-separated integers"):
            ConfigManager(env="dev").load()

    def test_cli_and_settings(self):
        import sys
        import types

        from pytest_api_core.config.base_settings import BaseSettings

        mod = types.ModuleType("_test_settings_statuses")

        class Staging(BaseSettings):
            api_retry_statuses = [429, 503]

        mod.ENVIRONMENTS = {"staging": Staging}  # type: ignore[attr-defined]
        sys.modules["_test_settings_statuses"] = mod
        try:
            cfg = ConfigManager(env="staging", settings_module="_test_settings_statuses").load()
            assert cfg["api_retry_statuses"] == [429, 503]
            cfg = ConfigManager(
                env="staging",
                settings_module="_test_settings_statuses",
                cli_overrides={"api_retry_statuses": [502]},
            ).load()
            assert cfg["api_retry_statuses"] == [502]
        finally:
            del sys.modules["_test_settings_statuses"]
