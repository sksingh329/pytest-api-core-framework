"""
pytest-api-core: Reusable API automation framework for pytest.
Auto-registered as a pytest plugin via entry_points["pytest11"].
"""

from pytest_api_core.assertions.assert_utils import (
    assert_contains,
    assert_equal,
    assert_equal_ignore_case,
    assert_is_empty,
    assert_is_not_empty,
    assert_matches,
    assert_not_equal,
)
from pytest_api_core.assertions.response_assertions import assert_that
from pytest_api_core.auth.auth_handlers import (
    APIKeyAuth,
    BasicAuth,
    BearerAuth,
    OAuth2ClientCredentials,
)
from pytest_api_core.client.api_client import APIClient
from pytest_api_core.client.api_response import APIResponse
from pytest_api_core.security.redaction import add_sensitive_keys, register_secret

__version__ = "1.0.8"
__all__ = [
    "APIClient",
    "APIResponse",
    "assert_that",
    "assert_equal",
    "assert_not_equal",
    "assert_equal_ignore_case",
    "assert_contains",
    "assert_matches",
    "assert_is_empty",
    "assert_is_not_empty",
    "BearerAuth",
    "BasicAuth",
    "APIKeyAuth",
    "OAuth2ClientCredentials",
    "register_secret",
    "add_sensitive_keys",
]
