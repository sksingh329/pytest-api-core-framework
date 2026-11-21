"""
Custom HTML reporter for pytest-api-core.

Generates a single self-contained HTML file from a Jinja2 template with:
  - Summary card: total / passed / failed / error / skipped counts + duration
  - SVG donut chart
  - Filterable results table, sortable by status / test ID / duration / calls
  - Per-test expandable panels:
      • HTTP call banners (method badge, URL, status, elapsed, retry count) with
        tabbed Request Headers / Req Body / Res Headers / Res Body / Attempts
      • Assertion result rows (✅/❌ with expected vs actual)
      • Captured logs, stdout, failure traceback
  - Dark/light mode toggle
"""

from __future__ import annotations

import datetime
import difflib
import getpass
import json
import math
import os
import platform
import re
import shlex
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import pytest
from jinja2 import Environment, PackageLoader
from markupsafe import Markup, escape

from pytest_api_core.security.redaction import redact, scrub_text

_jinja_env = Environment(
    loader=PackageLoader("pytest_api_core", "reporters/templates"),
    autoescape=True,
)
# Registered at the bottom of the module, once _to_curl is defined.


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class _TestRecord:
    __slots__ = (
        "node_id",
        "name",
        "outcome",  # "passed" | "failed" | "error" | "skipped" | "xfailed" | "xpassed"
        "duration",  # seconds
        "stdout",
        "stderr",
        "logs",  # captured log output (displayed in template)
        "longrepr",  # failure text
        "crash",  # one-line exception message of the first failure (pytest's reprcrash)
        "api_calls",  # list[dict] — parsed from __API_CALL__ sentinels
        "assertions",  # list[dict] — parsed from __API_ASSERT__ sentinels
        "markers",
        "worker",  # pytest-xdist worker id ("gw0", …) or "" when not parallel
        "_seen_log_headers",  # pytest re-attaches earlier phases' sections to later
        # reports verbatim, so track which section headers were already
        # processed for this test to avoid duplicating logs/sentinels.
    )

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.name = node_id.split("::")[-1]
        self.outcome = "unknown"
        self.duration = 0.0
        self.stdout = ""
        self.stderr = ""
        self.logs = ""
        self.longrepr = ""
        self.crash = ""
        self.api_calls: list[dict[str, Any]] = []
        self.assertions: list[dict[str, Any]] = []
        self.markers: list[str] = []
        self.worker = ""
        self._seen_log_headers: set[str] = set()


# ---------------------------------------------------------------------------
# Plugin hooks
# ---------------------------------------------------------------------------


# Report attribute carrying a test's marker names. pytest-xdist serialises every
# JSON-safe attribute of a TestReport, so this survives the worker → controller hop
# (the controller never collects items itself, so it cannot look markers up).
_MARKERS_ATTR = "api_core_markers"


class MarkerTagger:
    """Attach marker names to each test report.

    Registered in every process — including pytest-xdist workers — so the
    controller-side ``HTMLReporter`` can show markers for tests it never collected.
    """

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call: pytest.CallInfo[None]) -> Any:
        outcome = yield
        report = outcome.get_result()
        setattr(report, _MARKERS_ATTR, [m.name for m in item.iter_markers()])


def _worker_id(node: Any) -> str:
    """Return the xdist worker id ("gw0", …) for a WorkerController, or ""."""
    return str(getattr(getattr(node, "gateway", None), "id", "") or "")


def _workers_info(workers: set[str]) -> list[tuple[str, str]]:
    """Run-info row describing the parallel workers, if any were used."""
    if not workers:
        return []
    ordered = sorted(workers, key=lambda w: (len(w), w))  # gw2 before gw10
    return [("Parallel workers", f"{len(ordered)} ({', '.join(ordered)})")]


def is_xdist_worker(config: pytest.Config) -> bool:
    """True when running inside a pytest-xdist worker process."""
    return hasattr(config, "workerinput")


