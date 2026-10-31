"""
Generic, standalone string assertion utilities.

Usage
-----
    from pytest_api_core.assertions import assert_equal

    assert_equal(actual, expected)
    assert_contains(actual, "substring")
    assert_matches(actual, r"^\\d+$")
    assert_matches_schema(actual, schema)
    assert_is_not_empty(token, sensitive=True)   # value masked in logs/report

Registered secrets (auth handler tokens, ``register_secret()``), Bearer
credentials and JWTs are always scrubbed from sentinels and failure messages.
Pass ``sensitive=True`` to mask the actual/expected values entirely.

Unlike :class:`ResponseAssertions`, these are plain functions for comparing
arbitrary actual/expected strings — not tied to an ``APIResponse``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pytest_api_core.security.redaction import mask, redact, schema_error_message

_assert_log = logging.getLogger("pytest_api_core.assertions")


def _emit(name: str, passed: bool, **detail: object) -> None:
    """Emit a machine-readable sentinel line captured by HTMLReporter (secrets redacted)."""
    _assert_log.debug(
        "__API_ASSERT__ %s",
        json.dumps({"name": name, "passed": passed, **redact(detail)}, separators=(",", ":")),
    )


def _fail(message: str | None, default: str) -> None:
    raise AssertionError(f"{message}\n  {redact(default)}" if message else redact(default))


def _show(value: Any, sensitive: bool) -> Any:
    """Value as it may appear in sentinels and failure messages."""
    return mask(value) if sensitive else value


def assert_equal(
    actual: str, expected: str, *, message: str | None = None, sensitive: bool = False
) -> None:
    """Assert *actual* equals *expected*."""
    passed = actual == expected
    shown_actual, shown_expected = _show(actual, sensitive), _show(expected, sensitive)
    _emit("assert_equal", passed, expected=shown_expected, actual=shown_actual)
    if not passed:
        _fail(message, f"Expected {shown_expected!r}, got {shown_actual!r}.")


def assert_not_equal(
    actual: str, expected: str, *, message: str | None = None, sensitive: bool = False
) -> None:
    """Assert *actual* does not equal *expected*."""
    passed = actual != expected
    shown_actual, shown_expected = _show(actual, sensitive), _show(expected, sensitive)
    _emit("assert_not_equal", passed, expected=shown_expected, actual=shown_actual)
    if not passed:
        _fail(message, f"Expected value to differ from {shown_expected!r}, got {shown_actual!r}.")


def assert_equal_ignore_case(
    actual: str, expected: str, *, message: str | None = None, sensitive: bool = False
) -> None:
    """Assert *actual* equals *expected*, ignoring case."""
    passed = actual.lower() == expected.lower()
    shown_actual, shown_expected = _show(actual, sensitive), _show(expected, sensitive)
    _emit("assert_equal_ignore_case", passed, expected=shown_expected, actual=shown_actual)
    if not passed:
        _fail(message, f"Expected {shown_expected!r} (case-insensitive), got {shown_actual!r}.")


def assert_contains(
    actual: str, expected_substring: str, *, message: str | None = None, sensitive: bool = False
) -> None:
    """Assert *actual* contains *expected_substring*."""
    passed = expected_substring in actual
    shown_actual = _show(actual, sensitive)
    shown_substring = _show(expected_substring, sensitive)
    _emit("assert_contains", passed, expected_substring=shown_substring, actual=shown_actual)
    if not passed:
        _fail(message, f"Expected {shown_actual!r} to contain {shown_substring!r}.")


def assert_matches(
    actual: str, pattern: str, *, message: str | None = None, sensitive: bool = False
) -> None:
    """Assert *actual* matches the regex *pattern*."""
    passed = re.search(pattern, actual) is not None
    shown_actual = _show(actual, sensitive)
    _emit("assert_matches", passed, pattern=pattern, actual=shown_actual)
    if not passed:
        _fail(message, f"Expected {shown_actual!r} to match /{pattern}/.")


def assert_is_empty(actual: str, *, message: str | None = None, sensitive: bool = False) -> None:
    """Assert *actual* is an empty string."""
    passed = actual == ""
    shown_actual = _show(actual, sensitive)
    _emit("assert_is_empty", passed, actual=shown_actual)
    if not passed:
        _fail(message, f"Expected empty string, got {shown_actual!r}.")


def assert_is_not_empty(
    actual: str, *, message: str | None = None, sensitive: bool = False
) -> None:
    """Assert *actual* is a non-empty string."""
    passed = actual != ""
    _emit("assert_is_not_empty", passed, actual=_show(actual, sensitive))
    if not passed:
        _fail(message, "Expected non-empty string, got empty string.")


def assert_matches_schema(
    actual: object, schema: dict[str, Any], *, message: str | None = None
) -> None:
    """Assert *actual* conforms to the given JSON Schema, collecting all errors.

    Values under sensitive keys (``token``, ``password``, …) are masked in the
    sentinel's ``actual`` payload.
    """
    import jsonschema

    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(actual), key=lambda e: list(e.path))
    passed = not errors
    error_messages = [schema_error_message(e) for e in errors]
    _emit(
        "assert_matches_schema",
        passed,
        errors=error_messages,
        schema=json.dumps(schema, indent=2, default=str),
        actual=json.dumps(redact(actual), indent=2, default=str),
    )
    if not passed:
        joined = "; ".join(error_messages)
        _fail(message, f"Schema validation failed with {len(errors)} error(s): {joined}")
