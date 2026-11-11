"""
HTTP client built on top of requests.Session.

Features
--------
- Automatic base-URL resolution
- Configurable retry with back-off (via urllib3.Retry); every retried attempt
  is recorded and shown in the HTML report, so flaky endpoints stay visible
- Request / response logging
- Pluggable auth strategies
- Returns APIResponse objects for use with the fluent assertion API
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
from types import TracebackType
from typing import Any, Mapping, Sequence

import requests
from requests.adapters import HTTPAdapter
from urllib3.connectionpool import ConnectionPool
from urllib3.response import BaseHTTPResponse
from urllib3.util.retry import Retry

from pytest_api_core.client.api_response import APIResponse, body_to_text
from pytest_api_core.security.redaction import (
    is_sensitive_key,
    redact,
    redact_headers,
    redact_text,
    redact_url,
    register_secret,
    scrub_text,
)

log = logging.getLogger("pytest_api_core.client")

# Max characters of each request/response body kept in the report sentinel.
_BODY_LIMIT = 2000

# Sentinel distinguishing "caller didn't pass retry=" (build one from the
# retry_total/retry_backoff_factor/retry_methods primitives) from an explicit
# retry=None (disable retries) or retry=<custom Retry instance>.
_UNSET: Any = object()

DEFAULT_RETRY_STATUSES: tuple[int, ...] = (500, 502, 503, 504)

# Attempts that triggered a retry during the in-flight request. Set by
# APIClient._request() around each call and appended to by RecordingRetry.
_retry_attempts: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "pytest_api_core_retry_attempts", default=None
)


class RecordingRetry(Retry):
    """``urllib3.Retry`` that records every attempt which led to a retry.

    urllib3 retries inside the transport adapter, so without this the client
    (and the HTML report) only ever sees the final response — a call that
    returned 503 and then 200 would look like a clean 200. Each recorded
    attempt holds its status (or error) and when it ended, relative to the
    start of the call.

    Subclass this rather than ``Retry`` when passing a custom ``retry=`` object
    so the attempts stay visible; a plain ``Retry`` instance is converted
    automatically.
    """

    def increment(
        self,
        method: str | None = None,
        url: str | None = None,
        response: BaseHTTPResponse | None = None,
        error: Exception | None = None,
        _pool: ConnectionPool | None = None,
        _stacktrace: TracebackType | None = None,
    ) -> RecordingRetry:
        # super() raises MaxRetryError once exhausted. Recording only after it
        # returns means the final attempt (which becomes the call's response or
        # error) is never also listed as a retried attempt.
        new_retry = super().increment(method, url, response, error, _pool, _stacktrace)
        attempts = _retry_attempts.get()
        if attempts is not None:
            entry: dict[str, Any] = {
                "status": response.status if response is not None else None,
                "monotonic": time.monotonic(),
            }
            if error is not None:
                entry["error"] = scrub_text(f"{type(error).__name__}: {error}")
            attempts.append(entry)
        return new_retry


class APIClient:
    """
    Session-backed HTTP client used by API tests.

    Parameters
    ----------
    base_url:
        Root URL prepended to every relative path (e.g. ``https://api.example.com/v1``).
    auth:
        An auth handler instance (BearerAuth, BasicAuth, APIKeyAuth, …) or any
        callable accepted by requests.
    timeout:
        Default timeout in seconds for every request.
    verify_ssl:
        Whether to verify TLS certificates.
    default_headers:
        Headers merged into every request.
    retry:
        Pre-built urllib3 ``Retry`` instance, for full manual control. Pass
        ``None`` to disable retries entirely. Leave unset (the default) to
        build one from *retry_total* / *retry_backoff_factor* / *retry_methods* /
        *retry_statuses*.
    retry_total:
        Max retry attempts for transient failures (default: 3). Ignored if
        *retry* is explicitly passed.
    retry_backoff_factor:
        Backoff factor between retries, e.g. 0.3 -> 0s, 0.3s, 0.6s, 1.2s, ...
        (default: 0.3). Ignored if *retry* is explicitly passed.
    retry_methods:
        HTTP methods eligible for retry (default: GET, HEAD, OPTIONS — the
        idempotent methods). Ignored if *retry* is explicitly passed.
    retry_statuses:
        Response status codes that trigger a retry (default: 500, 502, 503,
        504). Add 429 to retry rate-limited calls; urllib3 honours the
        ``Retry-After`` header on 413/429/503. Ignored if *retry* is explicitly
        passed.
    """

    def __init__(
        self,
        base_url: str,
        auth: Any = None,
        timeout: int | float = 30,
        verify_ssl: bool = True,
        default_headers: dict[str, str] | None = None,
        retry: Retry | None = _UNSET,
        retry_total: int = 3,
        retry_backoff_factor: float = 0.3,
        retry_methods: Sequence[str] = ("GET", "HEAD", "OPTIONS"),
        retry_statuses: Sequence[int] = DEFAULT_RETRY_STATUSES,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify_ssl = verify_ssl

        self._session = requests.Session()

        if auth is not None:
            self._session.auth = auth

        if default_headers:
            self._session.headers.update(default_headers)
            for name, value in default_headers.items():
                if is_sensitive_key(name):
                    register_secret(value)

        if retry is _UNSET:
            retry = RecordingRetry(
                total=retry_total,
                backoff_factor=retry_backoff_factor,
                status_forcelist=set(retry_statuses),
                allowed_methods=set(retry_methods),
                raise_on_status=False,
            )
        elif type(retry) is Retry:
            # Plain Retry from the caller: keep their policy, add recording.
            recording = RecordingRetry.__new__(RecordingRetry)
            recording.__dict__.update(retry.__dict__)
            retry = recording

        if retry:
            adapter = HTTPAdapter(max_retries=retry)
            self._session.mount("https://", adapter)
            self._session.mount("http://", adapter)

    # ------------------------------------------------------------------
    # HTTP verbs
    # ------------------------------------------------------------------

    def get(self, path: str, **kwargs: Any) -> APIResponse:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> APIResponse:
        return self._request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> APIResponse:
        return self._request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> APIResponse:
        return self._request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> APIResponse:
        return self._request("DELETE", path, **kwargs)

    def head(self, path: str, **kwargs: Any) -> APIResponse:
        return self._request("HEAD", path, **kwargs)

    def options(self, path: str, **kwargs: Any) -> APIResponse:
        return self._request("OPTIONS", path, **kwargs)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs: Any) -> APIResponse:
        url = self._resolve_url(path)
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("verify", self.verify_ssl)

        safe_url = redact_url(url)

        # DEBUG: full request detail before sending (secrets redacted)
        if log.isEnabledFor(logging.DEBUG):
            body = kwargs.get("json") or kwargs.get("data")
            log.debug(
                "→ %s %s  headers=%s  body=%s",
                method,
                safe_url,
                redact_headers(self._session.headers),
                redact(body) if isinstance(body, (dict, list, str)) else body,
            )

        attempts: list[dict[str, Any]] = []
        token = _retry_attempts.set(attempts)
        start = time.monotonic()
        try:
            response = self._session.request(method, url, **kwargs)
        except requests.RequestException as exc:
            # Timeouts / connection errors: record the attempt so it still shows
            # up in the HTML report (as an ERROR banner), then re-raise.
            elapsed_ms = (time.monotonic() - start) * 1000
            error = scrub_text(f"{type(exc).__name__}: {exc}")
            retries = self._log_retries(method, safe_url, attempts, start)
            log.warning("✗ %s %s  %s  (%.1f ms)", method, safe_url, error, elapsed_ms)
            sent = exc.request if isinstance(exc.request, requests.PreparedRequest) else None
            self._emit_call(
                method=method,
                url=safe_url,
                req_headers=sent.headers if sent is not None else self._session.headers,
                req_body=body_to_text(sent.body) if sent is not None else "",
                status=None,
                elapsed_ms=elapsed_ms,
                res_headers={},
                res_body="",
                error=error,
                retries=retries,
            )
            raise
        finally:
            _retry_attempts.reset(token)
        elapsed_ms = (time.monotonic() - start) * 1000

        api_resp = APIResponse(response, elapsed_ms)

        # INFO: one-liner always shown at INFO level
        retries = self._log_retries(method, safe_url, attempts, start)
        log.info("← %s %s  %s  (%.1f ms)", method, safe_url, response.status_code, elapsed_ms)

        # Redact before truncating so a cut can't leave a partial secret behind
        res_body = redact_text(api_resp.response_body_text())

        # DEBUG: response body
        if log.isEnabledFor(logging.DEBUG):
            log.debug("   response body: %s", res_body)

        # Uses the prepared request's headers (what was actually sent, incl. auth).
        self._emit_call(
            method=method,
            url=safe_url,
            req_headers=response.request.headers,
            req_body=api_resp.request_body_text(),
            status=response.status_code,
            elapsed_ms=elapsed_ms,
            res_headers=response.headers,
            res_body=res_body,
            retries=retries,
        )

        return api_resp

    @staticmethod
    def _log_retries(
        method: str, safe_url: str, attempts: list[dict[str, Any]], start: float
    ) -> list[dict[str, Any]]:
        """Turn recorded attempts into report entries and log each one at WARNING.

        WARNING (not DEBUG) so a call that only passed after a retry shows up in
        the console and the report's captured logs at the default log level.
        """
        retries: list[dict[str, Any]] = []
        for n, attempt in enumerate(attempts, start=1):
            entry: dict[str, Any] = {
                "attempt": n,
                "status": attempt["status"],
                "at_ms": round((attempt["monotonic"] - start) * 1000, 1),
            }
            if "error" in attempt:
                entry["error"] = attempt["error"]
            outcome = entry.get("error") or entry["status"]
            log.warning("↻ %s %s  %s  — attempt %d failed, retrying", method, safe_url, outcome, n)
            retries.append(entry)
        return retries

    @staticmethod
    def _emit_call(
        *,
        method: str,
        url: str,
        req_headers: Mapping[str, Any],
        req_body: str,
        status: int | None,
        elapsed_ms: float,
        res_headers: Mapping[str, Any],
        res_body: str,
        error: str | None = None,
        retries: list[dict[str, Any]] | None = None,
    ) -> None:
        """Structured sentinel parsed by HTMLReporter to build request/response banners.

        Headers and bodies are redacted here — tokens are never logged. Bodies are
        redacted before truncating so a cut can't leave a partial secret behind.
        """
        safe_req_body = redact_text(req_body)
        payload: dict[str, Any] = {
            "method": method,
            "url": url,
            "req_headers": redact_headers(req_headers),
            "req_body": safe_req_body[:_BODY_LIMIT],
            "req_body_truncated": len(safe_req_body) > _BODY_LIMIT,
            "status": status,
            "elapsed_ms": round(elapsed_ms, 1),
            "res_headers": redact_headers(res_headers),
            "res_body": redact_text(res_body)[:_BODY_LIMIT],
        }
        if error is not None:
            payload["error"] = error
        if retries:
            payload["retries"] = retries
        log.debug("__API_CALL__ %s", json.dumps(payload, separators=(",", ":")))

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "APIClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    def __repr__(self) -> str:
        return f"<APIClient base_url={self.base_url!r}>"
