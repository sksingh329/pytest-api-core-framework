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

from contextvars import ContextVar, Token
from types import TracebackType

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


class soft_assertions:  # noqa: N801 — used like a function: ``with soft_assertions():``
    """Collect assertion failures in the block and raise one combined AssertionError.

    A class rather than ``@contextmanager`` so the raising frame can be hidden
    from pytest tracebacks: the failure then points at the test's ``with`` line
    instead of framework / ``contextlib`` internals.
    """

    def __init__(self) -> None:
        self._failures: list[str] = []
        self._token: Token[list[str] | None] | None = None

    def __enter__(self) -> None:
        if _collector.get() is None:  # nested blocks report through the outermost one
            self._failures = []
            self._token = _collector.set(self._failures)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:  # None: never swallows an exception raised inside the block
        __tracebackhide__ = True  # noqa: F841 — read by pytest
        if self._token is None:
            return
        _collector.reset(self._token)
        self._token = None
        if exc_type is None and self._failures:
            raise AssertionError(_format(self._failures))