class HTMLReporter:
    """pytest plugin that captures results and writes an HTML report on finish.

    Under pytest-xdist it must only be registered on the controller: workers'
    reports are forwarded to the controller's ``pytest_runtest_logreport`` hook,
    so the controller sees every result and writes the single report file.
    """

    def __init__(self, report_path: str, config: pytest.Config) -> None:
        self._path = Path(report_path)
        self._records: dict[str, _TestRecord] = {}
        self._start_time: datetime.datetime = datetime.datetime.now()
        self._total_duration = 0.0
        # Set when tests run in parallel: summed test durations would then
        # overstate the run time, so the wall-clock time is reported instead.
        self._parallel = False
        self._workers: set[str] = set()
        self._written = False
        self._theme = config.getini("api_html_theme") or "dark"
        self._title = config.getini("api_html_title") or "API Test Report"
        self._header = config.getini("api_html_header") or "API Test Report"
        self._run_info = _collect_run_info(config)
        # Where the report will be served from once published (CI) — env wins over ini.
        self._public_base = (
            os.environ.get("API_HTML_REPORT_URL") or config.getini("api_html_report_url") or ""
        ).strip()

    # -- collection ----------------------------------------------------------

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        # Pre-register every collected item so the table order is stable
        for item in session.items:
            rec = _TestRecord(item.nodeid)
            rec.markers = [m.name for m in item.iter_markers()]
            self._records[item.nodeid] = rec

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node: Any, ids: list[str]) -> None:
        """pytest-xdist controller hook: pre-register tests in collection order."""
        self._parallel = True
        worker_id = _worker_id(node)
        if worker_id:
            self._workers.add(worker_id)
        for node_id in ids:
            if node_id not in self._records:
                self._records[node_id] = _TestRecord(node_id)

    # -- per-test result capture ---------------------------------------------

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        node_id = report.nodeid
        if node_id not in self._records:
            self._records[node_id] = _TestRecord(node_id)

        rec = self._records[node_id]
        markers = getattr(report, _MARKERS_ATTR, None)
        if markers and not rec.markers:
            rec.markers = list(markers)
        # xdist sets ``report.node`` (the worker controller) on reports it forwards
        worker_id = _worker_id(getattr(report, "node", None))
        if worker_id:
            rec.worker = worker_id
            self._workers.add(worker_id)

        if report.when == "setup" and report.skipped and not report.failed:
            # pytest.xfail() called from a fixture, or @xfail(run=False)
            rec.outcome = "xfailed" if hasattr(report, "wasxfail") else "skipped"
            if report.longrepr:
                rec.longrepr = scrub_text(str(report.longrepr))
            return

        # setup, call, and teardown phases all contribute duration/logs/output —
        # accumulate rather than overwrite so nothing from setup or teardown is lost.
        rec.duration += report.duration
        self._total_duration += report.duration

        if report.when == "call":
            # pytest marks expected-failure outcomes with ``wasxfail``: an xfail
            # test that failed is reported as skipped, one that unexpectedly
            # passed (non-strict) as passed. Strict XPASS is a plain failure.
            xfail = hasattr(report, "wasxfail")
            if report.passed:
                rec.outcome = "xpassed" if xfail else "passed"
            elif report.failed:
                rec.outcome = "failed"
            elif report.skipped:
                rec.outcome = "xfailed" if xfail else "skipped"
        elif report.failed:
            # A failure during setup or teardown is a pytest "error", not a "failed"
            # assertion — don't downgrade an already-failed call outcome though.
            if rec.outcome != "failed":
                rec.outcome = "error"

        # capstdout/capstderr are cumulative across phases (the teardown report's
        # value already includes setup + call + teardown output) — overwrite,
        # don't accumulate, or output would be duplicated.
        if report.capstdout:
            rec.stdout = scrub_text(report.capstdout)
        if report.capstderr:
            rec.stderr = scrub_text(report.capstderr)

        # Parse captured log sections. Unlike capstdout/capstderr, pytest
        # re-attaches each phase's *own* section verbatim to every later report
        # for the same test, so dedupe by header to avoid processing (and thus
        # logging/sentinel-parsing) the same section more than once.
        log_text = ""
        for header, content in report.sections:
            if "log" not in header.lower() or not content.strip():
                continue
            if header in rec._seen_log_headers:
                continue
            rec._seen_log_headers.add(header)
            clean_lines = []
            for raw_line in _strip_ansi(content).splitlines():
                if "__API_CALL__" in raw_line:
                    try:
                        payload = raw_line.split("__API_CALL__", 1)[1].strip()
                        rec.api_calls.append(redact(json.loads(payload)))
                    except (ValueError, IndexError):
                        pass
                    continue  # don't add to human log
                if "__API_ASSERT__" in raw_line:
                    try:
                        payload = raw_line.split("__API_ASSERT__", 1)[1].strip()
                        rec.assertions.append(redact(json.loads(payload)))
                    except (ValueError, IndexError):
                        pass
                    continue  # don't add to human log
                clean_lines.append(scrub_text(raw_line))
            section_text = "\n".join(clean_lines).strip()
            if section_text:
                log_text += f"--- {header} ---\n{section_text}\n"
        rec.logs += log_text

        # Capture failure text
        if report.failed and not rec.crash:
            crash = getattr(getattr(report.longrepr, "reprcrash", None), "message", "")
            rec.crash = scrub_text(str(crash or ""))
        if report.longrepr:
            rec.longrepr += ("\n\n" if rec.longrepr else "") + scrub_text(str(report.longrepr))

    # -- session finish — write report ----------------------------------------

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if self._parallel:
            elapsed = datetime.datetime.now() - self._start_time
            self._total_duration = elapsed.total_seconds()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        html_content = _render_report(
            # Tests that never reported (e.g. deselected on a crashed worker) stay "unknown"
            records=list(self._records.values()),
            start_time=self._start_time,
            total_duration=self._total_duration,
            theme=self._theme,
            title=self._title,
            header=self._header,
            run_info=self._run_info + _workers_info(self._workers),
        )
        self._path.write_text(html_content, encoding="utf-8")
        self._written = True

    def pytest_terminal_summary(self, terminalreporter: Any) -> None:
        # Runs after pytest_sessionfinish (report already written) but before
        # pytest's final "N passed, M failed" line, which tools parse as the last
        # line of output — so the link must not be printed after it.
        if self._written:
            terminalreporter.write_line("")
            terminalreporter.write_line(f"  📄  API HTML report: {_terminal_link(self.report_uri)}")

    @property
    def report_uri(self) -> str:
        """Public URL of the report if a base URL is configured, else its ``file://`` URI.

        Only the file *name* is appended to the base URL: publishing steps usually
        flatten the local directory layout (e.g. ``reports/dev/x.html`` →
        ``<site>/reports/x.html``), so point the base URL at the folder holding them.
        """
        if self._public_base:
            return f"{self._public_base.rstrip('/')}/{quote(self._path.name)}"
        return self._path.resolve().as_uri()


