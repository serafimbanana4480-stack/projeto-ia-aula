"""Test runner tool — execute pytest and return structured results.

Provides a single ``run_tests`` tool that wraps pytest invocation, parses
JUnit XML output (or stdout), and returns structured results including
passed/failed counts, coverage, and failed test details.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from backend.tools.interpreters import resolve_python_interpreter
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


#: Substrings proving pytest never started. A run that never started has no
#: results — reporting "0 passed, 0 failed" as success is the failure mode this
#: guards against.
_PYTEST_MISSING_MARKERS: tuple[str, ...] = (
    "no module named pytest",
    "not installed",
    "command not found",
    "cannot find the path",
    "is not recognized",
)


async def _run_pytest(
    args: list[str],
    cwd: str | None = None,
    timeout: int = 600,
    interpreter: str | None = None,
) -> tuple[int, str, str]:
    """Run pytest as subprocess and return (returncode, stdout, stderr)."""
    python_bin = interpreter or resolve_python_interpreter(cwd)
    cmd = [python_bin, "-m", "pytest", *args]
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
        return (-1, "", f"interpreter not found: {python_bin}")


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

    # JUnit XML for structured results. A hardcoded POSIX /tmp path is wrong
    # on Windows, where it resolves to the current drive root and frequently
    # is not writable — the parser then silently fell back to counting zero.
    junit_path = str(Path(tempfile.gettempdir()) / "nexus-junit.xml")
    with contextlib.suppress(OSError):
        Path(junit_path).unlink()  # never reuse a previous run's results
    args.extend([f"--junit-xml={junit_path}"])

    # Add test path
    if test_path:
        args.append(test_path)

    # Run
    interpreter = resolve_python_interpreter(project_path)
    returncode, stdout, stderr = await _run_pytest(
        args, cwd=project_path, timeout=timeout, interpreter=interpreter
    )

    # Parse results
    summary = _parse_summary_line(stdout)
    junit_data = _parse_junit_xml(junit_path) if os.path.exists(junit_path) else {"tests": [], "failures": [], "errors": [], "skipped": [], "total": 0}
    cov_pct = _parse_coverage_output(stdout) if coverage else None

    duration_match = re.search(r"in\s+([\d.]+)s", stdout)
    duration_s = float(duration_match.group(1)) if duration_match else None

    executed = (
        junit_data["total"] > 0
        or summary["passed"] > 0
        or summary["failed"] > 0
        or summary["errors"] > 0
        or summary["skipped"] > 0
    )
    combined_output = f"{stdout}\n{stderr}".lower()
    runner_missing = any(marker in combined_output for marker in _PYTEST_MISSING_MARKERS)
    # returncode 4 = pytest usage error, 5 = no tests collected. Neither is a
    # pass, and neither may be reported as one.
    could_not_run = runner_missing or returncode in (4, 5) or (
        not executed and returncode != 0
    )

    # "This project has no tests" is a different fact from "the test runner is
    # broken". Treating the first as a failure sent the primary loop into a
    # recovery cycle — a second full inference — for read-only questions about
    # projects that simply have no suite.
    if returncode == 5 and not runner_missing:
        return {
            "status": "no_tests",
            "ran": True,
            "executed": False,
            "ok": True,
            "no_tests_found": True,
            "interpreter": interpreter,
            "returncode": returncode,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "total": 0,
            "duration_s": duration_s,
            "error": (
                "Nenhum teste foi recolhido neste alvo: o projeto pode não ter "
                "testes. Nada foi verificado — não afirmes que os testes passaram."
            ),
            "stdout_tail": stdout[-2000:] if stdout else "",
            "stderr_tail": stderr[-1000:] if stderr else "",
        }

    if could_not_run:
        reason = (
            f"pytest não arrancou com o interpretador '{interpreter}'"
            if runner_missing
            else (
                "pytest não recolheu nenhum teste"
                if returncode == 5
                else f"pytest terminou com returncode {returncode} sem executar testes"
            )
        )
        return {
            "status": "not_run",
            "ran": False,
            "executed": False,
            "ok": False,
            "error": (
                f"{reason}. Nenhum teste foi executado, por isso NÃO existe "
                "verificação verde: não afirmes que os testes passaram."
            ),
            "interpreter": interpreter,
            "returncode": returncode,
            "passed": 0,
            "failed": 0,
            "errors": summary["errors"],
            "skipped": 0,
            "total": 0,
            "duration_s": duration_s,
            "stdout_tail": stdout[-2000:] if stdout else "",
            "stderr_tail": stderr[-1000:] if stderr else "",
        }

    return {
        "status": "passed" if returncode == 0 else ("failed" if returncode in (1, 2) else "error"),
        "ran": True,
        "executed": executed,
        "ok": returncode == 0 and summary["failed"] == 0 and summary["errors"] == 0,
        "interpreter": interpreter,
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
