"""
Generic, standalone string assertion utilities.

Usage
-----
    from pytest_api_core.assertions import assert_equal

    assert_equal(actual, expected)
    assert_equal(user["name"], "Alice", field="user.name")   # field shown in report
    assert_contains(actual, "substring")
    assert_matches(actual, r"^\\d+$")
    assert_matches_schema(actual, schema)
    assert_is_not_empty(token, sensitive=True)   # value masked in logs/report

Registered secrets (auth handler tokens, ``register_secret()``), Bearer
credentials and JWTs are always scrubbed from sentinels and failure messages.
Pass ``sensitive=True`` to mask the actual/expected values entirely.

Each assertion is labelled with a field name, shown next to the expected/actual
values in the HTML report and prefixed to the failure message. Pass
``field="..."`` to set it; otherwise it is taken from the source text of the
first argument (``assert_equal(body["name"], "Alice")`` → ``body["name"]``).
A literal first argument gets no field name. A sensitive field name (``token``,
``password``, …) masks the values automatically, as if ``sensitive=True`` had
been passed.

Unlike :class:`ResponseAssertions`, these are plain functions for comparing
arbitrary actual/expected strings — not tied to an ``APIResponse``.
"""

from __future__ import annotations

import ast
import functools
import inspect
import json
import linecache
import logging
import re
from typing import Any

from pytest_api_core.assertions.soft import record, soft_active
from pytest_api_core.security.redaction import (
    is_sensitive_key,
    mask,
    redact,
    schema_error_message,
)

_assert_log = logging.getLogger("pytest_api_core.assertions")


def _emit(name: str, passed: bool, field: str | None, **detail: object) -> None:
    """Emit a machine-readable sentinel line captured by HTMLReporter (secrets redacted)."""
    if field is not None:
        detail = {"field": field, **detail}
    _assert_log.debug(
        "__API_ASSERT__ %s",
        json.dumps({"name": name, "passed": passed, **redact(detail)}, separators=(",", ":")),
    )


def _fail(message: str | None, default: str, field: str | None) -> None:
    if field is not None:
        default = f"[{field}] {default}"
    text = f"{message}\n  {redact(default)}" if message else redact(default)
    if soft_active():
        record(text)  # inside soft_assertions(): collect instead of raising
        return
    raise AssertionError(text)


def _masked(sensitive: bool, field: str | None) -> bool:
    """Mask when asked to, or when the field name itself is sensitive (``token`` etc.).

    The field may be a source expression such as ``body["access_token"]``, so each
    identifier segment is checked as well as the whole name.
    """
    if sensitive or field is None:
        return sensitive
    return is_sensitive_key(field) or any(
        is_sensitive_key(seg) for seg in re.split(r"\W+", field) if seg
    )


_MAX_FIELD_LEN = 80


@functools.lru_cache(maxsize=64)
def _parse_source(filename: str) -> tuple[str, ast.AST] | None:
    source = "".join(linecache.getlines(filename))
    if not source:
        return None
    try:
        return source, ast.parse(source, filename)
    except (SyntaxError, ValueError):
        return None


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_field_like(node: ast.expr) -> bool:
    """True for name-like expressions: ``x``, ``a.b``, ``body["k"][0]``, ``resp.json()["id"]``.

    Literals and anything built from them (dicts, f-strings, concatenation, calls
    with arguments) are rejected: their source text says nothing about which
    field is checked and may contain secret values written inline in the test.
    """
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _is_field_like(node.value)
    if isinstance(node, ast.Subscript):
        index = node.slice
        key_ok = isinstance(index, ast.Name) or (
            isinstance(index, ast.Constant) and isinstance(index.value, (str, int))
        )
        return key_ok and _is_field_like(node.value)
    if isinstance(node, ast.Call):
        return not node.args and not node.keywords and _is_field_like(node.func)
    return False


def _infer_field(helper: str, filename: str, lineno: int) -> str | None:
    """Return the source text of the first argument of the *helper* call at *lineno*."""
    parsed = _parse_source(filename)
    if parsed is None:
        return None
    source, tree = parsed
    best: ast.Call | None = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and node.args
            and _call_name(node.func) == helper
            and node.lineno <= lineno <= (node.end_lineno or node.lineno)
        ):
            # Innermost call wins if several span the line.
            if best is None or node.lineno >= best.lineno:
                best = node
    if best is None or not _is_field_like(best.args[0]):
        return None
    segment = ast.get_source_segment(source, best.args[0])
    if not segment:
        return None
    segment = " ".join(segment.split())
    if len(segment) > _MAX_FIELD_LEN:
        segment = segment[: _MAX_FIELD_LEN - 1] + "…"
    return segment


def _resolve_field(field: str | None) -> str | None:
    """Explicit *field*, else the source text of the caller's first argument.

    Must be called directly from a public helper: it reads the helper's name
    and its caller's location from the stack.
    """
    if field is not None:
        return field
    frame = inspect.currentframe()
    try:
        helper_frame = frame.f_back if frame else None
        caller = helper_frame.f_back if helper_frame else None
        if helper_frame is None or caller is None:
            return None
        return _infer_field(helper_frame.f_code.co_name, caller.f_code.co_filename, caller.f_lineno)
    except Exception:  # inference is best-effort; never break an assertion over it
        return None
    finally:
        del frame


