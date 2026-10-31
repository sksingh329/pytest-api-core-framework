"""
Secret redaction for logs, ``__API_CALL__`` / ``__API_ASSERT__`` sentinels,
assertion messages, and the HTML report.

Two complementary strategies are applied:

1. **Key-based** — values stored under a sensitive key (header name, JSON key,
   query/form parameter, json_path segment) are replaced with ``REDACTED``.
   A key is sensitive if its normalised form (lower-cased, ``-``/``_``
   removed) contains any of ``_SENSITIVE_FRAGMENTS`` or a key registered via
   :func:`add_sensitive_keys` / the ``api_redact_keys`` ini option.
2. **Value-based** — known secret values (registered by the auth handlers or
   via :func:`register_secret`) plus ``Bearer``/``Basic`` credentials and JWTs
   are scrubbed from any free text, wherever they appear.

Usage
-----
    from pytest_api_core.security import register_secret, add_sensitive_keys

    register_secret(os.environ["MY_SESSION_TOKEN"])
    add_sensitive_keys("x-tenant-signature", "otp")
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "***REDACTED***"

# Matched as substrings of the normalised key, e.g. "token" covers
# access_token, refresh_token, x-auth-token, id_token, …
_SENSITIVE_FRAGMENTS: tuple[str, ...] = (
    "authorization",
    "cookie",
    "password",
    "passwd",
    "secret",
    "token",
    "apikey",
    "credential",
    "privatekey",
)

# Registered secrets shorter than this are ignored — masking "1" or "ab"
# everywhere would mangle unrelated output.
_MIN_SECRET_LEN = 4

_lock = threading.Lock()
_extra_keys: set[str] = set()
_secrets: set[str] = set()

_AUTH_SCHEME_RE = re.compile(r"\b(Bearer|Basic|Token)\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")
# key=value pairs in query strings / form bodies / log text. The value stops
# at characters that would end a JSON string so scrubbing sentinels keeps them valid.
_KV_RE = re.compile(r"([A-Za-z0-9_.\-]+)=([^&\s\"',;]+)")
# "key": "value" pairs inside JSON text that couldn't be parsed (e.g. truncated).
_JSON_KV_RE = re.compile(r'"([^"\\]+)"(\s*:\s*)"((?:[^"\\]|\\.)*)"')


def _normalise(key: str) -> str:
    return key.lower().replace("-", "").replace("_", "")


def add_sensitive_keys(*keys: str) -> None:
    """Treat *keys* (headers, JSON keys, params) as sensitive in addition to the defaults."""
    with _lock:
        _extra_keys.update(_normalise(k) for k in keys if k and k.strip())


def register_secret(value: str | None) -> None:
    """Scrub *value* from all framework output wherever it appears."""
    if value and len(value) >= _MIN_SECRET_LEN:
        with _lock:
            _secrets.add(value)


def is_sensitive_key(key: object) -> bool:
    """Return True if values stored under *key* must never be logged."""
    if not isinstance(key, str):
        return False
    norm = _normalise(key)
    return norm in _extra_keys or any(f in norm for f in _SENSITIVE_FRAGMENTS)


def is_sensitive_path(path: str | None) -> bool:
    """Return True if any segment of a ``$.a.b[0].c`` path is a sensitive key."""
    if not path:
        return False
    return any(is_sensitive_key(seg) for seg in re.split(r"[.\[\]$]+", path) if seg)


def mask(value: Any) -> Any:
    """Fully mask *value*, keeping ``None`` visible so null-checks stay readable."""
    return None if value is None else REDACTED


def scrub_text(text: str) -> str:
    """Remove registered secrets, auth-scheme credentials, JWTs and sensitive k=v pairs."""
    if not text:
        return text
    with _lock:
        secrets = sorted(_secrets, key=len, reverse=True)
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    text = _AUTH_SCHEME_RE.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
    text = _JWT_RE.sub(REDACTED, text)
    text = _KV_RE.sub(
        lambda m: f"{m.group(1)}={REDACTED}" if is_sensitive_key(m.group(1)) else m.group(0), text
    )
    return text


def redact(value: Any) -> Any:
    """Recursively redact a JSON-like structure (dicts, lists, strings)."""
    if isinstance(value, Mapping):
        return {k: (mask(v) if is_sensitive_key(k) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return scrub_text(value)
    return value


def redact_headers(headers: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a plain dict copy of *headers* with sensitive values masked."""
    return redact(dict(headers or {}))  # type: ignore[no-any-return]


def redact_url(url: str) -> str:
    """Mask sensitive query parameters (and any embedded credentials) in *url*."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return scrub_text(url)
    netloc = parts.netloc
    if "@" in netloc:
        netloc = f"{REDACTED}@{netloc.rsplit('@', 1)[1]}"
    query = parts.query
    if query:
        pairs = parse_qsl(query, keep_blank_values=True)
        query = urlencode([(k, REDACTED if is_sensitive_key(k) else v) for k, v in pairs], safe="*")
    return scrub_text(urlunsplit(parts._replace(netloc=netloc, query=query)))


def redact_text(text: str) -> str:
    """Redact a request/response body: JSON-aware, with a regex fallback for other text."""
    if not text:
        return text
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, (dict, list)):
        return json.dumps(redact(parsed), indent=2)
    text = _JSON_KV_RE.sub(
        lambda m: (
            f'"{m.group(1)}"{m.group(2)}"{REDACTED}"'
            if is_sensitive_key(m.group(1))
            else m.group(0)
        ),
        text,
    )
    return scrub_text(text)


def schema_error_message(error: Any) -> str:
    """Safe message for a ``jsonschema.ValidationError`` — its default message
    quotes the offending value, which must not leak for sensitive fields."""
    path = list(getattr(error, "absolute_path", []) or [])
    if any(is_sensitive_key(p) for p in path):
        where = ".".join(str(p) for p in path)
        return f"'{error.validator}' validation failed for sensitive field '{where}'"
    return scrub_text(str(error.message))


class RedactingFilter(logging.Filter):
    """Logging filter that scrubs secrets from the fully-formatted message.

    Safety net for log lines the framework doesn't build itself (e.g. urllib3's
    ``"GET /path?api_key=… HTTP/1.1"`` debug lines).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # malformed record — let logging report it as usual
            return True
        scrubbed = scrub_text(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = None
        return True


# Loggers whose records get the RedactingFilter. Logger-level filters don't
# apply to child loggers, so each emitting logger is listed explicitly.
FILTERED_LOGGERS: tuple[str, ...] = (
    "pytest_api_core",
    "pytest_api_core.client",
    "pytest_api_core.assertions",
    "pytest_api_core.auth",
    "pytest_api_core.config",
    "urllib3.connectionpool",
)

_filter = RedactingFilter()


def install_log_filter() -> None:
    """Attach the RedactingFilter to the framework and urllib3 loggers (idempotent)."""
    for name in FILTERED_LOGGERS:
        logger = logging.getLogger(name)
        if _filter not in logger.filters:
            logger.addFilter(_filter)
