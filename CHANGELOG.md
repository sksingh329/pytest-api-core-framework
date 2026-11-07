# Changelog

All notable changes to pytest-api-core will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.1] - 2026-11-08

### Fixed
- A failing `soft_assertions()` block no longer shows the framework's own code
  (`soft.py`, `contextlib`) in the pytest traceback / HTML report — the failure
  points at the test's `with soft_assertions():` line followed by the combined message
- HTML report: `actual=` on a passed assertion row is shown in green, not in the
  failure red
- HTML report: the theme toggle's label now names the theme it switches to, and
  toggling no longer overwrites the "Run Info" button's label
- `token_type` (the OAuth 2.0 token-response field, e.g. `"Bearer"`) is no longer
  masked as if it were a secret; other `*token*` keys are still masked, and
  `add_sensitive_keys("token_type")` restores masking if needed

## [1.1.0] - 2026-11-08

### Added
- Standalone assertion helpers (`assert_equal`, `assert_contains`, …) label each
  assertion with a field name, shown in the HTML report next to the expected/actual
  values and prefixed to the failure message. It defaults to the source text of the
  first argument (e.g. `body["name"]`) when that is a variable, attribute or subscript,
  and can be set with `field="..."`; a sensitive field name masks the values
- `has_key()` / `has_header()` now record the value found, so the report shows it
- The HTML report now shows the substring checked by `assert_contains`
- `soft_assertions()` context manager: collects every failing assertion in the block
  (both `assert_that(...)` chains and `assert_*` helpers) and raises one combined
  `AssertionError` at the end; every assertion still appears in the HTML report
- New `json_path()` matchers: `not_equals`, `is_type`, `contains`, `is_in`, `has_length`,
  `is_empty`, `is_not_empty`, `greater_than`, `less_than`, `between`; plus chain-level
  `has_path()` / `not_has_path()`
- A failing `json_path()` (missing path) now emits its own row in the HTML report
- Requests that fail without a response (timeouts, connection errors) now appear in the
  HTML report as an ERROR banner with the redacted error message; the exception is
  still re-raised
- "Copy cURL" button on each request in the HTML report (built from the redacted data,
  so secrets show as `***REDACTED***`)
- "Endpoint performance" table in the HTML report: calls, min/p50/p95/max latency and
  error count per `METHOD /path/{id}`, slowest p95 first

### Changed
- Standalone helpers now take their field name from the first argument when `field=`
  isn't passed. If any part of that name looks sensitive (`token`, `password`, …), the
  values are masked in the report and failure message — e.g. `assert_equal(token_count, 3)`
  now shows `***REDACTED***`. Pass a non-sensitive name such as `field="count"` to show them
- `has_key()` / `has_header()` report rows now include the value found (masked for
  sensitive keys and headers)
- `ResponseAssertions` methods are wrapped to support soft mode; outside
  `soft_assertions()` behaviour is unchanged and the wrapper frame is hidden from
  pytest tracebacks
- Docs: values extracted with jsonpath-ng are now shown checked with the standalone
  helpers (`assert_equal(..., field=...)`) instead of a bare `assert`, so they keep the
  HTML report row, redaction and `soft_assertions()` support

## [1.0.10] - 2026-11-02

### Fixed
- Quoted sensitive values (`"token": "..."`, `'token': '...'`, `token="..."`) are now
  redacted from free text, so secrets written as literals in test source or shown in dict
  reprs no longer appear in the HTML report's failure traceback, logs or stdout

## [1.0.9] - 2026-11-02

### Fixed
- `matches_schema()` no longer chains the raw `jsonschema.ValidationError` onto its
  `AssertionError`; the chained error's message dumped the full failing instance, exposing
  tokens and other sensitive fields in pytest failure traces and the HTML report

## [1.0.8] - 2026-11-01

### Changed
- First release published from the `sksingh329/pytest-api-core-framework` repository via
  the "Publish to Public PyPI" workflow; no code changes from 1.0.7

## [1.0.7] - 2026-10-31

### Fixed
- `pytest_api_core.__version__` and the README's `pip install` lines reported `1.1.0` in
  the 1.0.6 release (it was prepared as 1.1.0 but published as 1.0.6) — all version
  references now match the published version

## [1.0.6] - 2026-10-31

### Security
- Secrets are now redacted (`***REDACTED***`) from raw logs, `__API_CALL__` /
  `__API_ASSERT__` sentinels, assertion failure messages, and the HTML report.
  Previously the DEBUG request log printed all session headers (incl. `Authorization`),
  and only the `Authorization` header was stripped from the report — API keys, cookies,
  tokens in bodies/URLs, and values in assertions on sensitive fields leaked.

### Added
- `pytest_api_core.security` module with `register_secret()` and `add_sensitive_keys()`
  (also exported from `pytest_api_core`)
- `api_redact_keys` ini option for extra sensitive key names
- `sensitive=True` keyword on the standalone `assert_*` string helpers

