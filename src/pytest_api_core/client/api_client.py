"""
HTTP client built on top of requests.Session.

Features
--------
- Automatic base-URL resolution
- Configurable retry with back-off (via urllib3.Retry)
- Request / response logging
- Pluggable auth strategies
- Returns APIResponse objects for use with the fluent assertion API
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Sequence

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pytest_api_core.client.api_response import APIResponse

log = logging.getLogger("pytest_api_core.client")

# Sentinel distinguishing "caller didn't pass retry=" (build one from the
# retry_total/retry_backoff_factor/retry_methods primitives) from an explicit
# retry=None (disable retries) or retry=<custom Retry instance>.
_UNSET: Any = object()

_DEFAULT_RETRY_STATUS_FORCELIST = (500, 502, 503, 504)


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
        build one from *retry_total* / *retry_backoff_factor* / *retry_methods*.
    retry_total:
        Max retry attempts for transient failures (default: 3). Ignored if
        *retry* is explicitly passed.
    retry_backoff_factor:
        Backoff factor between retries, e.g. 0.3 -> 0s, 0.3s, 0.6s, 1.2s, ...
        (default: 0.3). Ignored if *retry* is explicitly passed.
    retry_methods:
        HTTP methods eligible for retry (default: GET, HEAD, OPTIONS — the
        idempotent methods). Ignored if *retry* is explicitly passed.
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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify_ssl = verify_ssl

        self._session = requests.Session()

        if auth is not None:
            self._session.auth = auth

        if default_headers:
            self._session.headers.update(default_headers)

        if retry is _UNSET:
            retry = Retry(
                total=retry_total,
                backoff_factor=retry_backoff_factor,
                status_forcelist=_DEFAULT_RETRY_STATUS_FORCELIST,
                allowed_methods=set(retry_methods),
                raise_on_status=False,
            )

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

        # DEBUG: full request detail before sending
        if log.isEnabledFor(logging.DEBUG):
            log.debug(
                "→ %s %s  headers=%s  body=%s",
                method,
                url,
                dict(self._session.headers),
                kwargs.get("json") or kwargs.get("data"),
            )

        start = time.monotonic()
        response = self._session.request(method, url, **kwargs)
        elapsed_ms = (time.monotonic() - start) * 1000

        api_resp = APIResponse(response, elapsed_ms)

        # INFO: one-liner always shown at INFO level
        log.info("← %s %s  %s  (%.1f ms)", method, url, response.status_code, elapsed_ms)

        # DEBUG: response body
        if log.isEnabledFor(logging.DEBUG):
            log.debug("   response body: %s", api_resp.response_body_text())

        # Structured sentinel — parsed by HTMLReporter to build request/response banners
        log.debug(
            "__API_CALL__ %s",
            json.dumps(
                {
                    "method": method,
                    "url": url,
                    "req_headers": {
                        k: v
                        for k, v in dict(self._session.headers).items()
                        if k.lower() not in ("authorization",)  # never log auth tokens
                    },
                    "req_body": api_resp.request_body_text()[:2000],
                    "status": response.status_code,
                    "elapsed_ms": round(elapsed_ms, 1),
                    "res_headers": dict(response.headers),
                    "res_body": api_resp.response_body_text()[:2000],
                },
                separators=(",", ":"),
            ),
        )

        return api_resp

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