def _show(value: Any, sensitive: bool) -> Any:
    """Value as it may appear in sentinels and failure messages."""
    return mask(value) if sensitive else value


def assert_equal(
    actual: str,
    expected: str,
    *,
    message: str | None = None,
    sensitive: bool = False,
    field: str | None = None,
) -> None:
    """Assert *actual* equals *expected*."""
    field = _resolve_field(field)
    passed = actual == expected
    hide = _masked(sensitive, field)
    shown_actual, shown_expected = _show(actual, hide), _show(expected, hide)
    _emit("assert_equal", passed, field, expected=shown_expected, actual=shown_actual)
    if not passed:
        _fail(message, f"Expected {shown_expected!r}, got {shown_actual!r}.", field)


def assert_not_equal(
    actual: str,
    expected: str,
    *,
    message: str | None = None,
    sensitive: bool = False,
    field: str | None = None,
) -> None:
    """Assert *actual* does not equal *expected*."""
    field = _resolve_field(field)
    passed = actual != expected
    hide = _masked(sensitive, field)
    shown_actual, shown_expected = _show(actual, hide), _show(expected, hide)
    _emit("assert_not_equal", passed, field, expected=shown_expected, actual=shown_actual)
    if not passed:
        _fail(
            message,
            f"Expected value to differ from {shown_expected!r}, got {shown_actual!r}.",
            field,
        )


def assert_equal_ignore_case(
    actual: str,
    expected: str,
    *,
    message: str | None = None,
    sensitive: bool = False,
    field: str | None = None,
) -> None:
    """Assert *actual* equals *expected*, ignoring case."""
    field = _resolve_field(field)
    passed = actual.lower() == expected.lower()
    hide = _masked(sensitive, field)
    shown_actual, shown_expected = _show(actual, hide), _show(expected, hide)
    _emit("assert_equal_ignore_case", passed, field, expected=shown_expected, actual=shown_actual)
    if not passed:
        _fail(
            message,
            f"Expected {shown_expected!r} (case-insensitive), got {shown_actual!r}.",
            field,
        )


def assert_contains(
    actual: str,
    expected_substring: str,
    *,
    message: str | None = None,
    sensitive: bool = False,
    field: str | None = None,
) -> None:
    """Assert *actual* contains *expected_substring*."""
    field = _resolve_field(field)
    passed = expected_substring in actual
    hide = _masked(sensitive, field)
    shown_actual = _show(actual, hide)
    shown_substring = _show(expected_substring, hide)
    _emit("assert_contains", passed, field, expected_substring=shown_substring, actual=shown_actual)
    if not passed:
        _fail(message, f"Expected {shown_actual!r} to contain {shown_substring!r}.", field)


def assert_matches(
    actual: str,
    pattern: str,
    *,
    message: str | None = None,
    sensitive: bool = False,
    field: str | None = None,
) -> None:
    """Assert *actual* matches the regex *pattern*."""
    field = _resolve_field(field)
    passed = re.search(pattern, actual) is not None
    shown_actual = _show(actual, _masked(sensitive, field))
    _emit("assert_matches", passed, field, pattern=pattern, actual=shown_actual)
    if not passed:
        _fail(message, f"Expected {shown_actual!r} to match /{pattern}/.", field)


def assert_is_empty(
    actual: str,
    *,
    message: str | None = None,
    sensitive: bool = False,
    field: str | None = None,
) -> None:
    """Assert *actual* is an empty string."""
    field = _resolve_field(field)
    passed = actual == ""
    shown_actual = _show(actual, _masked(sensitive, field))
    _emit("assert_is_empty", passed, field, actual=shown_actual)
    if not passed:
        _fail(message, f"Expected empty string, got {shown_actual!r}.", field)


def assert_is_not_empty(
    actual: str,
    *,
    message: str | None = None,
    sensitive: bool = False,
    field: str | None = None,
) -> None:
    """Assert *actual* is a non-empty string."""
    field = _resolve_field(field)
    passed = actual != ""
    _emit("assert_is_not_empty", passed, field, actual=_show(actual, _masked(sensitive, field)))
    if not passed:
        _fail(message, "Expected non-empty string, got empty string.", field)


def assert_matches_schema(
    actual: object,
    schema: dict[str, Any],
    *,
    message: str | None = None,
    field: str | None = None,
) -> None:
    """Assert *actual* conforms to the given JSON Schema, collecting all errors.

    Values under sensitive keys (``token``, ``password``, …) are masked in the
    sentinel's ``actual`` payload.
    """
    field = _resolve_field(field)
    import jsonschema

    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(actual), key=lambda e: list(e.path))
    passed = not errors
    error_messages = [schema_error_message(e) for e in errors]
    _emit(
        "assert_matches_schema",
        passed,
        field,
        errors=error_messages,
        schema=json.dumps(schema, indent=2, default=str),
        actual=json.dumps(redact(actual), indent=2, default=str),
    )
    if not passed:
        joined = "; ".join(error_messages)
        _fail(message, f"Schema validation failed with {len(errors)} error(s): {joined}", field)
