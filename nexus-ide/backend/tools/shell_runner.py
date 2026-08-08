"""Shell runner tool — execute safe shell commands via WorkspaceManager.

Delegates all validation and execution to :class:`backend.core.workspace.WorkspaceManager`,
which provides an expanded command whitelist and comprehensive audit logging.
"""

from __future__ import annotations

import os
import time
from typing import Any

from backend.tools.registry import ToolSpec, register_tool


def _typed_process_result(result: dict[str, Any], command: str, started: float) -> dict[str, Any]:
    """Attach stable process evidence without changing workspace semantics."""
    payload = dict(result or {})
    timed_out = bool(payload.get("timed_out", False))
    exit_code = payload.get("exit_code")
    if exit_code is None:
        exit_code = 124 if timed_out else (1 if payload.get("error") else 0)
    duration_ms = int(payload.get("duration_ms", (time.monotonic() - started) * 1000))
    payload.update(
        {
            "command": payload.get("command") or command,
            "exit_code": int(exit_code),
            "duration_ms": duration_ms,
            "timed_out": timed_out,
            "evidence": {
                "kind": "process",
                "verified": not timed_out and int(exit_code) == 0,
                "command": payload.get("command") or command,
                "exit_code": int(exit_code),
                "duration_ms": duration_ms,
                "timed_out": timed_out,
                "stdout": str(payload.get("stdout") or "")[-4000:],
                "stderr": str(payload.get("stderr") or "")[-4000:],
            },
        }
    )
    return payload


async def run_shell(
    command: str,
    project_path: str = ".",
    timeout: int = 30,
) -> dict:
    """Run shell commands in the project directory.

    Args:
        command: Shell command to execute.
        project_path: Project root path (commands run inside this directory).
        timeout: Maximum execution time in seconds.

    Returns:
        Dict with stdout, stderr, return code, and command info.
    """
    manager = WorkspaceManager(project_path)
    effective_timeout = max(
        1,
        min(int(timeout), int(float(os.environ.get("NEXUS_SUBPROCESS_TIMEOUT", "300")))),
    )
    started = time.monotonic()
    result = await manager.execute_shell(
        command, cwd=project_path, timeout=effective_timeout, env={}
    )
    return _typed_process_result(result, command, started)


async def run_python_script(
    code: str,
    project_path: str = ".",
    timeout: int = 30,
) -> dict:
    """Run a Python script string in the project directory."""
    from backend.core.workspace import WorkspaceManager

    manager = WorkspaceManager(project_path)
    effective_timeout = max(
        1,
        min(int(timeout), int(float(os.environ.get("NEXUS_SUBPROCESS_TIMEOUT", "300")))),
    )
    started = time.monotonic()
    result = await manager.execute_python(code, cwd=project_path, timeout=effective_timeout)
    return _typed_process_result(result, "python -c <script>", started)


register_tool(
    ToolSpec(
        name="run_shell",
        description=(
            "Run shell commands in the project directory. "
            "Allowed commands include: python, pip, npm, node, git, cargo, go, make, "
            "gcc, clang, find, grep, awk, sed, tar, rsync, and many more. "
            "Dangerous commands (rm -rf /, dd, mkfs, format, shutdown, etc.) are blocked."
        ),
        schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
                "timeout": {
                    "type": "integer",
                    "default": 30,
                    "description": "Timeout in seconds",
                },
            },
            "required": ["command"],
        },
        handler=run_shell,
    )
)

register_tool(
    ToolSpec(
        name="run_python_script",
        description="Run a Python script string in the project directory",
        schema={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"},
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
                "timeout": {
                    "type": "integer",
                    "default": 30,
                    "description": "Timeout in seconds",
                },
            },
            "required": ["code"],
        },
        handler=run_python_script,
    )
)
