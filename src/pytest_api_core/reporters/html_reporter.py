"""
Custom HTML reporter for pytest-api-core.

Generates a single self-contained HTML file from a Jinja2 template with:
  - Summary card: total / passed / failed / error / skipped counts + duration
  - SVG donut chart
  - Filterable, sortable results table
  - Per-test expandable panels:
      • HTTP call banners (method badge, URL, status, elapsed) with
        tabbed Request Headers / Req Body / Res Headers / Res Body
      • Assertion result rows (✅/❌ with expected vs actual)
      • Captured logs, stdout, failure traceback
  - Dark/light mode toggle
"""

from __future__ import annotations

import datetime
import getpass
import json
import platform
import re
from pathlib import Path
from typing import Any

import pytest
from jinja2 import Environment, PackageLoader

_jinja_env = Environment(
    loader=PackageLoader("pytest_api_core", "reporters/templates"),
    autoescape=True,
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class _TestRecord:
    __slots__ = (
        "node_id",
        "name",
        "outcome",  # "passed" | "failed" | "error" | "skipped"
        "duration",  # seconds
        "stdout",
        "stderr",
        "logs",  # captured log output (displayed in template)
        "longrepr",  # failure text
        "api_calls",  # list[dict] — parsed from __API_CALL__ sentinels
        "assertions",  # list[dict] — parsed from __API_ASSERT__ sentinels
        "markers",
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
        self.api_calls: list[dict[str, Any]] = []
        self.assertions: list[dict[str, Any]] = []
        self.markers: list[str] = []
        self._seen_log_headers: set[str] = set()


# ---------------------------------------------------------------------------
# Plugin hooks
# ---------------------------------------------------------------------------


class HTMLReporter:
    """pytest plugin that captures results and writes an HTML report on finish."""

    def __init__(self, report_path: str, config: pytest.Config) -> None:
        self._path = Path(report_path)
        self._records: dict[str, _TestRecord] = {}
        self._start_time: datetime.datetime = datetime.datetime.now()
        self._total_duration = 0.0
        self._theme = config.getini("api_html_theme") or "dark"
        self._title = config.getini("api_html_title") or "API Test Report"
        self._header = config.getini("api_html_header") or "API Test Report"
        self._run_info = _collect_run_info(config)

    # -- collection ----------------------------------------------------------

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        # Pre-register every collected item so the table order is stable
        for item in session.items:
            rec = _TestRecord(item.nodeid)
            rec.markers = [m.name for m in item.iter_markers()]
            self._records[item.nodeid] = rec

    # -- per-test result capture ---------------------------------------------

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        node_id = report.nodeid
        if node_id not in self._records:
            self._records[node_id] = _TestRecord(node_id)

        rec = self._records[node_id]

        if report.when == "setup" and report.skipped and not report.failed:
            rec.outcome = "skipped"
            if report.longrepr:
                rec.longrepr = str(report.longrepr)
            return

        # setup, call, and teardown phases all contribute duration/logs/output —
        # accumulate rather than overwrite so nothing from setup or teardown is lost.
        rec.duration += report.duration
        self._total_duration += report.duration

        if report.when == "call":
            if report.passed:
                rec.outcome = "passed"
            elif report.failed:
                rec.outcome = "failed"
            elif report.skipped:
                rec.outcome = "skipped"
        elif report.failed:
            # A failure during setup or teardown is a pytest "error", not a "failed"
            # assertion — don't downgrade an already-failed call outcome though.
            if rec.outcome != "failed":
                rec.outcome = "error"

        # capstdout/capstderr are cumulative across phases (the teardown report's
        # value already includes setup + call + teardown output) — overwrite,
        # don't accumulate, or output would be duplicated.
        if report.capstdout:
            rec.stdout = report.capstdout
        if report.capstderr:
            rec.stderr = report.capstderr

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
                        rec.api_calls.append(json.loads(payload))
                    except (ValueError, IndexError):
                        pass
                    continue  # don't add to human log
                if "__API_ASSERT__" in raw_line:
                    try:
                        payload = raw_line.split("__API_ASSERT__", 1)[1].strip()
                        rec.assertions.append(json.loads(payload))
                    except (ValueError, IndexError):
                        pass
                    continue  # don't add to human log
                clean_lines.append(raw_line)
            section_text = "\n".join(clean_lines).strip()
            if section_text:
                log_text += f"--- {header} ---\n{section_text}\n"
        rec.logs += log_text

        # Capture failure text
        if report.longrepr:
            rec.longrepr += ("\n\n" if rec.longrepr else "") + str(report.longrepr)

    # -- session finish — write report ----------------------------------------

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        html_content = _render_report(
            records=list(self._records.values()),
            start_time=self._start_time,
            total_duration=self._total_duration,
            theme=self._theme,
            title=self._title,
            header=self._header,
            run_info=self._run_info,
        )
        self._path.write_text(html_content, encoding="utf-8")
        # Print path relative to cwd for readability
        try:
            rel = self._path.relative_to(Path.cwd())
        except ValueError:
            rel = self._path
        print(f"\n  📄  API HTML report: {rel}\n")


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
    counts: dict[str, int] = {"passed": 0, "failed": 0, "error": 0, "skipped": 0, "unknown": 0}
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
        pass_rate=f"{(counts['passed'] / total * 100):.1f}" if total else "0.0",
        donut_svg=_donut_svg(counts, total),
        theme=theme,
        report_title=title,
        report_header=header,
        run_info=run_info,
    )


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from a string."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _donut_svg(counts: dict[str, int], total: int) -> str:
    if total == 0:
        return '<svg width="140" height="140"><circle cx="70" cy="70" r="55" fill="none" stroke="#ccc" stroke-width="20"/></svg>'

    colors = {"passed": "#22c55e", "failed": "#ef4444", "error": "#f97316", "skipped": "#94a3b8"}
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
