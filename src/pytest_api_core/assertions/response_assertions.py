"""
Fluent (chainable) response assertion API.

Usage
-----
    from pytest_api_core.assertions import assert_that

    assert_that(response).status_is(200)
    assert_that(response).status_is(200).has_key("id").json_path("$.name").equals("Alice")
    assert_that(response).content_type_contains("application/json")
    assert_that(response).response_time_under(500)   # ms
    assert_that(response).json_path("$.age").is_type("integer").json_path("$.age").between(0, 130)
    assert_that(response).has_path("$.data.items[0].id").not_has_path("$.error")

Every assertion method returns *self* so calls can be chained freely.
A clear AssertionError with context is raised on failure — or, inside
``soft_assertions()``, recorded so the chain keeps going (see ``soft.py``).
"""

from __future__ import annotations

import functools
import json
import logging
import re
from typing import Any, Callable, TypeVar, cast

from pytest_api_core.assertions.soft import record, soft_active
from pytest_api_core.client.api_response import APIResponse
from pytest_api_core.security.redaction import (
    is_sensitive_key,
    is_sensitive_path,
    mask,
    redact,
    redact_headers,
    redact_text,
    redact_url,
    schema_error_message,
)

_assert_log = logging.getLogger("pytest_api_core.assertions")

_F = TypeVar("_F", bound=Callable[..., Any])


def _emit(name: str, passed: bool, **detail: Any) -> None:
    """Emit a machine-readable sentinel line captured by HTMLReporter (secrets redacted)."""
    _assert_log.debug(
        "__API_ASSERT__ %s",
        json.dumps(
            {"name": name, "passed": passed, **redact(detail)}, separators=(",", ":"), default=str
        ),
    )


