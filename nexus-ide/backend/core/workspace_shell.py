"""Shell and Python execution for the workspace.

Wraps ``asyncio.create_subprocess_*`` with validation, timeout handling,
and environment sanitisation.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import platform
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from backend.core.workspace_security import (
    _check_python_sandbox,
    _is_blocked_path,
    _log_operation,
    _split_on_separators,
    _validate_shell_command,
    _verify_auth_token,
    argv_for_validated_shell_command,
    logger,
)
from backend.tools.interpreters import resolve_python_interpreter, scrubbed_environment
from backend.tools.output_stream import current_output_channel

_SHELL_INHERITED_ENV = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "SYSTEMDRIVE",
        "HOMEDRIVE",
        "HOMEPATH",
        "HOME",
        "USERPROFILE",
        "TEMP",
        "TMP",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "CONDA_DEFAULT_ENV",
        "PYTHONUTF8",
        "PYTHONIOENCODING",
    }
)

# Safe, explicit additions for command-specific behavior; arbitrary environment
# names (including provider and credential keys) never cross the process boundary.
_SHELL_TOOL_ENV = frozenset(
    {"CI", "FORCE_COLOR", "NO_COLOR", "PIP_DISABLE_PIP_VERSION_CHECK"}
)

_SCRIPT_OUTPUT_LIMIT_BYTES = 1024 * 1024
_SCRIPT_OUTPUT_CHUNK_BYTES = 64 * 1024
_SCRIPT_KILL_WAIT_SECONDS = 2


def _shell_child_environment(overrides: dict[str, str] | None) -> dict[str, str]:
    """Build a minimal child environment without inheriting process secrets."""
    allowed = _SHELL_INHERITED_ENV | _SHELL_TOOL_ENV
    env_by_name = {key.casefold(): (key, value) for key, value in os.environ.items()}
    result = {
        key: value
        for folded, (key, value) in env_by_name.items()
        if folded.upper() in allowed
    }
    for key, value in (overrides or {}).items():
        if key.upper() in _SHELL_TOOL_ENV and isinstance(value, str):
            result[key] = value
    return result


def _argv_for_shell_segment(segment: str) -> list[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        parts = segment.strip().split()
        if not parts:
            raise ValueError("empty shell segment") from None
        return parts


def _drain_bounded_script_output(
    stream: Any,
    captured: bytearray,
    truncated: threading.Event,
    writer: Any = None,
) -> None:
    """Drain one child pipe while retaining at most the configured output cap."""
    if stream is None:
        return
    try:
        descriptor = stream.fileno()
        while True:
            chunk = os.read(descriptor, _SCRIPT_OUTPUT_CHUNK_BYTES)
            if not chunk:
                break
            if writer is not None:
                writer.feed(chunk)
            remaining = _SCRIPT_OUTPUT_LIMIT_BYTES - len(captured)
            if remaining > 0:
                captured.extend(chunk[:remaining])
            if len(chunk) > max(remaining, 0):
                truncated.set()
    except (OSError, ValueError):
        return
    finally:
        if writer is not None:
            writer.finish()


def _kill_script_process_tree(process: subprocess.Popen[bytes]) -> bool:
    """Terminate a script and descendants created in its process group."""
    if os.name == "nt":
        try:
            import psutil

            root = psutil.Process(process.pid)
            descendants = root.children(recursive=True)
            with contextlib.suppress(psutil.Error, OSError):
                root.kill()
            for descendant in reversed(descendants):
                with contextlib.suppress(psutil.Error, OSError):
                    descendant.kill()
            _gone, alive = psutil.wait_procs(
                [root, *descendants], timeout=_SCRIPT_KILL_WAIT_SECONDS
            )
            tree_termination_requested = not alive
        except Exception:
            tree_termination_requested = False
            try:
                result = subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    check=False,
                    timeout=5,
                    env=scrubbed_environment(),
                )
                tree_termination_requested = result.returncode == 0
            except (OSError, subprocess.SubprocessError):
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            tree_termination_requested = True
        except ProcessLookupError:
            tree_termination_requested = True
        except OSError:
            tree_termination_requested = False

    if process.poll() is None:
        with contextlib.suppress(OSError):
            process.kill()
    return tree_termination_requested


async def _terminate_script_process_and_wait(
    process: subprocess.Popen[bytes],
    wait_task: asyncio.Task[int],
) -> bool:
    """Request tree termination and wait a bounded time to reap the root."""
    tree_termination_requested = await asyncio.to_thread(
        _kill_script_process_tree, process
    )
    completed, _pending = await asyncio.wait(
        {wait_task}, timeout=_SCRIPT_KILL_WAIT_SECONDS
    )
    return tree_termination_requested and wait_task in completed


def _script_output_text(captured: bytearray, truncated: threading.Event) -> str:
    text = bytes(captured).decode("utf-8", errors="replace")
    if truncated.is_set():
        text += f"\n[output truncated after {_SCRIPT_OUTPUT_LIMIT_BYTES} bytes]"
    return text


async def _run_script_process(
    command: list[str],
    cwd: Path,
    timeout: float,
    *,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str, bool, bool]:
    """Run a script with bounded output and cleanup on timeout/cancellation."""
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=scrubbed_environment() if env is None else env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        start_new_session=os.name != "nt",
    )

    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    stdout_truncated = threading.Event()
    stderr_truncated = threading.Event()
    channel = current_output_channel()
    stdout_reader = threading.Thread(
        target=_drain_bounded_script_output,
        args=(process.stdout, stdout_buffer, stdout_truncated,
              channel.writer("stdout") if channel else None),
        daemon=True,
    )
    stderr_reader = threading.Thread(
        target=_drain_bounded_script_output,
        args=(process.stderr, stderr_buffer, stderr_truncated,
              channel.writer("stderr") if channel else None),
        daemon=True,
    )
    stdout_reader.start()
    stderr_reader.start()
    wait_task = asyncio.create_task(asyncio.to_thread(process.wait))
    timed_out = False
    termination_confirmed = True

    try:
        try:
            await asyncio.wait_for(asyncio.shield(wait_task), timeout=timeout)
        except TimeoutError:
            timed_out = True
            termination_confirmed = await _terminate_script_process_and_wait(
                process, wait_task
            )
            if not termination_confirmed:
                logger.error(
                    "Script process termination was not confirmed after timeout | pid=%s",
                    process.pid,
                )
    except asyncio.CancelledError:
        cleanup_task = asyncio.create_task(
            _terminate_script_process_and_wait(process, wait_task)
        )
        try:
            termination_confirmed = await asyncio.shield(cleanup_task)
        except BaseException:  # preserve cancellation after bounded cleanup
            termination_confirmed = False
        if not termination_confirmed:
            logger.error(
                "Script process termination was not confirmed after cancellation | pid=%s",
                process.pid,
            )
        raise
    finally:
        if process.poll() is None and not termination_confirmed:
            cleanup_task = asyncio.create_task(
                _terminate_script_process_and_wait(process, wait_task)
            )
            try:
                termination_confirmed = await asyncio.shield(cleanup_task)
            except BaseException:
                termination_confirmed = False
            if not termination_confirmed:
                logger.error(
                    "Script process is still running after cleanup retries | pid=%s",
                    process.pid,
                )

        await asyncio.to_thread(stdout_reader.join, 5)
        await asyncio.to_thread(stderr_reader.join, 5)
        if stdout_reader.is_alive() or stderr_reader.is_alive():
            await asyncio.to_thread(_kill_script_process_tree, process)
            await asyncio.to_thread(stdout_reader.join, 2)
            await asyncio.to_thread(stderr_reader.join, 2)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    return (
        process.returncode if process.returncode is not None else -1,
        _script_output_text(stdout_buffer, stdout_truncated),
        _script_output_text(stderr_buffer, stderr_truncated),
        timed_out,
        termination_confirmed,
    )


async def _run_validated_pipeline(
    command: str,
    cwd_path: Path | None,
    child_env: dict[str, str],
    timeout: int,
) -> dict[str, Any]:
    """Run a validated ``|`` pipeline with bounded output and child cleanup."""
    segments = _split_on_separators(command.strip())
    processes: list[subprocess.Popen[bytes]] = []
    output_readers: list[tuple[threading.Thread, bytearray, threading.Event]] = []
    wait_tasks: list[asyncio.Task[int]] = []
    termination_confirmed = True
    channel = current_output_channel()

    def start_reader(stream: Any, name: str) -> tuple[threading.Thread, bytearray, threading.Event]:
        captured = bytearray()
        truncated = threading.Event()
        reader = threading.Thread(
            target=_drain_bounded_script_output,
            args=(stream, captured, truncated, channel.writer(name) if channel else None),
            daemon=True,
        )
        reader.start()
        return reader, captured, truncated

    async def stop_processes() -> bool:
        if not processes:
            return True
        killed = await asyncio.gather(
            *(asyncio.to_thread(_kill_script_process_tree, process) for process in processes)
        )
        completed, _pending = await asyncio.wait(
            set(wait_tasks), timeout=_SCRIPT_KILL_WAIT_SECONDS
        )
        return all(killed) and len(completed) == len(wait_tasks)

    try:
        for segment in segments:
            argv = _argv_for_shell_segment(segment)
            stdin = processes[-1].stdout if processes else None
            process = subprocess.Popen(
                argv,
                cwd=str(cwd_path) if cwd_path else None,
                stdin=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=child_env,
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                ),
                start_new_session=os.name != "nt",
            )
            if processes and processes[-1].stdout is not None:
                processes[-1].stdout.close()
            processes.append(process)
            if process.stderr is not None:
                output_readers.append(start_reader(process.stderr, "stderr"))

        if processes[-1].stdout is not None:
            stdout_reader = start_reader(processes[-1].stdout, "stdout")
        else:  # pragma: no cover - stdout is always PIPE above
            stdout_reader = start_reader(None, "stdout")
        wait_tasks = [
            asyncio.create_task(asyncio.to_thread(process.wait))
            for process in processes
        ]
        wait_all = asyncio.gather(*wait_tasks)
        timed_out = False
        try:
            await asyncio.wait_for(asyncio.shield(wait_all), timeout=float(timeout))
        except TimeoutError:
            timed_out = True
            termination_confirmed = await stop_processes()
        except asyncio.CancelledError:
            cleanup_task = asyncio.create_task(stop_processes())
            with contextlib.suppress(BaseException):
                termination_confirmed = await asyncio.shield(cleanup_task)
            raise

        for reader, _captured, _truncated in [*output_readers, stdout_reader]:
            await asyncio.to_thread(reader.join, 5)
        if any(reader.is_alive() for reader, _captured, _truncated in [*output_readers, stdout_reader]):
            termination_confirmed = await stop_processes() and termination_confirmed
            for reader, _captured, _truncated in [*output_readers, stdout_reader]:
                await asyncio.to_thread(reader.join, 2)
        stdout = _script_output_text(stdout_reader[1], stdout_reader[2])
        stderr = "\n".join(
            text
            for _reader, captured, truncated in output_readers
            if (text := _script_output_text(captured, truncated))
        )
        returncode = processes[-1].returncode
        if timed_out:
            message = f"Command timed out after {timeout} seconds"
            if not termination_confirmed:
                message += "; process termination could not be confirmed"
            return {
                "error": message,
                "command": command,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": 124,
                "timed_out": True,
                "termination_confirmed": termination_confirmed,
            }
        return {
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": returncode,
            "cwd": str(cwd_path) if cwd_path else None,
        }
    except asyncio.CancelledError:
        if processes and any(process.poll() is None for process in processes):
            cleanup_task = asyncio.create_task(stop_processes())
            with contextlib.suppress(BaseException):
                await asyncio.shield(cleanup_task)
        raise
    except Exception:
        if processes and any(process.poll() is None for process in processes):
            await stop_processes()
        raise
    finally:
        for process in processes:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    with contextlib.suppress(OSError):
                        stream.close()


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

    child_env = _shell_child_environment(env)
    try:
        try:
            argv = argv_for_validated_shell_command(command)
        except ValueError:
            return await _run_validated_pipeline(command, cwd_path, child_env, timeout)
        returncode, stdout, stderr, timed_out, termination_confirmed = (
            await _run_script_process(
                argv,
                cwd_path or Path.cwd(),
                float(timeout),
                env=child_env,
            )
        )
        if timed_out:
            logger.warning("Shell command timed out: %s", command)
            message = f"Command timed out after {timeout} seconds"
            if not termination_confirmed:
                message += "; process termination could not be confirmed"
            return {
                "error": message,
                "command": command,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": 124,
                "timed_out": True,
                "termination_confirmed": termination_confirmed,
            }
        return {
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": returncode,
            "cwd": str(cwd_path) if cwd_path else None,
        }
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

        # The child must never inherit the server environment: it holds the
        # provider API keys and the signing secrets, and the code executed
        # here is model-supplied (``POST /api/workspace/execute_python``).
        # ``scrubbed_environment()`` is the same hardened helper the
        # model-facing tools use.
        try:
            returncode, stdout_text, stderr_text, timed_out, termination_confirmed = (
                await _run_script_process(
                    [sys.executable, temp_path],
                    cwd_path,
                    float(timeout),
                    env=scrubbed_environment(),
                )
            )
            if timed_out:
                error = f"Python script timed out after {timeout}s"
                if not termination_confirmed:
                    error += "; process termination could not be confirmed"
                return {
                    "error": error,
                    "returncode": -1,
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                    "timed_out": True,
                    "termination_confirmed": termination_confirmed,
                }
        finally:
            Path(temp_path).unlink(missing_ok=True)

        return {
            "returncode": returncode,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "success": returncode == 0,
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
        # Use a concrete interpreter path. On Windows, ``py.exe`` is a
        # launcher that creates a second process; killing it at the timeout
        # boundary can leave the script process alive long enough to perform
        # late writes. Prefer the project's virtualenv when one exists.
        interpreter = resolve_python_interpreter(str(cwd_path))
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
        returncode, stdout, stderr, timed_out, termination_confirmed = await _run_script_process(
            cmd,
            cwd_path,
            timeout=float(timeout),
        )
        command_text = " ".join(shlex.quote(c) for c in cmd)
        if timed_out:
            error = f"Script timed out after {timeout}s"
            if not termination_confirmed:
                error += "; process termination could not be confirmed"
            return {
                "error": error,
                "command": command_text,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": returncode,
                "timed_out": True,
                "termination_confirmed": termination_confirmed,
            }
        return {
            "command": command_text,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": returncode,
            "cwd": str(cwd_path),
        }
    except FileNotFoundError:
        return {"error": f"Interpreter not found: {interpreter}", "command": " ".join(cmd)}
    except Exception as exc:
        return {"error": f"Script execution failed: {exc}", "command": " ".join(cmd)}
