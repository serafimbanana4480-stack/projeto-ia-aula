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
import signal
import subprocess
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
    proc: asyncio.subprocess.Process | None = None
    communication: asyncio.Task[tuple[bytes, bytes]] | None = None
    try:
        process_options: dict[str, Any] = {}
        if os.name == "nt":
            process_options["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        else:
            process_options["start_new_session"] = True

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            **process_options,
        )
        communication = asyncio.create_task(proc.communicate())
        stdout_b, stderr_b = await asyncio.wait_for(
            asyncio.shield(communication), timeout=timeout
        )
        return (
            proc.returncode if proc.returncode is not None else -1,
            (stdout_b or b"").decode(errors="replace"),
            (stderr_b or b"").decode(errors="replace"),
        )
    except TimeoutError:
        if proc is None or communication is None:
            return (-1, "", f"Timeout after {timeout}s")
        await _terminate_process_tree(proc)
        stdout_b, stderr_b = await _finish_communication(communication)
        return (
            -1,
            (stdout_b or b"").decode(errors="replace"),
            f"Timeout after {timeout}s\n{(stderr_b or b'').decode(errors='replace')}".rstrip(),
        )
    except asyncio.CancelledError:
        if proc is not None:
            try:
                await _terminate_process_tree(proc)
            except Exception:  # noqa: BLE001 - preserve cancellation after best-effort cleanup
                logger.exception("Failed to terminate cancelled pytest process tree")
        if communication is not None:
            await _finish_communication(communication)
        raise
    except FileNotFoundError:
        return (-1, "", f"interpreter not found: {python_bin}")


async def _terminate_process_tree(proc: asyncio.subprocess.Process) -> None:
    """Stop pytest and every child it spawned, then reap the direct process."""
    if proc.returncode is not None:
        return

    if os.name == "nt":
        terminator: asyncio.subprocess.Process | None = None
        try:
            terminator = await asyncio.create_subprocess_exec(
                "taskkill.exe",
                "/PID",
                str(proc.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            await asyncio.wait_for(terminator.wait(), timeout=5.0)
        except (OSError, TimeoutError):
            if terminator is not None and terminator.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    terminator.kill()
    else:
        kill_process_group = getattr(os, "killpg", None)
        kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
        if callable(kill_process_group):
            with contextlib.suppress(ProcessLookupError):
                kill_process_group(proc.pid, kill_signal)

    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=1.0)


async def _finish_communication(
    communication: asyncio.Task[tuple[bytes, bytes]],
) -> tuple[bytes, bytes]:
    """Drain subprocess pipes after termination without allowing a hang."""
    try:
        return await asyncio.wait_for(asyncio.shield(communication), timeout=5.0)
    except TimeoutError:
        communication.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await communication
        return b"", b""


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


async def _run_pytest_with_results(
    args: list[str],
    *,
    cwd: str | None,
    timeout: int,
    interpreter: str,
    coverage: bool,
) -> tuple[int, str, str, dict[str, Any]]:
    """Keep each run's reports private and remove only its own temporary files."""
    with tempfile.TemporaryDirectory(prefix="nexus-pytest-") as output_dir:
        junit_path = str(Path(output_dir) / "junit.xml")
        command_args = [*args, f"--junit-xml={junit_path}"]
        if coverage:
            coverage_path = Path(output_dir) / "coverage.xml"
            command_args.append(f"--cov-report=xml:{coverage_path}")

        returncode, stdout, stderr = await _run_pytest(
            command_args, cwd=cwd, timeout=timeout, interpreter=interpreter
        )
        fallback: dict[str, Any] = {
            "tests": [],
            "failures": [],
            "errors": [],
            "skipped": [],
            "total": 0,
        }
        junit_data = _parse_junit_xml(junit_path) if os.path.exists(junit_path) else fallback
        return returncode, stdout, stderr, junit_data


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
) -> dict[str, Any]:
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
        args.extend(["--cov", ".", "--cov-report=term"])
    if marker:
        args.extend(["-m", marker])

    # Add test path
    if test_path:
        args.append(test_path)

    # Each invocation owns its temporary JUnit and coverage reports. Concurrent
    # chat sessions must not overwrite or delete one another's test evidence.
    interpreter = resolve_python_interpreter(project_path)
    returncode, stdout, stderr, junit_data = await _run_pytest_with_results(
        args,
        cwd=project_path,
        timeout=timeout,
        interpreter=interpreter,
        coverage=coverage,
    )

    # Parse results
    summary = _parse_summary_line(stdout)
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
