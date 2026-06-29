"""Code quality tools — linting, formatting, type checking.

Provides tools to run ruff (lint/format) and mypy (type check) on a project.
Returns structured output suitable for agent decision-making.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from typing import Any

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


def _tool_available(name: str) -> bool:
    """Check if a CLI tool is on PATH."""
    return shutil.which(name) is not None


async def _run(cmd: list[str], cwd: str | None = None, timeout: int = 120) -> tuple[int, str, str]:
    """Run a subprocess and return (returncode, stdout, stderr)."""
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
    except FileNotFoundError as e:
        return (-1, "", f"Command not found: {e}")


# ---------------------------------------------------------------------------
# Ruff lint
# ---------------------------------------------------------------------------
async def run_lint(
    path: str = ".",
    fix: bool = False,
    select: str | None = None,
    ignore: str | None = None,
    project_path: str | None = None,
    timeout: int = 120,
) -> dict:
    """Run ruff linter on a path.

    Args:
        path: Path to lint (file or directory). Default = current dir.
        fix: If True, apply auto-fixes (--fix).
        select: Optional rule codes to enable (e.g. 'E,F,W').
        ignore: Optional rule codes to ignore (e.g. 'E501').
        project_path: Working directory.
        timeout: Timeout in seconds (1-600).
    """
    if not _tool_available("ruff") and not _has_ruff_module():
        return {"error": "ruff not installed (pip install ruff)"}

    timeout = min(max(timeout, 1), 600)
    cmd = ["ruff", "check", path, "--output-format=json"]
    if fix:
        cmd.append("--fix")
    if select:
        cmd.extend(["--select", select])
    if ignore:
        cmd.extend(["--ignore", ignore])

    returncode, stdout, stderr = await _run(cmd, cwd=project_path, timeout=timeout)

    # Parse JSON output
    issues: list[dict[str, Any]] = []
    if stdout.strip():
        try:
            issues = json.loads(stdout)
        except json.JSONDecodeError:
            # Not JSON, return raw
            return {
                "status": "passed" if returncode == 0 else "issues",
                "tool": "ruff",
                "returncode": returncode,
                "output": stdout,
                "stderr": stderr,
                "issue_count": 0,
            }

    # Count by code
    by_code: dict[str, int] = {}
    for issue in issues:
        code = issue.get("code", "UNKNOWN")
        by_code[code] = by_code.get(code, 0) + 1

    return {
        "status": "passed" if returncode == 0 else "issues",
        "tool": "ruff",
        "fix_applied": fix,
        "issue_count": len(issues),
        "by_code": by_code,
        "issues": issues[:100],  # cap
        "stderr": stderr,
    }


# ---------------------------------------------------------------------------
# Ruff format
# ---------------------------------------------------------------------------
async def format_code(
    path: str = ".",
    check: bool = False,
    project_path: str | None = None,
    timeout: int = 120,
) -> dict:
    """Run ruff formatter on a path.

    Args:
        path: Path to format (file or directory). Default = current dir.
        check: If True, only check if files are formatted (no changes).
        project_path: Working directory.
        timeout: Timeout in seconds (1-600).
    """
    if not _tool_available("ruff") and not _has_ruff_module():
        return {"error": "ruff not installed (pip install ruff)"}

    timeout = min(max(timeout, 1), 600)
    cmd = ["ruff", "format", path]
    if check:
        cmd.append("--check")

    returncode, stdout, stderr = await _run(cmd, cwd=project_path, timeout=timeout)

    return {
        "status": (
            "formatted"
            if returncode == 0 and not check
            else ("needs_formatting" if returncode == 1 and check else "unchanged")
        ),
        "tool": "ruff format",
        "check_only": check,
        "returncode": returncode,
        "output": stdout,
        "stderr": stderr,
    }


# ---------------------------------------------------------------------------
# MyPy
# ---------------------------------------------------------------------------
async def type_check(
    path: str = ".",
    strict: bool = False,
    ignore_missing_imports: bool = True,
    project_path: str | None = None,
    timeout: int = 300,
) -> dict:
    """Run mypy type checker on a path (best-effort, requires mypy installed).

    Args:
        path: Path to type check.
        strict: If True, use --strict mode.
        ignore_missing_imports: If True, suppress missing import errors.
        project_path: Working directory.
        timeout: Timeout in seconds (1-1800).
    """
    if not _tool_available("mypy") and not _has_mypy_module():
        return {"error": "mypy not installed (pip install mypy)"}

    timeout = min(max(timeout, 1), 1800)
    cmd = ["mypy", path, "--output-format=json", "--no-error-summary"]
    if strict:
        cmd.append("--strict")
    if ignore_missing_imports:
        cmd.append("--ignore-missing-imports")

    returncode, stdout, stderr = await _run(cmd, cwd=project_path, timeout=timeout)

    # Parse JSON output
    errors: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            err = json.loads(line)
            if isinstance(err, dict):
                errors.append(
                    {
                        "file": err.get("file", ""),
                        "line": err.get("line", 0),
                        "column": err.get("column", 0),
                        "severity": err.get("severity", "error"),
                        "message": err.get("message", "")[:300],
                        "code": err.get("code", None),
                    }
                )
        except json.JSONDecodeError:
            continue

    return {
        "status": "passed" if returncode == 0 else "issues",
        "tool": "mypy",
        "strict": strict,
        "error_count": len(errors),
        "errors": errors[:100],  # cap
        "stderr": stderr[:500] if stderr else "",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _has_ruff_module() -> bool:
    try:
        import ruff  # type: ignore # noqa: F401

        return True
    except ImportError:
        return False


def _has_mypy_module() -> bool:
    try:
        import mypy  # type: ignore # noqa: F401

        return True
    except ImportError:
        return False


register_tool(
    ToolSpec(
        name="run_lint",
        description=(
            "Run ruff linter on a file or directory. Supports auto-fix, "
            "rule selection (--select), and rule ignoring (--ignore). "
            "Returns issues grouped by code."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to lint", "default": "."},
                "fix": {"type": "boolean", "description": "Apply auto-fixes", "default": False},
                "select": {"type": "string", "description": "Rule codes to enable (e.g. 'E,F,W')"},
                "ignore": {"type": "string", "description": "Rule codes to ignore"},
                "project_path": {"type": "string", "description": "Working directory"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 120},
            },
        },
        handler=run_lint,
    )
)

register_tool(
    ToolSpec(
        name="format_code",
        description=(
            "Run ruff formatter on a file or directory. Use check=true to "
            "verify formatting without changes."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to format", "default": "."},
                "check": {"type": "boolean", "description": "Check only, don't modify", "default": False},
                "project_path": {"type": "string", "description": "Working directory"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 120},
            },
        },
        handler=format_code,
    )
)

register_tool(
    ToolSpec(
        name="type_check",
        description=(
            "Run mypy type checker on a file or directory (best-effort, "
            "requires mypy installed). Supports --strict mode."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to type check", "default": "."},
                "strict": {"type": "boolean", "description": "Use --strict mode", "default": False},
                "ignore_missing_imports": {"type": "boolean", "description": "Ignore missing imports", "default": True},
                "project_path": {"type": "string", "description": "Working directory"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 300},
            },
        },
        handler=type_check,
    )
)
