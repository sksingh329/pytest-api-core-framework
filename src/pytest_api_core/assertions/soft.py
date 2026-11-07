"""
Soft assertions: collect every failure in a block, then fail once at the end.

Usage
-----
    from pytest_api_core.assertions import assert_that, assert_equal, soft_assertions

    with soft_assertions():
        assert_that(resp).status_is(200).json_path("$.name").equals("Alice")
        assert_that(resp).json_path("$.age").greater_than(18)
        assert_equal(resp.headers["X-Env"], "prod")
    # -> one AssertionError listing every failure above

Inside the block, a failing ``assert_that(...)`` chain or ``assert_*`` helper
records its message and carries on instead of raising. Each assertion still
emits its ``__API_ASSERT__`` sentinel, so the HTML report shows every row.

Blocks may be nested; failures go to the outermost block, which raises once.
If the block raises some other exception, that exception propagates unchanged.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_collector: ContextVar[list[str] | None] = ContextVar("pytest_api_core_soft", default=None)


def soft_active() -> bool:
    """True inside a ``soft_assertions()`` block."""
    return _collector.get() is not None


def record(message: str) -> None:
    """Record a failure message in the active block (no-op outside one)."""
    failures = _collector.get()
    if failures is not None:
        failures.append(message)


def _format(failures: list[str]) -> str:
    lines = [f"{len(failures)} soft assertion(s) failed:"]
    for i, msg in enumerate(failures, 1):
        body = msg.replace("\n", "\n     ")
        lines.append(f"  {i}) {body}")
    return "\n".join(lines)


@contextmanager
def soft_assertions() -> Iterator[None]:
    """Collect assertion failures in the block and raise one combined AssertionError."""
    if _collector.get() is not None:
        yield  # nested: the outer block collects and raises
        return
    failures: list[str] = []
    token = _collector.set(failures)
    try:
        yield
    finally:
        _collector.reset(token)
    if failures:
        raise AssertionError(_format(failures))