def _terminal_link(uri: str) -> str:
    """Make *uri* clickable in the terminal.

    Plain ``file://`` / ``https://`` URIs are auto-linked by most terminals
    (VS Code, iTerm2, Windows Terminal, GNOME) and by CI log viewers. When stdout
    is a TTY, the URI is additionally wrapped in an OSC 8 hyperlink escape so
    terminals that support explicit hyperlinks make it clickable too. Non-TTY
    output (CI logs, pipes) gets the bare URI with no escape codes.
    """
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        return f"\033]8;;{uri}\033\\{uri}\033]8;;\033\\"
    return uri


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _collect_run_info(config: pytest.Config) -> list[tuple[str, str]]:
    """Gather report/log config and machine details for the collapsible info panel."""
    env = config.getoption("--api-env", default=None) or config.getini("api_env") or "default"
    api_log_level = (
        config.getoption("--api-log-level", default=None)
        or config.getini("api_log_level")
        or "WARNING"
    )
    html_log_level = config.getini("log_level") or "WARNING"
    log_cli_level = config.getoption("log_cli_level", default=None) or config.getini(
        "log_cli_level"
    )
    log_cli = bool(log_cli_level) or bool(config.getini("log_cli"))

    return [
        ("Environment", env),
        ("api_log_level", api_log_level),
        ("HTML report log_level", html_log_level),
        ("log_cli", "enabled" if log_cli else "disabled"),
        ("log_cli_level", log_cli_level if log_cli else "—"),
        ("Hostname", platform.node()),
        ("User", getpass.getuser()),
        ("OS / Platform", platform.platform()),
        ("Python", platform.python_version()),
        ("Pytest", pytest.__version__),
    ]


