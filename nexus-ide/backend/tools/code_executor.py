"""Code executor - sandbox for running Python, JS, Bash, etc.

Uses subprocess with timeout and resource limits. For production, use Docker.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

SANDBOX_CONFIG: dict[str, Any] = {
    "network_mode": "none",
    "mem_limit": "512m",
    "read_only": True,
    "user": "nobody",
    "security_opt": ["no-new-privileges"],
    "cap_drop": ["ALL"],
    "tmpfs": ["/tmp"],
}

LANGUAGE_CONFIG: dict[str, dict[str, str]] = {
    "python": {
        "command": "python3",
        "args": ["-u"],  # unbuffered output
        "extension": ".py",
    },
    "javascript": {
        "command": "node",
        "args": [],
        "extension": ".js",
    },
    "bash": {
        "command": "bash",
        "args": [],
        "extension": ".sh",
    },
}


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    execution_time: float
    timed_out: bool


async def execute_code(
    code: str, language: str = "python", timeout: int = 30
) -> ExecutionResult:
    """Run code in subprocess with timeout.

    WARNING: This is NOT a true sandbox. Code runs with the same user
    permissions as the server process. For production use, switch to
    Docker-based execution with the SANDBOX_CONFIG settings.

    Args:
        code: Source code to execute.
        language: One of 'python', 'javascript', 'bash'.
        timeout: Maximum execution time in seconds.

    Returns:
        ExecutionResult with stdout, stderr, exit code, timing info.

    Raises:
        ValueError: If the language is not supported.
    """
    if language not in LANGUAGE_CONFIG:
        raise ValueError(
            f"Unsupported language: {language}. "
            f"Supported: {', '.join(LANGUAGE_CONFIG.keys())}"
        )

    config = LANGUAGE_CONFIG[language]
    started_at = asyncio.get_event_loop().time()

    try:
        with tempfile.TemporaryDirectory(prefix="nexus_exec_") as tmpdir:
            source_path = Path(tmpdir) / f"code{config['extension']}"
            source_path.write_text(code, encoding="utf-8")

            cmd = [config["command"], *config["args"], str(source_path)]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmpdir,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                timed_out = False
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                stdout_bytes = b""
                stderr_bytes = b"Execution timed out"
                timed_out = True

            elapsed = asyncio.get_event_loop().time() - started_at

            return ExecutionResult(
                stdout=stdout_bytes.decode("utf-8", errors="replace")[:100_000],
                stderr=stderr_bytes.decode("utf-8", errors="replace")[:100_000],
                exit_code=proc.returncode if proc.returncode is not None else -1,
                execution_time=round(elapsed, 3),
                timed_out=timed_out,
            )

    except Exception as exc:
        elapsed = asyncio.get_event_loop().time() - started_at
        logger.exception("Code execution failed: %s", exc)
        return ExecutionResult(
            stdout="",
            stderr=f"Execution error: {exc}",
            exit_code=-1,
            execution_time=round(elapsed, 3),
            timed_out=False,
        )


register_tool(
    ToolSpec(
        name="execute_code",
        description="Execute code in a sandboxed environment (Python, JavaScript, Bash). WARNING: Not fully sandboxed - runs with server permissions.",
        schema={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Code to execute"},
                "language": {
                    "type": "string",
                    "enum": ["python", "javascript", "bash"],
                    "default": "python",
                },
                "timeout": {"type": "integer", "default": 30, "description": "Timeout in seconds"},
            },
            "required": ["code"],
        },
        handler=execute_code,
    )
)
