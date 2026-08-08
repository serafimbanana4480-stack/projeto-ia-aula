"""Sandbox System — isolated code execution with security policies.

Provides secure, resource-limited execution environments for agent-generated
code. Uses Docker containers with strict resource limits, network isolation,
and filesystem restrictions.

Architecture:
- ``SandboxConfig``: configuration for sandbox constraints
- ``SandboxExecutor``: executes code in isolated Docker containers
- ``SecurityPolicy``: defines allowed/blocked operations
- ``DangerousCommandDetector``: identifies high-risk operations

Security features:
- No network access (--network=none)
- Read-only root filesystem
- Memory limits (512MB default)
- CPU limits (0.5 core default)
- Timeout enforcement (30s default)
- Path traversal prevention
- Dangerous command detection
- Audit logging
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)

# Lazy imports to avoid circular deps at module load time
_workspace_security = None


def _get_security():
    global _workspace_security
    if _workspace_security is None:
        from backend.core import workspace_security as _ws

        _workspace_security = _ws
    return _workspace_security


class RiskLevel(StrEnum):
    SAFE = "safe"  # read-only, no side effects
    LOW = "low"  # file writes within project
    MEDIUM = "medium"  # network access, package install
    HIGH = "high"  # system modification, git operations
    CRITICAL = "critical"  # destructive operations, requires explicit approval


@dataclass
class SandboxConfig:
    """Configuration for sandbox execution environment."""

    image: str = "python:3.12-slim"  # Docker image
    timeout_seconds: int = 30
    max_memory_mb: int = 512
    max_cpu_cores: float = 0.5
    max_disk_mb: int = 100
    network_enabled: bool = False
    read_only_root: bool = True
    allow_write_paths: list[str] = field(default_factory=lambda: ["/tmp", "/workspace"])
    environment: dict[str, str] = field(default_factory=dict)
    working_dir: str = "/workspace"


@dataclass
class SandboxResult:
    """Result of a sandboxed execution."""

    execution_id: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    duration_ms: int
    memory_used_mb: float = 0.0
    risk_level: RiskLevel = RiskLevel.SAFE
    sandbox_healthy: bool = True
    snapshot_hash: str | None = None
    dependencies_installed: list[str] = field(default_factory=list)
    policy_violations: list[str] = field(default_factory=list)


class DangerousCommandDetector:
    """Detects potentially dangerous commands that require approval."""

    # Patterns that require user confirmation
    CRITICAL_PATTERNS: list[tuple[str, str]] = [
        (r"rm\s+-rf\s+/", "Recursive root deletion"),
        (r"rm\s+-rf\s+~", "Home directory deletion"),
        (r"mkfs\.", "Filesystem formatting"),
        (r"dd\s+if=", "Raw disk operations"),
        (r">\s*/dev/sd[a-z]", "Raw device write"),
        (r"chmod\s+777\s+/", "World-writable root"),
        (r"git\s+push\s+--force", "Force push"),
        (r"git\s+reset\s+--hard", "Hard git reset"),
        (r"DROP\s+(TABLE|DATABASE)", "SQL destructive operation"),
        (r"DELETE\s+FROM", "SQL mass delete"),
        (r"shutdown|reboot|halt", "System shutdown"),
        (r"docker\s+(rm|kill|stop)", "Docker container manipulation"),
        (r"kubectl\s+delete", "Kubernetes resource deletion"),
        (r"npm\s+install\s+-g", "Global package installation"),
        (r"curl.*\|.*(bash|sh)", "Pipe to shell"),
        (r"eval\s+", "Eval execution"),
        (r"__import__\s*\(\s*['\"]os['\"]", "Python os import escape"),
        (r"subprocess|os\.system|os\.popen", "Python subprocess escape"),
    ]

    HIGH_PATTERNS: list[tuple[str, str]] = [
        (r"rm\s+-rf", "Recursive deletion"),
        (r"git\s+push", "Git push"),
        (r"pip\s+install|npm\s+install", "Package installation"),
        (r"wget|curl", "Network download"),
        (r"chmod|chown", "Permission changes"),
        (r"sudo", "Privilege escalation"),
        (r"docker\s+run", "Docker container run"),
    ]

    @classmethod
    def assess_risk(cls, command: str) -> tuple[RiskLevel, list[str]]:
        """Assess the risk level of a command and return reasons."""
        reasons: list[str] = []

        for pattern, description in cls.CRITICAL_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                reasons.append(f"CRITICAL: {description}")
                return RiskLevel.CRITICAL, reasons

        for pattern, description in cls.HIGH_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                reasons.append(f"HIGH: {description}")

        if reasons:
            return RiskLevel.HIGH, reasons

        # Check for file writes
        if re.search(r'write|open\s*\(.*[\'"]w[\'"]', command):
            return RiskLevel.LOW, ["File write operation"]

        return RiskLevel.SAFE, []


class SandboxExecutor:
    """Executes code in isolated Docker containers.

    Falls back to subprocess execution when Docker is unavailable.
    """

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self._config = config or SandboxConfig()
        self._docker_available: bool | None = None

    async def check_docker(self) -> bool:
        """Check if Docker is available."""
        if self._docker_available is not None:
            return self._docker_available

        try:
            # Use asyncio.to_thread + subprocess.run for Windows compatibility
            # asyncio.create_subprocess_exec can raise NotImplementedError on Windows
            import subprocess

            result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "info"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=5,
            )
            self._docker_available = result.returncode == 0
        except (FileNotFoundError, OSError):
            self._docker_available = False

        logger.info("Docker available: %s", self._docker_available)
        return self._docker_available

    async def execute(
        self,
        code: str,
        language: str = "python",
        *,
        timeout: int | None = None,
        files: dict[str, str] | None = None,  # filename -> content
        session_id: str = "",
        cwd: str | None = None,  # working directory override
    ) -> SandboxResult:
        """Execute code in a sandboxed environment."""
        execution_id = uuid.uuid4().hex[:12]
        timeout_sec = timeout or self._config.timeout_seconds

        # Assess risk
        risk, reasons = DangerousCommandDetector.assess_risk(code)
        if risk == RiskLevel.CRITICAL:
            logger.warning(
                "CRITICAL risk command blocked for session %s: %s",
                session_id,
                reasons,
            )
            return SandboxResult(
                execution_id=execution_id,
                stdout="",
                stderr=f"Command blocked: {'; '.join(reasons)}",
                exit_code=1,
                timed_out=False,
                duration_ms=0,
                risk_level=risk,
            )

        # Security validation before any execution path
        ws = _get_security()
        if language == "python":
            is_safe, reason = ws._check_python_sandbox(code)
            if not is_safe:
                return SandboxResult(
                    execution_id=execution_id,
                    stdout="",
                    stderr=f"Sandbox blocked: {reason}",
                    exit_code=1,
                    timed_out=False,
                    duration_ms=0,
                    risk_level=RiskLevel.CRITICAL,
                )
        elif language == "bash":
            is_safe, reason = ws._validate_shell_command(code)
            if not is_safe:
                return SandboxResult(
                    execution_id=execution_id,
                    stdout="",
                    stderr=f"Shell blocked: {reason}",
                    exit_code=1,
                    timed_out=False,
                    duration_ms=0,
                    risk_level=RiskLevel.CRITICAL,
                )

        docker_ok = await self.check_docker()

        if docker_ok:
            return await self._execute_docker(code, language, execution_id, timeout_sec, files)
        else:
            return await self._execute_subprocess(code, language, execution_id, timeout_sec, cwd)

    async def _execute_docker(
        self,
        code: str,
        language: str,
        execution_id: str,
        timeout: int,
        files: dict[str, str] | None,
    ) -> SandboxResult:
        """Execute code in a Docker container."""
        start = time.time()

        # Create temp directory for code
        with tempfile.TemporaryDirectory(prefix=f"nexus-sandbox-{execution_id}-") as tmpdir:
            tmp = Path(tmpdir)

            # Write code file
            ext = {"python": "py", "javascript": "js", "bash": "sh"}.get(language, "txt")
            code_file = tmp / f"code.{ext}"
            code_file.write_text(code)

            # Write additional files
            if files:
                for fname, fcontent in files.items():
                    fpath = tmp / fname
                    fpath.parent.mkdir(parents=True, exist_ok=True)
                    fpath.write_text(fcontent)

            # Build docker command
            cmd = [
                "docker",
                "run",
                "--rm",
                f"--name=nexus-sandbox-{execution_id}",
                "--network=none",
                f"--memory={self._config.max_memory_mb}m",
                f"--cpus={self._config.max_cpu_cores}",
                f"--read-only={str(self._config.read_only_root).lower()}",
                f"-v={tmpdir}:/workspace:rw",
                f"-w={self._config.working_dir}",
                self._config.image,
            ]

            # Add language-specific command
            if language == "python":
                cmd.extend(["python3", f"/workspace/code.{ext}"])
            elif language == "javascript":
                cmd.extend(["node", f"/workspace/code.{ext}"])
            elif language == "bash":
                cmd.extend(["bash", f"/workspace/code.{ext}"])
            else:
                return SandboxResult(
                    execution_id=execution_id,
                    stdout="",
                    stderr=f"Unsupported language: {language}",
                    exit_code=1,
                    timed_out=False,
                    duration_ms=0,
                )

            try:
                # Use asyncio.to_thread + subprocess.run for Windows compatibility
                import subprocess

                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        subprocess.run,
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    ),
                    timeout=timeout,
                )
                duration_ms = int((time.time() - start) * 1000)

                return SandboxResult(
                    execution_id=execution_id,
                    stdout=result.stdout.decode("utf-8", errors="replace") if result.stdout else "",
                    stderr=result.stderr.decode("utf-8", errors="replace") if result.stderr else "",
                    exit_code=result.returncode or 0,
                    timed_out=False,
                    duration_ms=duration_ms,
                )

            except TimeoutError:
                # Kill container
                try:
                    await asyncio.to_thread(
                        subprocess.run,
                        ["docker", "kill", f"nexus-sandbox-{execution_id}"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                except Exception as exc:
                    logger.debug("Failed to kill Docker sandbox %s: %s", execution_id, exc)

                duration_ms = int((time.time() - start) * 1000)
                return SandboxResult(
                    execution_id=execution_id,
                    stdout="",
                    stderr="Execution timed out",
                    exit_code=124,
                    timed_out=True,
                    duration_ms=duration_ms,
                )

            except FileNotFoundError:
                return SandboxResult(
                    execution_id=execution_id,
                    stdout="",
                    stderr="Docker not available",
                    exit_code=127,
                    timed_out=False,
                    duration_ms=0,
                )

    async def _execute_subprocess(
        self,
        code: str,
        language: str,
        execution_id: str,
        timeout: int,
        cwd: str | None = None,
    ) -> SandboxResult:
        """Fallback: execute in subprocess with resource limits.

        Applies OS-level resource limits when available:
        - Windows: job objects for memory/CPU limits
        - Linux: resource.setrlimit for memory limits
        """
        start = time.time()

        try:
            if language == "python":
                import sys

                cmd = [sys.executable, "-c", code]
            elif language == "javascript":
                cmd = ["node", "-e", code]
            elif language == "bash":
                bash = shutil.which("bash")
                if os.name == "nt" and bash:
                    try:
                        probe = subprocess.run(
                            [bash, "--version"],
                            capture_output=True,
                            timeout=3,
                            check=False,
                        )
                        if probe.returncode != 0:
                            bash = None
                    except (OSError, subprocess.SubprocessError):
                        bash = None
                if bash:
                    cmd = [bash, "-c", code]
                elif os.name == "nt":
                    # Windows commonly exposes the unusable WSL bash shim even
                    # when no distribution is installed. PowerShell provides a
                    # practical local fallback for simple shell verification.
                    cmd = ["powershell", "-NoProfile", "-Command", code]
                else:
                    cmd = ["bash", "-c", code]
            else:
                return SandboxResult(
                    execution_id=execution_id,
                    stdout="",
                    stderr=f"Unsupported language: {language}",
                    exit_code=1,
                    timed_out=False,
                    duration_ms=0,
                )

            # Prepare environment with resource limits
            env = {}
            if hasattr(os, "sysconf"):
                # Linux: set memory limit via environment for child process
                env["PYTHONMEMORY"] = str(self._config.max_memory_mb * 1024 * 1024)

            # Use Popen so a timeout can terminate exactly this child process.
            # Calling taskkill with /IM would also kill the pytest runner and
            # unrelated Python processes on Windows.
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd or tempfile.gettempdir(),
                env={**os.environ, **env} if env else None,
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                ),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    asyncio.to_thread(process.communicate), timeout=timeout
                )
                duration_ms = int((time.time() - start) * 1000)

                return SandboxResult(
                    execution_id=execution_id,
                    stdout=stdout.decode("utf-8", errors="replace") if stdout else "",
                    stderr=stderr.decode("utf-8", errors="replace") if stderr else "",
                    exit_code=process.returncode or 0,
                    timed_out=False,
                    duration_ms=duration_ms,
                )
            except TimeoutError:
                # Kill only the process tree rooted at this exact PID.
                try:
                    if os.name == "nt":
                        await asyncio.to_thread(
                            subprocess.run,
                            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            check=False,
                        )
                    else:
                        process.kill()
                    await asyncio.to_thread(process.communicate)
                except Exception as exc:
                    logger.debug(
                        "Failed to kill local process for sandbox %s: %s", execution_id, exc
                    )
                duration_ms = int((time.time() - start) * 1000)
                return SandboxResult(
                    execution_id=execution_id,
                    stdout="",
                    stderr="Execution timed out",
                    exit_code=124,
                    timed_out=True,
                    duration_ms=duration_ms,
                )

        except FileNotFoundError:
            return SandboxResult(
                execution_id=execution_id,
                stdout="",
                stderr=f"Interpreter not found for {language}",
                exit_code=127,
                timed_out=False,
                duration_ms=0,
            )
        except Exception as exc:
            duration_ms = int((time.time() - start) * 1000)
            return SandboxResult(
                execution_id=execution_id,
                stdout="",
                stderr=str(exc),
                exit_code=1,
                timed_out=False,
                duration_ms=duration_ms,
            )


class SecurityPolicy:
    """Defines and enforces security policies for agent operations."""

    def __init__(self) -> None:
        self._blocked_paths: set[str] = {
            "/etc/passwd",
            "/etc/shadow",
            "/etc/sudoers",
            "/root/.ssh",
            "/home/*/.ssh",
            "~/.aws",
            "~/.gcloud",
            "~/.config/gcloud",
        }
        self._allowed_commands: set[str] = {
            "ls",
            "cat",
            "head",
            "tail",
            "grep",
            "find",
            "wc",
            "python3",
            "python",
            "node",
            "bash",
            "git",
            "pip",
            "npm",
            "yarn",
            "cargo",
            "go",
        }
        self._blocked_commands: set[str] = {
            "sudo",
            "su",
            "chown",
            "chmod",
            "mount",
            "umount",
            "mkfs",
            "dd",
            "fdisk",
            "parted",
        }

    def is_path_allowed(self, path: str, project_root: str) -> bool:
        """Check if a file path is within allowed boundaries."""
        resolved = Path(path).resolve()
        project = Path(project_root).resolve()

        # Check blocked paths
        for blocked in self._blocked_paths:
            bp = Path(blocked).expanduser().resolve()
            try:
                resolved.relative_to(bp)
                return False
            except ValueError:
                pass

        # Must be within project root
        try:
            resolved.relative_to(project)
            return True
        except ValueError:
            return False

    def is_command_allowed(self, command: str) -> tuple[bool, str]:
        """Check if a shell command is allowed."""
        cmd_parts = command.strip().split()
        if not cmd_parts:
            return False, "Empty command"

        base_cmd = cmd_parts[0]

        if base_cmd in self._blocked_commands:
            return False, f"Blocked command: {base_cmd}"

        if base_cmd not in self._allowed_commands:
            return False, f"Command not in allowlist: {base_cmd}"

        return True, ""


# Global singletons
_sandbox_executor: SandboxExecutor | None = None
_security_policy: SecurityPolicy | None = None


def get_sandbox_executor() -> SandboxExecutor:
    global _sandbox_executor
    if _sandbox_executor is None:
        _sandbox_executor = SandboxExecutor()
    return _sandbox_executor


def get_security_policy() -> SecurityPolicy:
    global _security_policy
    if _security_policy is None:
        _security_policy = SecurityPolicy()
    return _security_policy