def _render_report(
    records: list[_TestRecord],
    start_time: datetime.datetime,
    total_duration: float,
    theme: str,
    title: str,
    header: str,
    run_info: list[tuple[str, str]],
) -> str:
    counts: dict[str, int] = {
        "passed": 0,
        "failed": 0,
        "error": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
        "unknown": 0,
    }
    for rec in records:
        counts[rec.outcome] = counts.get(rec.outcome, 0) + 1

    total = len(records)
    template = _jinja_env.get_template("report.html")
    return template.render(
        records=records,
        generated_at=start_time.strftime("%Y-%m-%d %H:%M:%S"),
        duration=f"{total_duration:.2f}s",
        total=total,
        passed=counts["passed"],
        failed=counts["failed"],
        error=counts["error"],
        skipped=counts["skipped"],
        xfailed=counts["xfailed"],
        xpassed=counts["xpassed"],
        # Expected failures (and non-strict unexpected passes) don't fail the run,
        # so they count towards the pass rate rather than against it.
        pass_rate=_pass_rate(counts, total),
        donut_svg=_donut_svg(counts, total),
        theme=theme,
        report_title=title,
        report_header=header,
        run_info=run_info,
        endpoint_stats=_endpoint_stats(records),
        retried_calls=sum(1 for rec in records for call in rec.api_calls if call.get("retries")),
    )


_REASON_MAX = 200
# Assertion fields that say *what* was checked, in display order.
_ASSERT_TARGETS = ("field", "path", "key", "header")


def _shorten(text: str, limit: int = _REASON_MAX) -> str:
    text = " ".join(text.split())  # collapse newlines/indentation to one line
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _describe_assertion(a: dict[str, Any]) -> str:
    """One-line summary of a failed assertion sentinel, e.g. ``key_equals [id]: expected 1, got 2``."""
    target = next((str(a[k]) for k in _ASSERT_TARGETS if a.get(k) is not None), "")
    head = f"{a.get('name', 'assertion')}" + (f" [{target}]" if target else "")
    errors = a.get("errors")
    if errors:
        return f"{head}: {len(errors)} schema error(s) — {errors[0]}"
    diff = _assertion_diff(a)
    if diff and diff["rows"]:
        # JSON objects/arrays: name the differing paths rather than dumping both values
        total = len(diff["rows"]) + diff["more"]
        shown = ", ".join(f"{r['path']} {_DIFF_WORDS[r['kind']]}" for r in diff["rows"][:3])
        extra = f", +{total - 3} more" if total > 3 else ""
        return f"{head}: {total} difference(s) — {shown}{extra}"
    parts = []
    if "expected" in a:
        parts.append(f"expected {a['expected']!r}")
    if "actual" in a:
        parts.append(f"got {a['actual']!r}")
    return f"{head}: {', '.join(parts)}" if parts else head


def _last_error_line(longrepr: str) -> str:
    """First pytest ``E   …`` line of a traceback, else its last non-blank line."""
    lines = [ln.strip() for ln in longrepr.splitlines() if ln.strip()]
    for ln in lines:
        if ln.startswith("E "):
            return ln[1:].strip()
    return lines[-1] if lines else ""


def _failure_reason(rec: _TestRecord) -> str:
    """Short, already-redacted reason a test failed or errored ("" otherwise).

    Prefers the structured data the framework recorded — the first failed
    assertion, then a request that never got a response — over pytest's
    exception message, which falls back to the traceback's error line.
    """
    if rec.outcome not in ("failed", "error"):
        return ""
    failed = [a for a in rec.assertions if not a.get("passed", True)]
    if failed:
        reason = _describe_assertion(failed[0])
        if len(failed) > 1:
            reason += f" (+{len(failed) - 1} more failed assertion(s))"
        return _shorten(reason)
    for call in rec.api_calls:
        if call.get("error"):
            return _shorten(f"{call.get('method', '')} {call.get('url', '')} → {call['error']}")
    return _shorten(rec.crash or _last_error_line(rec.longrepr))


