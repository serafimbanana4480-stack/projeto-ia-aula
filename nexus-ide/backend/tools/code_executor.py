"""Code executor - sandbox for running Python, JS, Bash, etc.

Uses SandboxExecutor which provides:
- Docker container isolation when Docker is available
- Dangerous command detection and blocking
- Resource limits (memory, CPU, timeout)
- Automatic fallback to subprocess when Docker is unavailable
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

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


# Global SandboxExecutor instance (lazy-initialized)
_executor = None


def _get_executor():
    """Get or create the global SandboxExecutor instance."""
    global _executor
    if _executor is None:
        from backend.sandbox.executor import SandboxExecutor

        _executor = SandboxExecutor()
    return _executor


async def execute_code(code: str, language: str = "python", timeout: int = 30) -> dict[str, Any]:
    """Run code in a sandboxed environment.

    Uses SandboxExecutor which provides Docker isolation when available,
    dangerous command detection, and resource limits. Falls back to
    subprocess with security checks when Docker is unavailable.

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
            f"Unsupported language: {language}. Supported: {', '.join(LANGUAGE_CONFIG.keys())}"
        )

    try:
        executor = _get_executor()
        result = await executor.execute(
            code=code,
            language=language,
            timeout=timeout,
        )

        return {
            "stdout": result.stdout[:100_000],
            "stderr": result.stderr[:100_000],
            "exit_code": result.exit_code,
            "execution_time": result.duration_ms / 1000.0,
            "timed_out": result.timed_out,
        }

    except Exception as exc:
        logger.exception("Code execution failed: %s", exc)
        return {
            "stdout": "",
            "stderr": f"Execution error: {exc}",
            "exit_code": -1,
            "execution_time": 0.0,
            "timed_out": False,
        }


register_tool(
    ToolSpec(
        name="execute_code",
        description=(
            "Execute code in a sandboxed environment (Python, JavaScript, Bash). "
            "Uses Docker isolation when available, with dangerous command detection. "
            "CRITICAL risk commands (rm -rf /, etc.) are automatically blocked."
        ),
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