class ResponseAssertions:
    """Chainable assertion wrapper for APIResponse objects."""

    def __init__(self, response: APIResponse) -> None:
        self._response = response
        self._json_path_value: Any = _UNSET
        self._json_path_path: str | None = None

    # ------------------------------------------------------------------
    # Status code
    # ------------------------------------------------------------------

    def status_is(self, expected: int) -> "ResponseAssertions":
        """Assert the HTTP status code equals *expected*."""
        actual = self._response.status_code
        passed = actual == expected
        _emit("status_is", passed, expected=expected, actual=actual)
        if not passed:
            raise AssertionError(
                f"Expected status {expected}, got {actual}.\n"
                f"  URL: {self._safe_url()}\n"
                f"  Body: {self._safe_body()[:500]}"
            )
        return self

    def status_in(self, *expected: int) -> "ResponseAssertions":
        """Assert the status code is one of *expected*."""
        actual = self._response.status_code
        passed = actual in expected
        _emit("status_in", passed, expected=list(expected), actual=actual)
        if not passed:
            raise AssertionError(
                f"Expected status in {expected}, got {actual}.\n" f"  URL: {self._safe_url()}"
            )
        return self

    def is_success(self) -> "ResponseAssertions":
        """Assert 2xx status code."""
        actual = self._response.status_code
        passed = 200 <= actual < 300
        _emit("is_success", passed, actual=actual)
        if not passed:
            raise AssertionError(
                f"Expected 2xx status, got {actual}.\n"
                f"  URL: {self._safe_url()}\n"
                f"  Body: {self._safe_body()[:500]}"
            )
        return self

    def is_client_error(self) -> "ResponseAssertions":
        """Assert 4xx status code."""
        actual = self._response.status_code
        passed = 400 <= actual < 500
        _emit("is_client_error", passed, actual=actual)
        if not passed:
            raise AssertionError(f"Expected 4xx status, got {actual}.")
        return self

    def is_server_error(self) -> "ResponseAssertions":
        """Assert 5xx status code."""
        actual = self._response.status_code
        passed = 500 <= actual < 600
        _emit("is_server_error", passed, actual=actual)
        if not passed:
            raise AssertionError(f"Expected 5xx status, got {actual}.")
        return self

    # ------------------------------------------------------------------
    # Headers
    # ------------------------------------------------------------------

    def has_header(self, name: str) -> "ResponseAssertions":
        """Assert a response header with *name* is present (case-insensitive)."""
        passed = name.lower() in {k.lower() for k in self._response.headers}
        if passed:
            value = self._response.headers.get(name)
            shown = mask(value) if is_sensitive_key(name) else value
            _emit("has_header", passed, header=name, actual=shown)
        else:
            _emit("has_header", passed, header=name, actual="<missing>")
        if not passed:
            raise AssertionError(
                f"Expected header '{name}' to be present.\n"
                f"  Headers: {redact_headers(self._response.headers)}"
            )
        return self

    def header_equals(self, name: str, expected: str) -> "ResponseAssertions":
        """Assert header *name* equals *expected* (case-insensitive name match)."""
        actual = self._response.headers.get(name)
        passed = actual == expected
        if is_sensitive_key(name):
            expected, actual = mask(expected), mask(actual)
        _emit("header_equals", passed, header=name, expected=expected, actual=actual)
        if not passed:
            raise AssertionError(
                f"Expected header '{name}' = {redact(expected)!r}, got {redact(actual)!r}."
            )
        return self

    def content_type_contains(self, fragment: str) -> "ResponseAssertions":
        """Assert the Content-Type header contains *fragment*."""
        ct = self._response.headers.get("Content-Type", "")
        passed = fragment.lower() in ct.lower()
        _emit("content_type_contains", passed, expected=fragment, actual=ct)
        if not passed:
            raise AssertionError(f"Expected Content-Type to contain {fragment!r}, got {ct!r}.")
        return self

    # ------------------------------------------------------------------
    # JSON body — top-level keys
    # ------------------------------------------------------------------

    def has_key(self, key: str) -> "ResponseAssertions":
        """Assert the JSON body contains *key* at the top level."""
        body = self._json_body()
        passed = isinstance(body, dict) and key in body
        if passed:
            value = body[key]
            shown = mask(value) if is_sensitive_key(key) else value
            _emit("has_key", passed, key=key, actual=shown)
        else:
            _emit("has_key", passed, key=key, actual="<missing>")
        if not passed:
            raise AssertionError(
                f"Expected JSON key '{key}' to be present.\n"
                f"  Body keys: {list(body.keys()) if isinstance(body, dict) else redact(body)}"
            )
        return self

    def key_equals(self, key: str, expected: Any) -> "ResponseAssertions":
        """Assert top-level JSON key *key* equals *expected*."""
        body = self._json_body()
        if not isinstance(body, dict):
            raise AssertionError(f"Response body is not a JSON object: {redact(body)!r}")
        actual = body.get(key, _UNSET)
        shown_expected = mask(expected) if is_sensitive_key(key) else expected
        if actual is _UNSET:
            _emit("key_equals", False, key=key, expected=shown_expected, actual="<missing>")
            raise AssertionError(f"Key '{key}' not found in response body.")
        passed = actual == expected
        shown_actual = mask(actual) if is_sensitive_key(key) else actual
        _emit("key_equals", passed, key=key, expected=shown_expected, actual=shown_actual)
        if not passed:
            raise AssertionError(
                f"Expected body['{key}'] = {redact(shown_expected)!r}, "
                f"got {redact(shown_actual)!r}."
            )
        return self

    def body_contains(self, text: str) -> "ResponseAssertions":
        """Assert the raw response text contains *text*."""
        passed = text in self._response.text
        _emit("body_contains", passed, expected=text)
        if not passed:
            raise AssertionError(
                f"Expected response body to contain {redact(text)!r}.\n"
                f"  Body (first 300 chars): {redact_text(self._response.text)[:300]}"
            )
        return self

    def is_json_list(self) -> "ResponseAssertions":
        """Assert the JSON body is an array."""
        body = self._json_body()
        passed = isinstance(body, list)
        _emit("is_json_list", passed, actual=type(body).__name__)
        if not passed:
            raise AssertionError(f"Expected JSON array, got {type(body).__name__}.")
        return self

    def list_length(self, expected: int) -> "ResponseAssertions":
        """Assert the JSON array body has exactly *expected* items."""
        body = self._json_body()
        if not isinstance(body, list):
            _emit("list_length", False, expected=expected, actual=type(body).__name__)
            raise AssertionError(f"Expected JSON array, got {type(body).__name__}.")
        passed = len(body) == expected
        _emit("list_length", passed, expected=expected, actual=len(body))
        if not passed:
            raise AssertionError(f"Expected JSON list length {expected}, got {len(body)}.")
        return self

    def list_length_gte(self, minimum: int) -> "ResponseAssertions":
        """Assert the JSON array length is at least *minimum*."""
        body = self._json_body()
        actual = len(body) if isinstance(body, list) else "non-list"
        passed = isinstance(body, list) and len(body) >= minimum
        _emit("list_length_gte", passed, expected=minimum, actual=actual)
        if not passed:
            raise AssertionError(f"Expected JSON list length >= {minimum}, got {actual}.")
        return self

    # ------------------------------------------------------------------
    # JSONPath navigation (simple dot-notation; no external lib required)
    # ------------------------------------------------------------------

    def json_path(self, path: str) -> "ResponseAssertions":
        """
        Navigate to a value in the JSON body using a simple path expression.

        This is a small built-in subset, not full JSONPath — no external
        dependency required.

        Supported:
          ``$.key``            — top-level key
          ``$.key.nested``     — nested key
          ``$.items[0].id``    — array index
          ``$[0].id``          — root is array

        Not supported: wildcards (``$.items[*]``), filter expressions
        (``$.items[?(@.price > 10)]``), recursive descent (``$..id``), and
        slices (``$.items[0:2]``). For those, extract with a library like
        ``jsonpath-ng`` yourself and check the result with
        ``assert_equal(value, expected, field="<expression>")`` so it still
        appears in the HTML report.

        The extracted value is stored for the following ``.equals()`` /
        ``.matches()`` call.
        """
        body = self._json_body()
        try:
            self._json_path_value = _resolve_path(body, path)
        except AssertionError as exc:
            _emit("json_path", False, path=path, actual=str(exc))
            raise
        self._json_path_path = path
        return self

    def equals(self, expected: Any) -> "ResponseAssertions":
        """Assert the value from the last ``.json_path()`` call equals *expected*."""
        actual, path = self._take_path_value("equals")
        passed = actual == expected
        if is_sensitive_path(path):
            expected, actual = mask(expected), mask(actual)
        _emit("equals", passed, path=path, expected=expected, actual=actual)
        if not passed:
            raise AssertionError(f"Expected {redact(expected)!r}, got {redact(actual)!r}.")
        return self

    def not_equals(self, unexpected: Any) -> "ResponseAssertions":
        """Assert the value from the last ``.json_path()`` call differs from *unexpected*."""
        actual, path = self._take_path_value("not_equals")
        passed = actual != unexpected
        shown_unexpected, shown_actual = _shown(path, unexpected), _shown(path, actual)
        _emit(
            "not_equals",
            passed,
            path=path,
            expected=f"not {shown_unexpected!r}",
            actual=shown_actual,
        )
        if not passed:
            raise AssertionError(
                f"Expected {path} to differ from {redact(shown_unexpected)!r}, but it was equal."
            )
        return self

    def matches(self, pattern: str) -> "ResponseAssertions":
        """Assert the value from the last ``.json_path()`` call matches regex *pattern*."""
        value, path = self._take_path_value("matches")
        actual = str(value)
        passed = re.search(pattern, actual) is not None
        shown = mask(actual) if is_sensitive_path(path) else redact(actual)
        _emit("matches", passed, path=path, pattern=pattern, actual=shown)
        if not passed:
            raise AssertionError(f"Expected value to match /{pattern}/, got {shown!r}.")
        return self

    def is_not_none(self) -> "ResponseAssertions":
        """Assert the value from the last ``.json_path()`` call is not None."""
        actual, path = self._take_path_value("is_not_none")
        passed = actual is not None
        shown = mask(actual) if is_sensitive_path(path) else actual
        _emit("is_not_none", passed, path=path, actual=shown)
        if not passed:
            raise AssertionError("Expected value to be non-null.")
        return self

    def is_type(self, expected: type | tuple[type, ...] | str) -> "ResponseAssertions":
        """Assert the type of the last ``.json_path()`` value.

        *expected* is a Python type / tuple of types, or a JSON type name:
        ``"string"``, ``"number"``, ``"integer"``, ``"boolean"``, ``"array"``,
        ``"object"``, ``"null"``. Booleans never count as integers or numbers.
        """
        actual, path = self._take_path_value("is_type")
        passed = _type_matches(actual, expected)
        expected_name = _type_label(expected)
        actual_name = _json_type_name(actual)
        _emit("is_type", passed, path=path, expected=expected_name, actual=actual_name)
        if not passed:
            raise AssertionError(
                f"Expected {path} to be of type {expected_name}, got {actual_name}."
            )
        return self

    def contains(self, item: Any) -> "ResponseAssertions":
        """Assert the last ``.json_path()`` value contains *item*.

        Substring for strings, element membership for arrays, key for objects.
        """
        actual, path = self._take_path_value("contains")
        if isinstance(actual, str):
            passed = isinstance(item, str) and item in actual
        elif isinstance(actual, (list, dict)):
            passed = item in actual
        else:
            passed = False
        shown_item, shown_actual = _shown(path, item), _shown(path, actual)
        _emit("contains", passed, path=path, expected=shown_item, actual=shown_actual)
        if not passed:
            raise AssertionError(
                f"Expected {path} to contain {redact(shown_item)!r}, "
                f"got {_json_type_name(actual)} {redact(shown_actual)!r}."
            )
        return self

    def is_in(self, options: Any) -> "ResponseAssertions":
        """Assert the last ``.json_path()`` value is one of *options*."""
        actual, path = self._take_path_value("is_in")
        choices = list(options)
        passed = actual in choices
        shown_choices, shown_actual = _shown(path, choices), _shown(path, actual)
        _emit("is_in", passed, path=path, expected=shown_choices, actual=shown_actual)
        if not passed:
            raise AssertionError(
                f"Expected {path} to be one of {redact(shown_choices)!r}, "
                f"got {redact(shown_actual)!r}."
            )
        return self

    def has_length(self, expected: int) -> "ResponseAssertions":
        """Assert the last ``.json_path()`` value (string/array/object) has *expected* length."""
        actual, path = self._take_path_value("has_length")
        length = len(actual) if isinstance(actual, (str, list, dict)) else None
        passed = length == expected
        shown_len = length if length is not None else f"<{_json_type_name(actual)}>"
        _emit("has_length", passed, path=path, expected=expected, actual=shown_len)
        if not passed:
            raise AssertionError(f"Expected {path} to have length {expected}, got {shown_len}.")
        return self

    def is_empty(self) -> "ResponseAssertions":
        """Assert the last ``.json_path()`` value is an empty string, array or object."""
        actual, path = self._take_path_value("is_empty")
        passed = isinstance(actual, (str, list, dict)) and len(actual) == 0
        shown = _shown(path, actual)
        _emit("is_empty", passed, path=path, actual=shown)
        if not passed:
            raise AssertionError(f"Expected {path} to be empty, got {redact(shown)!r}.")
        return self

    def is_not_empty(self) -> "ResponseAssertions":
        """Assert the last ``.json_path()`` value is a non-empty string, array or object."""
        actual, path = self._take_path_value("is_not_empty")
        passed = isinstance(actual, (str, list, dict)) and len(actual) > 0
        shown = _shown(path, actual)
        _emit("is_not_empty", passed, path=path, actual=shown)
        if not passed:
            raise AssertionError(f"Expected {path} to be non-empty, got {redact(shown)!r}.")
        return self

    def greater_than(self, bound: float) -> "ResponseAssertions":
        """Assert the last ``.json_path()`` value is a number greater than *bound*."""
        return self._compare("greater_than", ">", bound, lambda v: v > bound)

    def less_than(self, bound: float) -> "ResponseAssertions":
        """Assert the last ``.json_path()`` value is a number less than *bound*."""
        return self._compare("less_than", "<", bound, lambda v: v < bound)

    def between(self, low: float, high: float) -> "ResponseAssertions":
        """Assert the last ``.json_path()`` value is a number with ``low <= value <= high``."""
        return self._compare(
            "between", f"in [{low}, {high}]", (low, high), lambda v: low <= v <= high
        )

    def has_path(self, path: str) -> "ResponseAssertions":
        """Assert *path* resolves in the JSON body (the value may be null)."""
        passed = self._path_exists(path)
        _emit("has_path", passed, path=path)
        if not passed:
            raise AssertionError(f"Expected path {path} to exist in the response body.")
        return self

    def not_has_path(self, path: str) -> "ResponseAssertions":
        """Assert *path* does not resolve in the JSON body."""
        passed = not self._path_exists(path)
        _emit("not_has_path", passed, path=path)
        if not passed:
            raise AssertionError(f"Expected path {path} to be absent from the response body.")
        return self

    # ------------------------------------------------------------------
    # Performance
    # ------------------------------------------------------------------

    def response_time_under(self, max_ms: float) -> "ResponseAssertions":
        """Assert the response time is under *max_ms* milliseconds.

        ``elapsed_ms`` is measured around the whole ``session.request()`` call,
        so it includes time spent on any urllib3 retries and backoff sleeps —
        not just the final successful attempt.
        """
        actual = self._response.elapsed_ms
        passed = actual < max_ms
        _emit("response_time_under", passed, max_ms=max_ms, actual_ms=round(actual, 1))
        if not passed:
            raise AssertionError(
                f"Expected response time < {max_ms}ms, got {actual:.1f}ms.\n"
                f"  URL: {self._safe_url()}"
            )
        return self

    # ------------------------------------------------------------------
    # Schema validation (uses jsonschema if available)
    # ------------------------------------------------------------------

    def matches_schema(self, schema: dict[str, Any]) -> "ResponseAssertions":
        """Assert the JSON body conforms to the given JSON Schema."""
        try:
            import jsonschema

            jsonschema.validate(instance=self._json_body(), schema=schema)
        except ImportError:
            raise ImportError(
                "jsonschema is required for schema validation: pip install jsonschema"
            )
        except jsonschema.ValidationError as exc:
            detail = schema_error_message(exc)
            _emit("matches_schema", False, actual=detail)
            # ``from None``: the ValidationError's str() dumps the whole failing
            # instance, which pytest would print as the chained "direct cause".
            raise AssertionError(f"Schema validation failed: {detail}") from None
        _emit("matches_schema", True)
        return self

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _take_path_value(self, method: str) -> tuple[Any, str | None]:
        """Consume the value stored by ``.json_path()`` (and reset it)."""
        value, path = self._json_path_value, self._json_path_path
        if value is _UNSET:
            raise RuntimeError(f"Call .json_path() before .{method}()")
        self._json_path_value = _UNSET
        self._json_path_path = None
        if value is _FAILED:
            # json_path() already failed and was recorded in soft mode.
            raise _AlreadyReported
        return value, path

    def _compare(
        self, name: str, op: str, bound: Any, check: Callable[[float], bool]
    ) -> "ResponseAssertions":
        actual, path = self._take_path_value(name)
        is_number = isinstance(actual, (int, float)) and not isinstance(actual, bool)
        passed = is_number and check(actual)
        shown = _shown(path, actual)
        expected = f"{op} {bound}" if not isinstance(bound, tuple) else op
        _emit(name, passed, path=path, expected=expected, actual=shown)
        if not passed:
            got = (
                repr(redact(shown)) if is_number else f"{_json_type_name(actual)} {redact(shown)!r}"
            )
            raise AssertionError(f"Expected {path} {expected}, got {got}.")
        return self

    def _path_exists(self, path: str) -> bool:
        try:
            _resolve_path(self._json_body(), path)
        except AssertionError:
            return False
        return True

    def _json_body(self) -> Any:
        try:
            return self._response.json()
        except (ValueError, TypeError) as exc:
            raise AssertionError(
                f"Response body is not valid JSON.\n"
                f"  Status: {self._response.status_code}\n"
                f"  Body: {redact_text(self._response.text)[:200]}"
            ) from exc

    def _safe_url(self) -> str:
        return redact_url(self._response.url)

    def _safe_body(self) -> str:
        return redact_text(self._response.response_body_text())