def _pass_rate(counts: dict[str, int], total: int) -> str:
    if not total:
        return "0.0"
    ok = counts["passed"] + counts["xfailed"] + counts["xpassed"]
    return f"{ok / total * 100:.1f}"


_CURL_SKIP_HEADERS = {"content-length"}


def _to_curl(call: dict[str, Any]) -> str:
    """Build a copy-pasteable cURL command from an ``__API_CALL__`` sentinel.

    The sentinel is already redacted, so masked secrets stay ``***REDACTED***``
    and must be filled in by hand before the command will authenticate.
    """
    parts = [
        "curl",
        "-X",
        shlex.quote(str(call.get("method", "GET"))),
        shlex.quote(str(call.get("url", ""))),
    ]
    headers = call.get("req_headers") or {}
    for name, value in headers.items():
        if str(name).lower() in _CURL_SKIP_HEADERS:
            continue
        parts += ["-H", shlex.quote(f"{name}: {value}")]
    body = call.get("req_body") or ""
    if body:
        parts += ["--data-raw", shlex.quote(str(body))]
    command = " \\\n  ".join(_pair_flags(parts))
    if call.get("req_body_truncated"):
        command += "\n# body truncated in report"
    return command


def _pair_flags(parts: list[str]) -> list[str]:
    """Keep each ``-H value`` / ``--data-raw value`` on one line of the multi-line command."""
    lines = [" ".join(parts[:4])]
    rest = parts[4:]
    for i in range(0, len(rest), 2):
        lines.append(" ".join(rest[i : i + 2]))
    return lines


_ID_SEGMENT_RE = re.compile(
    r"^(\d+|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)


def _endpoint_template(url: str) -> str:
    """``https://host/users/42?x=1`` → ``/users/{id}`` (numeric and UUID segments collapsed)."""
    path = urlsplit(url).path or "/"
    segments = ["{id}" if _ID_SEGMENT_RE.match(seg) else seg for seg in path.split("/")]
    return "/".join(segments) or "/"


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile of an already-sorted, non-empty list."""
    rank = max(1, math.ceil(pct / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


def _endpoint_stats(records: list[_TestRecord]) -> list[dict[str, Any]]:
    """Latency/error summary per ``METHOD /path/{id}``, slowest p95 first."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for rec in records:
        for call in rec.api_calls:
            key = (str(call.get("method", "?")), _endpoint_template(str(call.get("url", ""))))
            groups.setdefault(key, []).append(call)

    stats: list[dict[str, Any]] = []
    for (method, endpoint), calls in groups.items():
        times = sorted(float(c.get("elapsed_ms") or 0.0) for c in calls)
        errors = sum(
            1
            for c in calls
            if "error" in c or (isinstance(c.get("status"), int) and c["status"] >= 500)
        )
        stats.append(
            {
                "method": method,
                "endpoint": endpoint,
                "count": len(calls),
                "min": round(times[0], 1),
                "p50": round(_percentile(times, 50), 1),
                "p95": round(_percentile(times, 95), 1),
                "max": round(times[-1], 1),
                "errors": errors,
                "retried": sum(1 for c in calls if c.get("retries")),
            }
        )
    stats.sort(key=lambda s: s["p95"], reverse=True)
    return stats


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from a string."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _donut_svg(counts: dict[str, int], total: int) -> str:
    if total == 0:
        return '<svg width="140" height="140"><circle cx="70" cy="70" r="55" fill="none" stroke="#ccc" stroke-width="20"/></svg>'

    colors = {
        "passed": "#22c55e",
        "xpassed": "#14b8a6",
        "xfailed": "#a855f7",
        "failed": "#ef4444",
        "error": "#f97316",
        "skipped": "#94a3b8",
    }
    r = 55
    cx = cy = 70
    circumference = 2 * 3.14159 * r
    segments: list[str] = []
    offset = 0.0

    for outcome, color in colors.items():
        count = counts.get(outcome, 0)
        if count == 0:
            continue
        fraction = count / total
        dash = fraction * circumference
        segments.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" '
            f'stroke-width="20" stroke-dasharray="{dash:.2f} {circumference:.2f}" '
            f'stroke-dashoffset="-{offset:.2f}" transform="rotate(-90 {cx} {cy})"/>'
        )
        offset += dash

    inner_text = f'<text x="{cx}" y="{cy+5}" text-anchor="middle" font-size="18" font-weight="bold" fill="currentColor">{total}</text>'
    joined = "".join(segments)
    return f'<svg width="140" height="140">{joined}{inner_text}</svg>'


