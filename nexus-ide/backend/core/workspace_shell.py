"""Shell and Python execution for the workspace.

Wraps ``asyncio.create_subprocess_*`` with validation, timeout handling,
and environment sanitisation.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shlex
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from backend.core.workspace_security import (
    _check_python_sandbox,
    _log_operation,
    _validate_shell_command,
    _verify_auth_token,
    logger,
)


def _windows_python_fixup(command: str) -> str:
    """Replace 'python' with 'py' on Windows to avoid MS Store alias error 9009.

    Only replaces when ``py`` is actually available on PATH; otherwise keeps
    ``python`` so the shell can fall back.
    """
    if platform.system() != "Windows":
        return command
    if not shutil.which("py"):
        return command
    stripped = command.lstrip()
    lower = stripped.lower()
    if lower.startswith("python "):
        return "py " + stripped[7:]
    if lower == "python":
        return "py"
    return command


async def execute_shell(
    command: str,
    cwd: str | None = None,
    timeout: int = 120,
    env: dict[str, str] | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Execute any shell command (with blacklist validation)."""
    logger.info("execute_shell: %s (cwd=%s)", command, cwd)

    if auth_token is not None:
        ok, reason = _verify_auth_token(auth_token)
        if not ok:
            return {"error": reason}

    command = _windows_python_fixup(command)

    is_safe, reason = _validate_shell_command(command)
    if not is_safe:
        result = {"error": f"Blocked: {reason}", "command": command}
        _log_operation("execute_shell", {"command": command, "cwd": cwd}, result)
        return result

    try:
        cwd_path = Path(cwd).expanduser().resolve() if cwd else None
    except Exception:
        cwd_path = None

    merged_env = {**os.environ, **(env or {})}

    # Sanitize sensitive environment variables to prevent credential leakage
    for key in list(merged_env.keys()):
        if key in ("JWT_SECRET", "SECRET_KEY") or key.endswith("_API_KEY"):
            merged_env.pop(key, None)

    try:
        # Prefer create_subprocess_exec (no shell interpreter) for simple
        # commands without pipes on POSIX systems.  Windows quoting rules are
        # different and shlex.split can leave literal quotes in arguments, so
        # we keep the shell there.  This eliminates quoting / injection issues
        # that only exist when a shell parses the command string.
        use_exec = (not sys.platform.startswith("win")) and ("|" not in command)
        if use_exec:
            try:
                args = shlex.split(command)
            except ValueError:
                args = [command]
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(cwd_path) if cwd_path else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(cwd_path) if cwd_path else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=float(timeout)
        )

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        return {
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": proc.returncode,
            "cwd": str(cwd_path) if cwd_path else None,
        }
    except asyncio.TimeoutError:
        logger.warning("Shell command timed out: %s", command)
        return {"error": f"Command timed out after {timeout} seconds", "command": command}
    except FileNotFoundError:
        return {"error": "Shell executable not found", "command": command}
    except Exception as exc:
        logger.exception("Shell command failed: %s", exc)
        result = {"error": f"Shell execution failed: {exc}", "command": command}
        _log_operation("execute_shell", {"command": command, "cwd": cwd}, result)
        return result


async def execute_python(
    code: str,
    cwd: str | None = None,
    timeout: int = 120,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Execute a Python code string in a temporary file (sandboxed)."""
    logger.info("execute_python: %d bytes (cwd=%s)", len(code), cwd)

    if auth_token is not None:
        ok, reason = _verify_auth_token(auth_token)
        if not ok:
            return {"error": reason}

    # Sandbox check — block dangerous imports before writing any file
    is_safe, reason = _check_python_sandbox(code)
    if not is_safe:
        logger.warning("Blocked execute_python: %s", reason)
        result = {"error": f"Sandbox blocked: {reason}", "code": code[:500]}
        _log_operation("execute_python", {"code": code[:500], "cwd": cwd}, result)
        return result

    try:
        cwd_path = Path(cwd).expanduser().resolve() if cwd else Path.cwd()
    except Exception:
        cwd_path = Path.cwd()

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", dir=str(cwd_path), delete=False
        ) as f:
            f.write(code)
            temp_path = f.name

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            temp_path,
            cwd=str(cwd_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"error": f"Python script timed out after {timeout}s", "returncode": -1}
        finally:
            Path(temp_path).unlink(missing_ok=True)

        stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""

        return {
            "returncode": proc.returncode,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "success": proc.returncode == 0,
        }
    except Exception as exc:
        result = {"error": f"Python execution failed: {exc}"}
        _log_operation("execute_python", {"code": code[:500], "cwd": cwd}, result)
        return result


async def execute_script(
    path: str,
    args: list[str] | None = None,
    cwd: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Execute any script file (absolute path)."""
    logger.info("execute_script: %s args=%s (cwd=%s)", path, args, cwd)

    from backend.core.workspace_security import _is_blocked_path

    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": reason}

    try:
        script = await asyncio.to_thread(lambda: Path(path).expanduser().resolve())
        if not await asyncio.to_thread(script.exists):
            return {"error": f"Script not found: {path}"}

        cwd_path = await asyncio.to_thread(lambda: Path(cwd).expanduser().resolve()) if cwd else script.parent
    except Exception as exc:
        return {"error": f"Path resolution failed: {exc}"}

    interpreter: str | None = None
    ext = script.suffix.lower()
    if ext == ".py":
        if platform.system() == "Windows" and shutil.which("py"):
            interpreter = "py"
        else:
            interpreter = "python"
    elif ext == ".sh":
        interpreter = "bash"
    elif ext in (".ps1", ".psm1"):
        interpreter = "powershell"
    elif ext == ".js":
        interpreter = "node"
    elif ext == ".rb":
        interpreter = "ruby"
    else:
        try:
            first_line = (await asyncio.to_thread(script.read_text, encoding="utf-8", errors="ignore")).splitlines()[0]
        except (PermissionError, FileNotFoundError, IndexError):
            first_line = ""
        if first_line.startswith("#!"):
            interpreter = first_line[2:].strip().split()[0]

    cmd = [interpreter, str(script)] if interpreter else [str(script)]
    cmd.extend(args or [])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=float(timeout))

        stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""

        return {
            "command": " ".join(shlex.quote(c) for c in cmd),
            "stdout": stdout_text,
            "stderr": stderr_text,
            "exit_code": proc.returncode,
            "cwd": str(cwd_path),
        }
    except asyncio.TimeoutError:
        return {"error": f"Script timed out after {timeout}s", "command": " ".join(cmd)}
    except FileNotFoundError:
        return {"error": f"Interpreter not found: {interpreter}", "command": " ".join(cmd)}
    except Exception as exc:
        return {"error": f"Script execution failed: {exc}", "command": " ".join(cmd)}
