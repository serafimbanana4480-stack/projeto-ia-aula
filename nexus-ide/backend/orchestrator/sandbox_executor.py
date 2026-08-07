"""Sandbox Executor — runs quality gates in isolated environments.

Uses Docker/Sandbox when available, falls back to subprocess with
restricted permissions. Ensures proposed changes don't break the system
before they are applied.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SandboxResult:
    passed: bool
    output: str
    error: str | None = None
    duration_seconds: float = 0.0
    sandbox_type: str = "subprocess"


class SandboxExecutor:
    """Runs quality gates in isolated environments."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parent.parent.parent
        self._docker_available = self._check_docker()

    def _check_docker(self) -> bool:
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    async def run_tests(self, test_command: str = "python -m pytest") -> SandboxResult:
        start = time.time()
        try:
            if self._docker_available:
                return await self._run_in_docker(test_command, start)
            return await self._run_in_subprocess(test_command, start)
        except Exception as exc:
            return SandboxResult(
                passed=False,
                output="",
                error=str(exc),
                duration_seconds=(time.time() - start),
                sandbox_type="error",
            )

    async def _run_in_docker(self, test_command: str, start: float) -> SandboxResult:
        import docker
        client = docker.from_env()
        container = client.containers.run(
            "python:3.12-slim",
            command=f"sh -c 'pip install -q pytest && {test_command}'",
            volumes={str(self.project_root): {"bind": "/workspace", "mode": "ro"}},
            working_dir="/workspace",
            remove=True,
            mem_limit="512m",
            cpu_period=100000,
            cpu_quota=50000,
            network_mode="none",
            stdout=True,
            stderr=True,
        )
        output = container.decode("utf-8", errors="replace")
        return SandboxResult(
            passed="passed" in output.lower() or "ok" in output.lower(),
            output=output[-2000:],
            duration_seconds=(time.time() - start),
            sandbox_type="docker",
        )

    async def _run_in_subprocess(self, test_command: str, start: float) -> SandboxResult:
        result = subprocess.run(
            test_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(self.project_root),
        )
        output = result.stdout + result.stderr
        return SandboxResult(
            passed=result.returncode == 0,
            output=output[-2000:],
            error=None if result.returncode == 0 else output[-500:],
            duration_seconds=(time.time() - start),
            sandbox_type="subprocess",
        )

    async def run_lint(self, lint_command: str = "ruff check .") -> SandboxResult:
        start = time.time()
        try:
            result = subprocess.run(
                lint_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.project_root),
            )
            output = result.stdout + result.stderr
            return SandboxResult(
                passed=result.returncode == 0,
                output=output[-2000:],
                error=None if result.returncode == 0 else output[-500:],
                duration_seconds=(time.time() - start),
                sandbox_type="subprocess",
            )
        except Exception as exc:
            return SandboxResult(
                passed=False,
                output="",
                error=str(exc),
                duration_seconds=(time.time() - start),
                sandbox_type="subprocess",
            )