# ---------------------------------------------------------------------------
# JSON rendering: assertion diffs and pretty response/request bodies
# ---------------------------------------------------------------------------

_DIFF_WORDS = {
    "changed": "changed",
    "type": "type differs",
    "missing": "missing",
    "unexpected": "unexpected",
}
_DIFF_MAX_ROWS = 50  # differences listed per assertion
_DIFF_MAX_LINES = 400  # lines per side in the side-by-side view
# Bodies larger than this are shown raw: the collapsible tree multiplies the HTML
# size several times over, which would make reports with full-size payloads
# (api_body_limit = 0) slow to open.
_JSON_VIEW_MAX_CHARS = 500_000


def _pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str)


def _json_short(value: Any, limit: int = 120) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _diff_values(expected: Any, actual: Any, path: str, out: list[dict[str, str]]) -> None:
    """Collect differences between two JSON values as {path, kind, expected, actual} rows."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual), key=str):
            child = f"{path}.{key}"
            if key not in actual:
                out.append(
                    {
                        "path": child,
                        "kind": "missing",
                        "expected": _json_short(expected[key]),
                        "actual": "",
                    }
                )
            elif key not in expected:
                out.append(
                    {
                        "path": child,
                        "kind": "unexpected",
                        "expected": "",
                        "actual": _json_short(actual[key]),
                    }
                )
            else:
                _diff_values(expected[key], actual[key], child, out)
        return
    if isinstance(expected, list) and isinstance(actual, list):
        for i in range(max(len(expected), len(actual))):
            child = f"{path}[{i}]"
            if i >= len(actual):
                out.append(
                    {
                        "path": child,
                        "kind": "missing",
                        "expected": _json_short(expected[i]),
                        "actual": "",
                    }
                )
            elif i >= len(expected):
                out.append(
                    {
                        "path": child,
                        "kind": "unexpected",
                        "expected": "",
                        "actual": _json_short(actual[i]),
                    }
                )
            else:
                _diff_values(expected[i], actual[i], child, out)
        return
    # Compare JSON-equal values as equal (1 == 1.0, but not 1 == True or "1" == 1).
    if type(expected) is not type(actual) and not (
        isinstance(expected, (int, float))
        and isinstance(actual, (int, float))
        and not isinstance(expected, bool)
        and not isinstance(actual, bool)
    ):
        out.append(
            {
                "path": path,
                "kind": "type",
                "expected": _json_short(expected),
                "actual": _json_short(actual),
            }
        )
    elif expected != actual:
        out.append(
            {
                "path": path,
                "kind": "changed",
                "expected": _json_short(expected),
                "actual": _json_short(actual),
            }
        )


def _side_by_side(expected: Any, actual: Any) -> list[dict[str, str]]:
    """Align the pretty-printed values line by line, marking changed/missing/extra lines."""
    left = _pretty_json(expected).splitlines()[:_DIFF_MAX_LINES]
    right = _pretty_json(actual).splitlines()[:_DIFF_MAX_LINES]
    rows: list[dict[str, str]] = []
    matcher = difflib.SequenceMatcher(a=left, b=right, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            rows += [
                {"l": left[i], "r": right[j1 + n], "kind": "same"}
                for n, i in enumerate(range(i1, i2))
            ]
            continue
        a, b = left[i1:i2], right[j1:j2]
        for n in range(max(len(a), len(b))):
            rows.append(
                {
                    "l": a[n] if n < len(a) else "",
                    "r": b[n] if n < len(b) else "",
                    "kind": (
                        "chg" if n < len(a) and n < len(b) else ("del" if n < len(a) else "ins")
                    ),
                }
            )
    return rows


def _assertion_diff(a: dict[str, Any]) -> dict[str, Any] | None:
    """Structured expected-vs-actual diff for a failed assertion on JSON objects/arrays.

    Returns None when there is nothing structural to compare (passed assertion,
    scalar values, or a container compared against a scalar like "<missing>").
    Values in the sentinel are already redacted at emission time.
    """
    if a.get("passed", True) or "expected" not in a or "actual" not in a:
        return None
    expected, actual = a["expected"], a["actual"]
    if not (isinstance(expected, (dict, list)) and isinstance(actual, (dict, list))):
        return None
    base = a.get("path") or (f"$.{a['key']}" if a.get("key") else "$")
    rows: list[dict[str, str]] = []
    _diff_values(expected, actual, base, rows)
    return {
        "rows": rows[:_DIFF_MAX_ROWS],
        "more": max(0, len(rows) - _DIFF_MAX_ROWS),
        "lines": _side_by_side(expected, actual),
    }


def _jkey(key: str) -> str:
    return f'<span class="j-key">{escape(json.dumps(key, ensure_ascii=False))}</span>: '


def _jscalar(value: Any) -> str:
    if isinstance(value, str):
        cls = "j-str"
    elif isinstance(value, bool) or value is None:
        cls = "j-lit"
    else:
        cls = "j-num"
    return (
        f'<span class="{cls}">{escape(json.dumps(value, ensure_ascii=False, default=str))}</span>'
    )


def _jtree(value: Any, key_html: str = "", comma: str = "") -> str:
    """Render a JSON value as nested <details> nodes, collapsible per object/array."""
    is_dict = isinstance(value, dict)
    if isinstance(value, (dict, list)) and value:
        open_b, close_b = ("{", "}") if is_dict else ("[", "]")
        items = list(value.items()) if isinstance(value, dict) else list(enumerate(value))
        children = "".join(
            _jtree(v, _jkey(str(k)) if is_dict else "", "," if n < len(items) - 1 else "")
            for n, (k, v) in enumerate(items)
        )
        noun = ("key" if is_dict else "item") + ("" if len(items) == 1 else "s")
        return (
            f'<details class="j-node" open><summary>{key_html}<span class="j-p">{open_b}</span>'
            f'<span class="j-hint">…{close_b}{comma} <em>{len(items)} {noun}</em></span></summary>'
            f'<div class="j-children">{children}</div>'
            f'<div class="j-close"><span class="j-p">{close_b}</span>{comma}</div></details>'
        )
    if isinstance(value, (dict, list)):
        return f'<div class="j-line">{key_html}<span class="j-p">{"{}" if is_dict else "[]"}</span>{comma}</div>'
    return f'<div class="j-line">{key_html}{_jscalar(value)}{comma}</div>'


def _json_view(text: str | None) -> dict[str, Any] | None:
    """Pretty, collapsible rendering of a body that is valid JSON; None otherwise.

    Bodies are already redacted when captured. Truncated bodies are not valid JSON
    and fall back to the raw view.
    """
    if not text or len(text) > _JSON_VIEW_MAX_CHARS or text.lstrip()[:1] not in ("{", "["):
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    # Keep the body's own key order (only the diff view sorts keys, to align them).
    pretty = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    return {"tree": Markup(_jtree(value)), "pretty": pretty}


_jinja_env.filters["curl"] = _to_curl
_jinja_env.filters["assertion_diff"] = _assertion_diff
_jinja_env.filters["json_view"] = _json_view
_jinja_env.globals["diff_words"] = _DIFF_WORDS
_jinja_env.globals["json_view_max"] = _JSON_VIEW_MAX_CHARS
_jinja_env.filters["failure_reason"] = _failure_reason