# ---------------------------------------------------------------------------
# Sentinel & helpers
# ---------------------------------------------------------------------------


class _Unset:
    """Sentinel for unset json_path value."""

    def __repr__(self) -> str:
        return "<UNSET>"


_UNSET = _Unset()
# json_path() failed inside soft_assertions(); the next consumer skips silently.
_FAILED = _Unset()


class _AlreadyReported(Exception):
    """Raised by a consumer whose json_path() failure was already recorded."""


def _shown(path: str | None, value: Any) -> Any:
    """Value as it may appear in sentinels: masked when the json_path is sensitive."""
    return mask(value) if is_sensitive_path(path) else value


_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


def _json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _type_label(expected: type | tuple[type, ...] | str) -> str:
    if isinstance(expected, str):
        return expected
    if isinstance(expected, tuple):
        return " | ".join(t.__name__ for t in expected)
    return expected.__name__


def _type_matches(value: Any, expected: type | tuple[type, ...] | str) -> bool:
    if isinstance(expected, str):
        key = expected.lower()
        if key not in _JSON_TYPES:
            raise ValueError(
                f"Unknown JSON type {expected!r}; use one of {', '.join(_JSON_TYPES)}."
            )
        types = _JSON_TYPES[key]
    else:
        types = expected if isinstance(expected, tuple) else (expected,)
    # bool is a subclass of int; only accept it when bool is asked for explicitly.
    if isinstance(value, bool) and bool not in types:
        return False
    return isinstance(value, types)