### Changed
- Report request headers now show the headers actually sent (incl. auth, masked)
  rather than the session's default headers

### Known issues
- The published 1.0.6 package reports `pytest_api_core.__version__ == "1.1.0"` and its
  PyPI page README shows `pip install pytest-api-core==1.1.0` — the release was prepared
  as 1.1.0 but published as 1.0.6. Fixed in 1.0.7.

## [1.0.5] - 2026-07-05

### Fixed
- README's `pip install` version references were left at 1.0.3 in the 1.0.4
  release (the fix landed in git after 1.0.4 was already published to PyPI,
  which is immutable per-version) — corrected README is now baked into this
  release
- `publish-public.yml`'s test matrix now covers Python 3.9-3.14, matching
  `test-suite.yml` (it was previously stuck at 3.9-3.12)

## [1.0.4] - 2026-07-05

### Added
- MIT license classifier in `pyproject.toml` so PyPI displays the license correctly
- Python 3.13 and 3.14 classifiers
- `test-suite.yml` GitHub Actions workflow: runs unit + e2e tests on every push/PR
  to any branch, on Python 3.9-3.14, plus manual dispatch with a per-version option
- Test HTML report is now published to GitHub Pages after every workflow run

### Removed
- `deploy/` directory (self-hosted private PyPI index setup) — no longer used
  now that releases publish to public PyPI only

## [1.0.3] - 2026-07-02

### Added
- Standalone string assertion utilities (`assert_equal`, `assert_not_equal`,
  `assert_equal_ignore_case`, `assert_contains`, `assert_matches`, `assert_is_empty`,
  `assert_is_not_empty`) for comparing arbitrary values outside the fluent
  `assert_that()` chain
- Standalone `assert_matches_schema()` for validating any value against a JSON
  Schema, independent of an `APIResponse`; collects all validation errors
  (not just the first)
- HTML report renders the schema and actual value for `assert_matches_schema()`
  in a collapsible "Schema details" panel

### Fixed
- HTML report now captures logs from the `setup` and `teardown` pytest phases,
  not just `call` — previously fixture setup/teardown logs (and teardown
  failures) were silently dropped from the report
- CI now fails if a pushed release tag doesn't match `pyproject.toml`'s version,
  to prevent the version/tag drift that caused this file to fall out of sync
  with the `v1.0.2` release

## [1.0.2] - 2026-06-02

No functional changes from 1.0.1 — the `v1.0.1` release was never tagged in
git; this tag corresponds to the same commit and content described below.

## [1.0.1] - 2026-06-02

### Added
- GitHub Actions workflow for publishing to public PyPI
- Expand All / Collapse All buttons in HTML report
- Per-test chevron arrows for expand/collapse in HTML report
- Configurable HTML report theme, title, and header via pytest.ini
- Complete publishing documentation in docs/PUBLISHING.md

### Changed
- Improved HTML report table text readability with better contrast
- Updated README with About section and publishing instructions
- Updated pyproject.toml with correct GitHub repository URLs

### Fixed
- HTML report header/value column contrast issues
- GitHub Actions workflow permissions for release creation

## [1.0.0] - 2026-06-01

### Added
- Initial release of pytest-api-core framework
- APIClient with retry logic and structured logging
- Fluent response assertions API
- Multiple authentication strategies (Bearer, Basic, API Key, OAuth2)
- BaseSettings pattern for environment configuration
- .env file support via env_loader utility
- Custom HTML reporter with Jinja2 templates
- HTTP request/response banners in HTML report
- Visual assertion panels with pass/fail indicators
- Sentinel logging for API calls and assertions
- Auto-registered pytest fixtures
- Timestamped and environment-specific report paths
- Dark/light theme toggle in HTML reports
- pytest.ini configuration support
- Comprehensive test suite
- Documentation and usage examples

### Features
- Session-scoped fixtures: `api_config`, `api_client`
- Function-scoped auth fixtures: `api_bearer_auth`, `api_basic_auth`, `api_key_auth`
- Fluent assertions: `.status_is()`, `.has_key()`, `.json_path()`, `.matches_schema()`, etc.
- Configurable retry with exponential backoff
- Structured logging at multiple levels (DEBUG, INFO, WARNING)
- Environment variable resolution with precedence
- YAML configuration removed (replaced with Python settings classes)
- Self-contained HTML reports with embedded CSS/JavaScript
- Filterable test results by status
- Collapsible test details with logs, stdout, stderr, and failures

[1.0.5]: https://github.com/sksingh329/pytest-api-core-framework/compare/v1.0.4...v1.0.5
[1.0.4]: https://github.com/sksingh329/pytest-api-core-framework/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/sksingh329/pytest-api-core-framework/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/sksingh329/pytest-api-core-framework/releases/tag/v1.0.2
[1.0.1]: https://github.com/sksingh329/pytest-api-core-framework/compare/v1.0.0...v1.0.2
[1.0.0]: https://github.com/sksingh329/pytest-api-core-framework/releases/tag/v1.0.0
