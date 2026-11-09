"""Interpreter resolution and hardened execution shared by every tool that
shells out to Python.

``["python", ...]`` (or ``python3``) means "whatever is first on PATH", which
is routinely NOT the interpreter running NEXUS and, on Windows with an
unactivated project venv, is often a bare system Python with none of the
project's dependencies. That mismatch produced "No module named pytest" and,
because the caller only checked the failure count, a green verification over
zero executed tests (audit 2026-08-16, P3/P9i).

Resolution order, most specific first:

1. ``NEXUS_PYTHON`` — an explicit operator override;
2. the project's own virtualenv (``venv``/``.venv``/``env``);
3. ``sys.executable`` — the interpreter already running the backend;
4. ``python3``/``python`` from PATH, preserving historical behaviour.

This module also owns the *hardened* execution of model-supplied Python:
the child process never inherits the server environment, because that
environment holds provider API keys and signing secrets which the model
would otherwise be able to read back through ``os.environ``.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

__all__ = ["resolve_python_interpreter", "run_python_code", "scrubbed_environment"]

_VENV_DIRS = ("venv", ".venv", "env", ".env")
_VENV_BINS = (("Scripts", "python.exe"), ("bin", "python"), ("bin", "python3"))


def resolve_python_interpreter(project_path: str | None = None) -> str:
    """Return the best Python interpreter for running code in ``project_path``."""
    override = (os.environ.get("NEXUS_PYTHON") or "").strip()
    if override:
        return override

    if project_path:
        root = Path(project_path)
        for venv_name in _VENV_DIRS:
            for parts in _VENV_BINS:
                candidate = root.joinpath(venv_name, *parts)
                try:
                    if candidate.is_file():
                        return str(candidate)
                except OSError:  # pragma: no cover - unreadable path
                    continue

    if sys.executable:
        return sys.executable

    return shutil.which("python3") or shutil.which("python") or "python"


def scrubbed_environment() -> dict[str, str]:
    """Return the environment a child interpreter may see.

    Only an explicit allow-list of harmless variables (plus the non-secret
    ``NEXUS_*`` settings) is passed on; every credential-shaped variable of
    the server process is dropped.
    """
    from backend.core.workspace_security import _python_child_environment

    return _python_child_environment()


async def run_python_code(
    code: str,
    cwd: str | os.PathLike[str] | None = None,
    timeout: float = 120,
    project_root: str | None = None,
    script_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Execute *code* in a child interpreter with a scrubbed environment.

    The code is checked against the Python sandbox before anything is
    written to disk, and the child process is started with an environment
    that contains no server credentials.

    Args:
        code: Source code to run.
        cwd: Working directory of the child process.
        timeout: Maximum runtime in seconds.
        project_root: Directory the code is allowed to write to.
        script_dir: Directory the temporary script is written to.  Defaults
            to *cwd*.

    Returns:
        Dict with ``stdout``, ``stderr``, ``returncode``, ``exit_code``,
        ``success`` and (on failure) ``error``.
    """
    from backend.core.workspace_security import _check_python_sandbox, _log_operation

    is_safe, reason = _check_python_sandbox(code, project_root=project_root)
    if not is_safe:
        result = {
            "error": f"Sandbox blocked: {reason}",
            "stdout": "",
            "stderr": reason,
            "returncode": -1,
            "exit_code": 1,
            "success": False,
        }
        _log_operation("execute_python", {"code": code[:500], "cwd": str(cwd)}, result)
        return result

    try:
        workdir = Path(cwd).expanduser().resolve() if cwd else Path.cwd().resolve()
    except (OSError, ValueError):
        workdir = Path.cwd()

    try:
        script_path = Path(script_dir).expanduser().resolve() if script_dir else workdir
    except (OSError, ValueError):
        script_path = workdir

    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", dir=str(script_path), delete=False
        ) as handle:
            handle.write(code)
            temp_path = handle.name

        import subprocess

        process = subprocess.Popen(
            [resolve_python_interpreter(str(workdir)), temp_path],
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=scrubbed_environment(),
            text=True,
            errors="replace",
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            ),
        )

        try:
            stdout_text, stderr_text = await asyncio.wait_for(
                asyncio.to_thread(process.communicate),
                timeout=float(timeout),
            )
        except TimeoutError:
            await _terminate_process(process)
            return {
                "error": f"Python script timed out after {timeout}s",
                "stdout": "",
                "stderr": "",
                "returncode": -1,
                "exit_code": 124,
                "timed_out": True,
                "success": False,
            }

        returncode = int(process.returncode or 0)
        return {
            "stdout": stdout_text or "",
            "stderr": stderr_text or "",
            "returncode": returncode,
            "exit_code": returncode,
            "success": returncode == 0,
        }
    except Exception as exc:  # pragma: no cover - defensive
        result = {
            "error": f"Python execution failed: {exc}",
            "stdout": "",
            "stderr": str(exc),
            "returncode": -1,
            "exit_code": 1,
            "success": False,
        }
        _log_operation("execute_python", {"code": code[:500], "cwd": str(cwd)}, result)
        return result
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


async def _terminate_process(process: Any) -> None:
    """Kill *process* (and its children on Windows) after a timeout."""
    try:
        if os.name == "nt":
            import subprocess

            await asyncio.to_thread(
                subprocess.run,
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
        else:
            process.kill()
        await asyncio.to_thread(process.communicate)
    except Exception:  # pragma: no cover - best effort cleanup
        pass
