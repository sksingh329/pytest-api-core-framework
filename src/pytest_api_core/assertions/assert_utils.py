"""
Generic, standalone string assertion utilities.

Usage
-----
    from pytest_api_core.assertions import assert_equal

    assert_equal(actual, expected)
    assert_contains(actual, "substring")
    assert_matches(actual, r"^\\d+$")

Unlike :class:`ResponseAssertions`, these are plain functions for comparing
arbitrary actual/expected strings — not tied to an ``APIResponse``.
"""

from __future__ import annotations

import json
import logging
import re

_assert_log = logging.getLogger("pytest_api_core.assertions")


def _emit(name: str, passed: bool, **detail: object) -> None:
    """Emit a machine-readable sentinel line captured by HTMLReporter."""
    _assert_log.debug(
        "__API_ASSERT__ %s",
        json.dumps({"name": name, "passed": passed, **detail}, separators=(",", ":")),
    )


def _fail(message: str | None, default: str) -> None:
    raise AssertionError(f"{message}\n  {default}" if message else default)


def assert_equal(actual: str, expected: str, *, message: str | None = None) -> None:
    """Assert *actual* equals *expected*."""
    passed = actual == expected
    _emit("assert_equal", passed, expected=expected, actual=actual)
    if not passed:
        _fail(message, f"Expected {expected!r}, got {actual!r}.")


def assert_not_equal(actual: str, expected: str, *, message: str | None = None) -> None:
    """Assert *actual* does not equal *expected*."""
    passed = actual != expected
    _emit("assert_not_equal", passed, expected=expected, actual=actual)
    if not passed:
        _fail(message, f"Expected value to differ from {expected!r}, got {actual!r}.")


def assert_equal_ignore_case(actual: str, expected: str, *, message: str | None = None) -> None:
    """Assert *actual* equals *expected*, ignoring case."""
    passed = actual.lower() == expected.lower()
    _emit("assert_equal_ignore_case", passed, expected=expected, actual=actual)
    if not passed:
        _fail(message, f"Expected {expected!r} (case-insensitive), got {actual!r}.")


def assert_contains(actual: str, expected_substring: str, *, message: str | None = None) -> None:
    """Assert *actual* contains *expected_substring*."""
    passed = expected_substring in actual
    _emit("assert_contains", passed, expected_substring=expected_substring, actual=actual)
    if not passed:
        _fail(message, f"Expected {actual!r} to contain {expected_substring!r}.")


def assert_matches(actual: str, pattern: str, *, message: str | None = None) -> None:
    """Assert *actual* matches the regex *pattern*."""
    passed = re.search(pattern, actual) is not None
    _emit("assert_matches", passed, pattern=pattern, actual=actual)
    if not passed:
        _fail(message, f"Expected {actual!r} to match /{pattern}/.")


def assert_is_empty(actual: str, *, message: str | None = None) -> None:
    """Assert *actual* is an empty string."""
    passed = actual == ""
    _emit("assert_is_empty", passed, actual=actual)
    if not passed:
        _fail(message, f"Expected empty string, got {actual!r}.")


def assert_is_not_empty(actual: str, *, message: str | None = None) -> None:
    """Assert *actual* is a non-empty string."""
    passed = actual != ""
    _emit("assert_is_not_empty", passed, actual=actual)
    if not passed:
        _fail(message, "Expected non-empty string, got empty string.")
