"""Shell and Python execution for the workspace.

Wraps ``asyncio.create_subprocess_*`` with validation, timeout handling,
and environment sanitisation.
"""

from __future__ import annotations

import asyncio
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
    _is_blocked_path,
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

    # Validate cwd against blocked paths
    if cwd_path:
        blocked, reason = _is_blocked_path(str(cwd_path))
        if blocked:
            return {"error": f"Blocked working directory: {reason}", "command": command}

    merged_env = {**os.environ, **(env or {})}

    # Sanitize sensitive environment variables to prevent credential leakage
    for key in list(merged_env.keys()):
        if key in ("JWT_SECRET", "SECRET_KEY") or key.endswith("_API_KEY"):
            merged_env.pop(key, None)

    try:
        # Use asyncio.to_thread + subprocess.run for Windows compatibility.
        # asyncio.create_subprocess_exec raises NotImplementedError on Windows
        # with the default event loop policy.
        import subprocess

        def _run_shell():
            return subprocess.run(
                command,
                cwd=str(cwd_path) if cwd_path else None,
                capture_output=True,
                env=merged_env,
                shell=True,
                text=True,
                errors="replace",
            )

        result = await asyncio.wait_for(
            asyncio.to_thread(_run_shell),
            timeout=float(timeout),
        )

        return {
            "command": command,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "exit_code": result.returncode,
            "cwd": str(cwd_path) if cwd_path else None,
        }
    except TimeoutError:
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

        def _run_python():
            import subprocess

            return subprocess.run(
                [sys.executable, temp_path],
                cwd=str(cwd_path),
                capture_output=True,
                text=True,
                errors="replace",
            )

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_run_python),
                timeout=timeout,
            )
        except TimeoutError:
            # Attempt to kill the Python process on timeout
            try:
                import subprocess

                subprocess.run(
                    ["taskkill", "/F", "/T", "/IM", Path(sys.executable).name],
                    capture_output=True,
                    check=False,
                )
            except Exception:
                logger.debug("Failed to kill timed-out Python process", exc_info=True)
            return {"error": f"Python script timed out after {timeout}s", "returncode": -1}
        finally:
            Path(temp_path).unlink(missing_ok=True)

        stdout_text = result.stdout or ""
        stderr_text = result.stderr or ""

        return {
            "returncode": result.returncode,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "success": result.returncode == 0,
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
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Execute any script file (absolute path)."""
    logger.info("execute_script: %s args=%s (cwd=%s)", path, args, cwd)

    if auth_token is not None:
        ok, reason = _verify_auth_token(auth_token)
        if not ok:
            return {"error": reason}

    from backend.core.workspace_security import _is_blocked_path

    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": reason}

    try:
        script = await asyncio.to_thread(lambda: Path(path).expanduser().resolve())
        if not await asyncio.to_thread(script.exists):
            return {"error": f"Script not found: {path}"}

        cwd_path = (
            await asyncio.to_thread(lambda: Path(cwd).expanduser().resolve())
            if cwd
            else script.parent
        )
    except Exception as exc:
        return {"error": f"Path resolution failed: {exc}"}

    interpreter: str | None = None
    ext = script.suffix.lower()
    if ext == ".py":
        interpreter = "py" if platform.system() == "Windows" and shutil.which("py") else "python"
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
            first_line = (
                await asyncio.to_thread(script.read_text, encoding="utf-8", errors="ignore")
            ).splitlines()[0]
        except (PermissionError, FileNotFoundError, IndexError):
            first_line = ""
        if first_line.startswith("#!"):
            interpreter = first_line[2:].strip().split()[0]

    cmd = [interpreter, str(script)] if interpreter else [str(script)]
    cmd.extend(args or [])

    # For Python scripts, apply sandbox check before execution
    if ext == ".py":
        try:
            script_content = script.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            return {"error": f"Failed to read script: {exc}", "command": " ".join(cmd)}
        is_safe, reason = _check_python_sandbox(script_content)
        if not is_safe:
            return {"error": f"Sandbox blocked: {reason}", "command": " ".join(cmd)}

    try:

        def _run_script():
            import subprocess

            return subprocess.run(
                cmd,
                cwd=str(cwd_path),
                capture_output=True,
                text=True,
                errors="replace",
            )

        result = await asyncio.wait_for(
            asyncio.to_thread(_run_script),
            timeout=float(timeout),
        )

        return {
            "command": " ".join(shlex.quote(c) for c in cmd),
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "exit_code": result.returncode,
            "cwd": str(cwd_path),
        }
    except TimeoutError:
        return {"error": f"Script timed out after {timeout}s", "command": " ".join(cmd)}
    except FileNotFoundError:
        return {"error": f"Interpreter not found: {interpreter}", "command": " ".join(cmd)}
    except Exception as exc:
        return {"error": f"Script execution failed: {exc}", "command": " ".join(cmd)}