def _soft_aware(method: _F) -> _F:
    """Inside soft_assertions(), record a failing assertion and keep the chain going."""

    @functools.wraps(method)
    def wrapper(self: "ResponseAssertions", *args: Any, **kwargs: Any) -> Any:
        __tracebackhide__ = True  # keep this frame out of pytest tracebacks
        try:
            return method(self, *args, **kwargs)
        except _AlreadyReported:
            return self
        except AssertionError as exc:
            if not soft_active():
                raise
            record(str(exc))
            if method.__name__ == "json_path":
                self._json_path_value = _FAILED
                self._json_path_path = None
            return self

    return cast(_F, wrapper)


# Every public chain method (status_is, json_path, equals, ...) becomes soft-aware.
for _name, _attr in list(vars(ResponseAssertions).items()):
    if not _name.startswith("_") and callable(_attr):
        setattr(ResponseAssertions, _name, _soft_aware(_attr))
del _name, _attr


def _resolve_path(data: Any, path: str) -> Any:
    """Resolve a simple ``$.key.nested[0]`` path against *data*."""
    # Strip leading $
    path = path.lstrip("$")
    # Tokenise on "." and "[N]"
    tokens: list[str | int] = []
    for segment in re.split(r"\.|\[(\d+)\]", path):
        if segment is None or segment == "":
            continue
        try:
            tokens.append(int(segment))
        except ValueError:
            tokens.append(segment)

    current = data
    for token in tokens:
        if current is None:
            raise AssertionError(f"Path traversal failed at token {token!r}: value is null.")
        try:
            current = current[token]
        except (KeyError, IndexError, TypeError) as exc:
            raise AssertionError(
                f"Path token {token!r} not found in {type(current).__name__}: {redact(current)!r}"
            ) from exc
    return current


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def assert_that(response: APIResponse) -> ResponseAssertions:
    """Entry-point for the fluent assertion chain."""
    return ResponseAssertions(response)
