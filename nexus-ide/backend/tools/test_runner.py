"""Test runner tool — execute pytest and return structured results.

Provides a single ``run_tests`` tool that wraps pytest invocation, parses
JUnit XML output (or stdout), and returns structured results including
passed/failed counts, coverage, and failed test details.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import xml.etree.ElementTree as ET
from typing import Any

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pytest helpers
# ---------------------------------------------------------------------------
def _has_pytest_module() -> bool:
    try:
        import pytest  # noqa: F401
        return True
    except ImportError:
        return False


_PYTEST_AVAILABLE = shutil.which("pytest") is not None or _has_pytest_module()


def _has_pytest_module() -> bool:
    try:
        import pytest  # noqa: F401
        return True
    except ImportError:
        return False


async def _run_pytest(
    args: list[str], cwd: str | None = None, timeout: int = 600
) -> tuple[int, str, str]:
    """Run pytest as subprocess and return (returncode, stdout, stderr)."""
    cmd = ["python", "-m", "pytest", *args]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (
            proc.returncode if proc.returncode is not None else -1,
            (stdout_b or b"").decode(errors="replace"),
            (stderr_b or b"").decode(errors="replace"),
        )
    except TimeoutError:
        return (-1, "", f"Timeout after {timeout}s")
    except FileNotFoundError:
        return (-1, "", "pytest not installed (pip install pytest)")


# ---------------------------------------------------------------------------
# Result parsers
# ---------------------------------------------------------------------------
def _parse_summary_line(stdout: str) -> dict[str, int]:
    """Extract the pytest summary line '=== X passed, Y failed in Zs ==='."""
    result = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "warnings": 0}
    # Find last line matching pattern
    summary_re = re.compile(
        r"(?:=+\s*)?(\d+)\s+(passed|failed|error|skipped|warning)", re.IGNORECASE
    )
    for match in summary_re.finditer(stdout):
        n = int(match.group(1))
        word = match.group(2).lower()
        if word in result:
            result[word] += n
    return result


def _parse_junit_xml(xml_path: str) -> dict[str, Any]:
    """Parse pytest JUnit XML output for detailed test results."""
    result: dict[str, Any] = {
        "tests": [],
        "failures": [],
        "errors": [],
        "skipped": [],
        "total": 0,
    }
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        # testsuite is the root or first child
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        if suite is None:
            return result
        for tc in suite.findall("testcase"):
            name = tc.get("name", "")
            classname = tc.get("classname", "")
            duration = float(tc.get("time", "0") or "0")
            entry: dict[str, Any] = {
                "name": name,
                "classname": classname,
                "duration": round(duration, 4),
            }
            result["tests"].append(entry)
            result["total"] += 1
            failure = tc.find("failure")
            if failure is not None:
                entry["status"] = "failed"
                entry["message"] = (failure.get("message") or "")[:500]
                result["failures"].append(entry)
            elif tc.find("error") is not None:
                entry["status"] = "error"
                error_el = tc.find("error")
                entry["message"] = (error_el.get("message") or "")[:500] if error_el is not None else ""
                result["errors"].append(entry)
            elif tc.find("skipped") is not None:
                entry["status"] = "skipped"
                result["skipped"].append(entry)
            else:
                entry["status"] = "passed"
    except ET.ParseError as e:
        logger.warning("JUnit XML parse error: %s", e)
    return result


def _parse_coverage_output(stdout: str) -> float | None:
    """Extract coverage percentage from pytest-cov output."""
    # Look for "TOTAL ... 87%" pattern
    m = re.search(r"TOTAL\s+\d+\s+\d+\s+(?:100|[\d.]+)%\s+([\d.]+)%", stdout)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, IndexError):
            pass
    return None


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------
async def run_tests(
    test_path: str = "",
    marker: str | None = None,
    coverage: bool = False,
    verbose: bool = False,
    fail_fast: bool = False,
    project_path: str | None = None,
    timeout: int = 600,
) -> dict:
    """Run pytest tests and return structured results.

    Args:
        test_path: Path to test file or directory (e.g. 'backend/tests'). Empty = auto-detect.
        marker: Optional pytest marker filter (e.g. 'slow', 'unit').
        coverage: If True, include coverage (requires pytest-cov).
        verbose: If True, use -v flag.
        fail_fast: If True, stop on first failure (-x flag).
        project_path: Working directory for pytest.
        timeout: Timeout in seconds (1-1800).
    """
    if not _PYTEST_AVAILABLE:
        return {"error": "pytest not installed (pip install pytest)"}

    timeout = min(max(timeout, 1), 1800)

    # Build args
    args: list[str] = []
    if verbose:
        args.append("-v")
    if fail_fast:
        args.append("-x")
    if coverage:
        args.extend(["--cov", ".", "--cov-report=term", "--cov-report=xml:/tmp/nexus-cov.xml"])
    if marker:
        args.extend(["-m", marker])

    # JUnit XML for structured results
    junit_path = "/tmp/nexus-junit.xml"
    args.extend([f"--junit-xml={junit_path}"])

    # Add test path
    if test_path:
        args.append(test_path)

    # Run
    returncode, stdout, stderr = await _run_pytest(args, cwd=project_path, timeout=timeout)

    # Parse results
    summary = _parse_summary_line(stdout)
    junit_data = _parse_junit_xml(junit_path) if os.path.exists(junit_path) else {"tests": [], "failures": [], "errors": [], "skipped": [], "total": 0}
    cov_pct = _parse_coverage_output(stdout) if coverage else None

    duration_match = re.search(r"in\s+([\d.]+)s", stdout)
    duration_s = float(duration_match.group(1)) if duration_match else None

    return {
        "status": "passed" if returncode == 0 else ("failed" if returncode in (1, 2) else "error"),
        "returncode": returncode,
        "passed": summary["passed"],
        "failed": summary["failed"],
        "errors": summary["errors"],
        "skipped": summary["skipped"],
        "warnings": summary["warnings"],
        "total": junit_data["total"] or (summary["passed"] + summary["failed"] + summary["skipped"]),
        "duration_s": duration_s,
        "coverage_percent": cov_pct,
        "failed_tests": [
            {"name": t.get("name"), "classname": t.get("classname"), "message": t.get("message", "")}
            for t in junit_data["failures"]
        ],
        "error_tests": [
            {"name": t.get("name"), "classname": t.get("classname"), "message": t.get("message", "")}
            for t in junit_data["errors"]
        ],
        "stdout_tail": stdout[-2000:] if stdout else "",  # last 2KB
        "stderr_tail": stderr[-1000:] if stderr else "",
    }


register_tool(
    ToolSpec(
        name="run_tests",
        description=(
            "Run pytest tests and return structured results. Supports coverage "
            "(requires pytest-cov), marker filtering, fail-fast, and verbose output. "
            "Returns passed/failed/skipped counts, failed test details, and timing."
        ),
        schema={
            "type": "object",
            "properties": {
                "test_path": {"type": "string", "description": "Test file or directory (empty = auto)", "default": ""},
                "marker": {"type": "string", "description": "Pytest marker filter (e.g. 'slow', 'unit')"},
                "coverage": {"type": "boolean", "description": "Include coverage (requires pytest-cov)", "default": False},
                "verbose": {"type": "boolean", "description": "Verbose output (-v)", "default": False},
                "fail_fast": {"type": "boolean", "description": "Stop on first failure (-x)", "default": False},
                "project_path": {"type": "string", "description": "Working directory for pytest"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (1-1800)", "default": 600},
            },
        },
        handler=run_tests,
    )
)
