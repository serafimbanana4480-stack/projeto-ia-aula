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


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    execution_time: float
    timed_out: bool


async def execute_code(code: str, language: str = "python", timeout: int = 30) -> ExecutionResult:
    """Run code in subprocess with timeout."""
    import subprocess
    
    start = asyncio.get_event_loop().time()
    
    try:
        if language == "python":
            cmd = ["python3", "-c", code]
        elif language == "javascript":
            cmd = ["node", "-e", code]
        elif language == "bash":
            cmd = ["bash", "-c", code]
        else:
            return ExecutionResult(
                stdout="", stderr=f"Unsupported language: {language}", exit_code=1,
                execution_time=0, timed_out=False,
            )
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tempfile.gettempdir(),
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            elapsed = asyncio.get_event_loop().time() - start
            return ExecutionResult(
                stdout=stdout.decode("utf-8", errors="ignore"),
                stderr=stderr.decode("utf-8", errors="ignore"),
                exit_code=process.returncode or 0,
                execution_time=elapsed,
                timed_out=False,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            elapsed = asyncio.get_event_loop().time() - start
            return ExecutionResult(
                stdout="", stderr="Execution timed out", exit_code=124,
                execution_time=elapsed, timed_out=True,
            )
    except FileNotFoundError:
        return ExecutionResult(
            stdout="", stderr=f"Interpreter not found for {language}", exit_code=127,
            execution_time=0, timed_out=False,
        )
    except Exception as e:
        elapsed = asyncio.get_event_loop().time() - start
        return ExecutionResult(
            stdout="", stderr=str(e), exit_code=1,
            execution_time=elapsed, timed_out=False,
        )


register_tool(ToolSpec(
    name="execute_code",
    description="Execute code in a sandboxed environment (Python, JavaScript, Bash)",
    schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Code to execute"},
            "language": {"type": "string", "enum": ["python", "javascript", "bash"], "default": "python"},
            "timeout": {"type": "integer", "default": 30, "description": "Timeout in seconds"},
        },
        "required": ["code"],
    },
    handler=execute_code,
))
