# Changelog

All notable changes to pytest-api-core will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[1.0.3]: https://github.com/sksingh329/pytest-api-core-framework/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/sksingh329/pytest-api-core-framework/releases/tag/v1.0.2
[1.0.1]: https://github.com/sksingh329/pytest-api-core-framework/compare/v1.0.0...v1.0.2
[1.0.0]: https://github.com/sksingh329/pytest-api-core-framework/releases/tag/v1.0.0
