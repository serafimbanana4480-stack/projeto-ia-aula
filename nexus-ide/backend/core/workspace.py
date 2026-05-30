"""Workspace Manager — full filesystem and terminal access for NEXUS agents.

Replaces sandboxed file_ops / shell_runner with absolute-path operations.
Dangerous commands and system paths are blocked via blacklist; user home and
project directories are always allowed. All operations are logged and writes
are backed up to ``.nexus/backups/``.

Exposes both a :class:`WorkspaceManager` (used by legacy ``file_ops.py`` and
``shell_runner.py``) and free functions (registered as new absolute-path tools).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.persistence.db import propose_change

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Security configuration
# ---------------------------------------------------------------------------

_BLOCKED_COMMAND_PATTERNS = {
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "rm -rf ~/*",
    "dd ",
    "mkfs",
    "mkfs.",
    "fdisk",
    "format",
    "> /dev/sda",
    "> /dev/sdb",
    "> /dev/sdc",
    "/dev/sda",
    "/dev/sdb",
    "/dev/sdc",
    ":(){ :|:& };:",  # fork bomb
    "shutdown",
    "reboot",
    "poweroff",
    "halt",
    "del /f /s /q",
    "rd /s /q",
    "rd /s \\",
    "format c:",
    "format d:",
    "diskpart",
    "convert /fs:ntfs",
}

_BLOCKED_SYSTEM_PATHS = {
    "/etc",
    "/sys",
    "/proc",
    "/dev",
    "/boot",
    "/usr/sbin",
    "/sbin",
    "/bin",
    "/lib",
    "/lib64",
    "C:\\Windows\\System32",
    "C:\\Windows\\SysWOW64",
    "C:\\Windows\\System",
    "C:\\ProgramData\\Microsoft\\Windows",
}

_ALLOWED_OVERRIDES = {"home", "users", "projeto", "nexus", "desktop", "documents"}


def _is_blocked_path(path: str) -> tuple[bool, str]:
    """Check whether *path* resolves to a blocked system directory.

    User home and obvious project directories are always permitted.
    """
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, ValueError) as exc:
        return True, f"Invalid path: {exc}"

    home = Path.home().resolve()
    try:
        resolved.relative_to(home)
        return False, ""
    except ValueError:
        pass

    lower_parts = [p.lower() for p in resolved.parts]
    if any(part in lower_parts for part in _ALLOWED_OVERRIDES):
        return False, ""

    for blocked in _BLOCKED_SYSTEM_PATHS:
        bpath = Path(blocked).resolve() if ":" not in blocked else Path(blocked)
        try:
            resolved.relative_to(bpath)
            return True, f"Access to system path '{blocked}' is blocked"
        except ValueError:
            continue

    return False, ""


_SHELL_WHITELIST: set[str] = {
    # Original whitelist
    "python",
    "python3",
    "pip",
    "pip3",
    "npm",
    "node",
    "git",
    "mkdir",
    "cp",
    "mv",
    "rm",
    "cat",
    "echo",
    "pytest",
    "curl",
    "wget",
    # Expanded whitelist
    "cargo",
    "rustc",
    "go",
    "javac",
    "mvn",
    "gradle",
    "docker",
    "docker-compose",
    "make",
    "cmake",
    "gcc",
    "g++",
    "clang",
    "code",
    "vim",
    "nano",
    "htop",
    "ps",
    "kill",
    "find",
    "grep",
    "awk",
    "sed",
    "tar",
    "zip",
    "unzip",
    "ssh",
    "scp",
    "rsync",
    "nc",
    "telnet",
    "ping",
    "traceroute",
    "netstat",
    "ss",
    "lsof",
    "df",
    "du",
    "free",
    "uptime",
    "uname",
    "whoami",
    "id",
    "env",
    "export",
    "source",
    "chmod",
    "chown",
    "ln",
    "touch",
    "head",
    "tail",
    "less",
    "more",
    "wc",
    "sort",
    "uniq",
    "diff",
    "patch",
    "jq",
    "yq",
    "xargs",
    "parallel",
}

_GIT_BLOCKED_SUBCOMMANDS: set[str] = {"push", "reset", "clean", "rebase", "cherry-pick"}
_GIT_BLOCKED_FLAGS: set[str] = {"--force", "--hard", "-f", "-D", "--delete"}


def _validate_shell_command(command: str) -> tuple[bool, str]:
    """Validate a shell command against blacklist and whitelist."""
    if not command or not command.strip():
        return False, "Empty command"

    cmd_lower = command.lower().strip()

    # Blocked dangerous patterns
    for pattern in _BLOCKED_COMMAND_PATTERNS:
        if pattern.lower() in cmd_lower:
            return False, f"Dangerous pattern '{pattern}' is blocked"

    # Blocked system paths in command string
    for blocked_path in _BLOCKED_SYSTEM_PATHS:
        if blocked_path.lower() in cmd_lower:
            return False, f"Access to system path '{blocked_path}' is blocked"

    # Parse base command
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.strip().split()

    if not tokens:
        return False, "Empty command"

    base_cmd = Path(tokens[0]).name.lower()

    # Special handling for git
    if base_cmd == "git":
        if len(tokens) >= 2:
            subcmd = tokens[1].lower()
            if subcmd in _GIT_BLOCKED_SUBCOMMANDS:
                return False, f"Git subcommand '{subcmd}' is blocked for safety"
            for flag in _GIT_BLOCKED_FLAGS:
                if flag in cmd_lower:
                    return False, f"Git flag '{flag}' is blocked for safety"
        return True, ""

    if base_cmd not in _SHELL_WHITELIST:
        return False, f"Command '{base_cmd}' is not in the safe command whitelist"

    return True, ""


def _validate_path(project_path: str, target_path: str) -> Path:
    """Validate that target_path is within project_path (sandbox).

    Kept for backward compatibility with directory_tools.py.
    """
    project = Path(project_path).resolve()
    target = (
        (project / target_path).resolve()
        if not Path(target_path).is_absolute()
        else Path(target_path).resolve()
    )
    try:
        target.relative_to(project)
    except ValueError:
        raise PermissionError(f"Path {target} is outside project root {project}") from None
    return target


# ---------------------------------------------------------------------------
# Backup helpers
# ---------------------------------------------------------------------------

def _backup_dir_for(path: Path) -> Path:
    """Return the backup directory for a given file path."""
    candidate = path.resolve()
    for parent in [candidate] + list(candidate.parents):
        if (parent / ".git").exists() or (parent / ".nexus").exists():
            return parent / ".nexus" / "backups"
    return Path.home() / ".nexus" / "backups"


def _create_backup(path: Path) -> dict[str, Any]:
    """Create a timestamped backup of *path* and return metadata."""
    if not path.exists():
        return {"backed_up": False, "reason": "file did not exist"}

    try:
        original = path.read_bytes()
    except Exception as exc:
        return {"backed_up": False, "reason": str(exc)}

    backup_dir = _backup_dir_for(path)
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    hash_suffix = hashlib.sha256(str(path).encode()).hexdigest()[:8]
    backup_name = f"{path.name}.{timestamp}.{hash_suffix}.bak"
    backup_path = backup_dir / backup_name

    try:
        backup_path.write_bytes(original)
        logger.info("Backup created: %s -> %s", path, backup_path)
        return {
            "backed_up": True,
            "backup_path": str(backup_path),
            "original_size": len(original),
        }
    except Exception as exc:
        logger.warning("Failed to create backup for %s: %s", path, exc)
        return {"backed_up": False, "reason": str(exc)}


# ---------------------------------------------------------------------------
# Filesystem access — free functions (absolute paths)
# ---------------------------------------------------------------------------

async def read_file_absolute(path: str) -> dict[str, Any]:
    """Read any file the user has permission to read (absolute path)."""
    logger.info("read_file_absolute: %s", path)

    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": reason}

    try:
        target = Path(path).expanduser().resolve()
        content = target.read_text(encoding="utf-8")
        return {"path": str(target), "content": content, "size": len(content)}
    except FileNotFoundError:
        return {"error": f"File not found: {path}"}
    except PermissionError:
        return {"error": f"Permission denied: {path}"}
    except Exception as exc:
        return {"error": f"Failed to read file: {exc}"}


async def write_file_absolute(path: str, content: str) -> dict[str, Any]:
    """Write any file (absolute path) with backup of the original."""
    logger.info("write_file_absolute: %s (%d bytes)", path, len(content))

    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": reason}

    try:
        target = Path(path).expanduser().resolve()
        backup_meta = _create_backup(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"path": str(target), "written": True, "size": len(content), "backup": backup_meta}
    except PermissionError:
        return {"error": f"Permission denied: {path}"}
    except Exception as exc:
        return {"error": f"Failed to write file: {exc}"}


async def list_dir_absolute(path: str, recursive: bool = False) -> dict[str, Any]:
    """List any directory (absolute path)."""
    logger.info("list_dir_absolute: %s (recursive=%s)", path, recursive)

    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": reason}

    try:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            return {"error": f"Path not found: {path}"}
        if not target.is_dir():
            return {"error": f"Path is not a directory: {path}"}

        if recursive:
            items = [
                {
                    "path": str(item),
                    "name": item.name,
                    "type": "file" if item.is_file() else "dir",
                    "size": item.stat().st_size if item.is_file() else 0,
                }
                for item in target.rglob("*")
            ]
        else:
            items = [
                {
                    "path": str(item),
                    "name": item.name,
                    "type": "file" if item.is_file() else "dir",
                    "size": item.stat().st_size if item.is_file() else 0,
                }
                for item in target.iterdir()
            ]

        return {"path": str(target), "items": items, "count": len(items)}
    except PermissionError:
        return {"error": f"Permission denied: {path}"}
    except Exception as exc:
        return {"error": f"Failed to list directory: {exc}"}


async def create_dir_absolute(path: str) -> dict[str, Any]:
    """Create directories recursively (absolute path)."""
    logger.info("create_dir_absolute: %s", path)

    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": reason}

    try:
        target = Path(path).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        return {"path": str(target), "created": True}
    except PermissionError:
        return {"error": f"Permission denied: {path}"}
    except Exception as exc:
        return {"error": f"Failed to create directory: {exc}"}


async def delete_file_absolute(path: str, move_to_trash: bool = True) -> dict[str, Any]:
    """Delete a file (absolute path) with optional trash/recovery."""
    logger.info("delete_file_absolute: %s (trash=%s)", path, move_to_trash)

    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": reason}

    try:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            return {"error": f"File not found: {path}"}
        if target.is_dir():
            return {"error": "Path is a directory; use recursive directory deletion instead"}

        if move_to_trash:
            trash_dir = _backup_dir_for(target) / "trash"
            trash_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            hash_suffix = hashlib.sha256(str(target).encode()).hexdigest()[:8]
            trash_name = f"{target.name}.{timestamp}.{hash_suffix}"
            trash_path = trash_dir / trash_name
            shutil.move(str(target), str(trash_path))
            logger.info("Moved to trash: %s -> %s", target, trash_path)
            return {"path": str(target), "deleted": True, "trash_path": str(trash_path)}

        target.unlink()
        logger.info("Deleted permanently: %s", target)
        return {"path": str(target), "deleted": True, "trash_path": None}
    except PermissionError:
        return {"error": f"Permission denied: {path}"}
    except Exception as exc:
        return {"error": f"Failed to delete file: {exc}"}


async def search_files_absolute(
    pattern: str, root_path: str, max_results: int = 100
) -> dict[str, Any]:
    """Grep-like search across files under *root_path*."""
    logger.info("search_files_absolute: pattern='%s' root='%s'", pattern, root_path)

    blocked, reason = _is_blocked_path(root_path)
    if blocked:
        return {"error": reason}

    try:
        root = Path(root_path).expanduser().resolve()
        if not root.exists():
            return {"error": f"Root path not found: {root_path}"}

        results = []
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            try:
                stat = file_path.stat()
                if stat.st_size > 5 * 1024 * 1024:
                    continue
            except Exception:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            if pattern.lower() in content.lower():
                lines = content.splitlines()
                matches = [
                    {"line": i + 1, "text": line}
                    for i, line in enumerate(lines)
                    if pattern.lower() in line.lower()
                ]
                results.append(
                    {
                        "path": str(file_path),
                        "matches": matches[:5],
                        "match_count": len(matches),
                    }
                )
                if len(results) >= max_results:
                    break

        return {"pattern": pattern, "root": str(root), "results": results, "count": len(results)}
    except PermissionError:
        return {"error": f"Permission denied: {root_path}"}
    except Exception as exc:
        return {"error": f"Search failed: {exc}"}


# ---------------------------------------------------------------------------
# Terminal access — free functions
# ---------------------------------------------------------------------------

async def execute_shell(
    command: str,
    cwd: str | None = None,
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute any shell command (with blacklist validation)."""
    logger.info("execute_shell: %s (cwd=%s)", command, cwd)

    is_safe, reason = _validate_shell_command(command)
    if not is_safe:
        return {"error": f"Blocked: {reason}", "command": command}

    try:
        cwd_path = Path(cwd).expanduser().resolve() if cwd else None
    except Exception:
        cwd_path = None

    merged_env = {**os.environ, **(env or {})}

    try:
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
        return {"error": f"Shell execution failed: {exc}", "command": command}


async def execute_python(
    code: str,
    cwd: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Execute a Python code string in a temporary file."""
    logger.info("execute_python: %d bytes (cwd=%s)", len(code), cwd)

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
        return {"error": f"Python execution failed: {exc}"}


async def execute_script(
    path: str,
    args: list[str] | None = None,
    cwd: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Execute any script file (absolute path)."""
    logger.info("execute_script: %s args=%s (cwd=%s)", path, args, cwd)

    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": reason}

    try:
        script = Path(path).expanduser().resolve()
        if not script.exists():
            return {"error": f"Script not found: {path}"}

        cwd_path = Path(cwd).expanduser().resolve() if cwd else script.parent
    except Exception as exc:
        return {"error": f"Path resolution failed: {exc}"}

    interpreter: str | None = None
    ext = script.suffix.lower()
    if ext == ".py":
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
        first_line = script.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
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


# ---------------------------------------------------------------------------
# Git integration
# ---------------------------------------------------------------------------

async def _git_raw(args: list[str], cwd: str, timeout: int = 60) -> dict[str, Any]:
    """Run a raw git command and return structured output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            return {"exit_code": proc.returncode, "error": err or out, "command": f"git {' '.join(args)}"}

        return {"output": out, "command": f"git {' '.join(args)}", "exit_code": 0}
    except asyncio.TimeoutError:
        return {"error": f"Git command timed out: git {' '.join(args)}"}
    except FileNotFoundError:
        return {"error": "Git is not installed or not in PATH"}
    except Exception as exc:
        return {"error": f"Git operation failed: {exc}"}


async def git_init(path: str) -> dict[str, Any]:
    """Initialise a git repository at *path*."""
    logger.info("git_init: %s", path)
    target = Path(path).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    return await _git_raw(["init"], str(target))


async def git_clone(url: str, path: str) -> dict[str, Any]:
    """Clone a git repository into *path*."""
    logger.info("git_clone: %s -> %s", url, path)
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    return await _git_raw(["clone", url, str(target)], str(target.parent), timeout=180)


async def git_commit_all(
    path: str, message: str = "auto: changes from NEXUS workspace"
) -> dict[str, Any]:
    """Stage all changes and commit in *path*."""
    logger.info("git_commit_all: %s message='%s'", path, message)
    target = str(Path(path).expanduser().resolve())

    safe_message = message.replace('"', '\\"').replace("`", "").replace("$", "")[:500]

    add_res = await _git_raw(["add", "-A"], target)
    if "error" in add_res and add_res.get("exit_code", 0) != 0:
        return {"error": f"git add failed: {add_res.get('error')}", "add": add_res}

    commit_res = await _git_raw(["commit", "-m", safe_message], target)
    return {"add": add_res, "commit": commit_res}


async def git_push(
    path: str, remote: str = "origin", branch: str | None = None
) -> dict[str, Any]:
    """Push commits from *path*. Allowed for workspace manager."""
    logger.info("git_push: %s remote=%s branch=%s", path, remote, branch)
    target = str(Path(path).expanduser().resolve())

    args = ["push", remote]
    if branch:
        args.append(branch)
    return await _git_raw(args, target, timeout=120)


async def git_status(path: str) -> dict[str, Any]:
    """Return git status for *path*."""
    logger.info("git_status: %s", path)
    target = str(Path(path).expanduser().resolve())
    return await _git_raw(["status", "-sb"], target)


# ---------------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------------

_LANGUAGE_INDICATORS: dict[str, list[str]] = {
    "python": ["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile"],
    "javascript": ["package.json", "package-lock.json", "yarn.lock"],
    "typescript": ["tsconfig.json", "package.json"],
    "rust": ["Cargo.toml", "Cargo.lock"],
    "go": ["go.mod", "go.sum"],
    "ruby": ["Gemfile", "Gemfile.lock"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "dotnet": [".csproj", ".sln"],
    "php": ["composer.json", "composer.lock"],
    "elixir": ["mix.exs", "mix.lock"],
    "haskell": ["stack.yaml", "cabal.project"],
    "c": ["CMakeLists.txt", "Makefile"],
    "cpp": ["CMakeLists.txt", "Makefile", "conanfile.txt"],
}

_FRAMEWORK_INDICATORS: dict[str, list[str]] = {
    "django": ["manage.py", "wsgi.py", "asgi.py"],
    "flask": ["app.py", "wsgi.py"],
    "fastapi": ["main.py", "app/main.py"],
    "react": ["src/App.jsx", "src/App.tsx", "public/index.html"],
    "vue": ["vue.config.js", "vite.config.ts"],
    "angular": ["angular.json", ".angular-cli.json"],
    "nextjs": ["next.config.js", "next.config.mjs"],
    "rails": ["config/routes.rb", "Rakefile"],
    "laravel": ["artisan", "webpack.mix.js"],
    "spring": ["src/main/java", "src/main/resources/application.properties"],
}


def _detect_language(project_path: Path) -> str:
    scores: dict[str, int] = {}
    for lang, indicators in _LANGUAGE_INDICATORS.items():
        for indicator in indicators:
            if (project_path / indicator).exists():
                scores[lang] = scores.get(lang, 0) + 1
    return max(scores, key=scores.get) if scores else "unknown"


def _detect_framework(project_path: Path, language: str) -> str | None:
    for framework, indicators in _FRAMEWORK_INDICATORS.items():
        for indicator in indicators:
            if (project_path / indicator).exists():
                return framework
    return None


def _get_dependencies(project_path: Path, language: str) -> list[str]:
    deps: list[str] = []
    if language == "python":
        req_file = project_path / "requirements.txt"
        if req_file.exists():
            for line in req_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    deps.append(line.split("=")[0].split("<")[0].split(">")[0].strip())
        elif (project_path / "pyproject.toml").exists():
            deps.append("pyproject.toml")
    elif language in ("javascript", "typescript"):
        pkg_file = project_path / "package.json"
        if pkg_file.exists():
            try:
                data = json.loads(pkg_file.read_text(encoding="utf-8"))
                deps.extend(data.get("dependencies", {}).keys())
                deps.extend(data.get("devDependencies", {}).keys())
            except Exception:
                pass
    elif language == "rust":
        if (project_path / "Cargo.toml").exists():
            deps.append("Cargo.toml")
    elif language == "go":
        if (project_path / "go.mod").exists():
            deps.append("go.mod")
    return deps[:50]


async def discover_projects(root_path: str) -> dict[str, Any]:
    """Find all git repos and common project structures under *root_path*."""
    logger.info("discover_projects: %s", root_path)

    blocked, reason = _is_blocked_path(root_path)
    if blocked:
        return {"error": reason}

    try:
        root = Path(root_path).expanduser().resolve()
        if not root.exists():
            return {"error": f"Root path not found: {root_path}"}

        projects: list[dict[str, Any]] = []
        seen: set[Path] = set()

        for candidate in root.rglob("*"):
            if not candidate.is_dir():
                continue
            if candidate in seen:
                continue

            is_git = (candidate / ".git").is_dir()
            is_project = any(
                (candidate / indicator).exists()
                for indicators in _LANGUAGE_INDICATORS.values()
                for indicator in indicators
            )

            if is_git or is_project:
                for parent in candidate.parents:
                    if parent == root or root in parent.parents:
                        seen.add(parent)

                projects.append(
                    {
                        "path": str(candidate),
                        "name": candidate.name,
                        "is_git_repo": is_git,
                        "detected_language": _detect_language(candidate),
                        "detected_framework": _detect_framework(
                            candidate, _detect_language(candidate)
                        ),
                    }
                )

        return {"root": str(root), "projects": projects, "count": len(projects)}
    except PermissionError:
        return {"error": f"Permission denied: {root_path}"}
    except Exception as exc:
        return {"error": f"Discovery failed: {exc}"}


async def get_project_info(path: str) -> dict[str, Any]:
    """Detect language, framework, dependencies and git status for *path*."""
    logger.info("get_project_info: %s", path)

    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": reason}

    try:
        project = Path(path).expanduser().resolve()
        if not project.exists():
            return {"error": f"Path not found: {path}"}

        language = _detect_language(project)
        framework = _detect_framework(project, language)
        dependencies = _get_dependencies(project, language)

        git_info: dict[str, Any] = {"is_repo": False}
        if (project / ".git").exists():
            try:
                branch = subprocess.check_output(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=str(project),
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
                remote = subprocess.check_output(
                    ["git", "remote", "get-url", "origin"],
                    cwd=str(project),
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
                git_info = {"is_repo": True, "branch": branch, "remote": remote}
            except subprocess.CalledProcessError:
                git_info = {"is_repo": True, "branch": "unknown", "remote": None}

        file_count = sum(1 for _ in project.rglob("*") if _.is_file())
        dir_count = sum(1 for _ in project.rglob("*") if _.is_dir())

        return {
            "path": str(project),
            "name": project.name,
            "language": language,
            "framework": framework,
            "dependencies": dependencies,
            "git": git_info,
            "file_count": file_count,
            "dir_count": dir_count,
        }
    except PermissionError:
        return {"error": f"Permission denied: {path}"}
    except Exception as exc:
        return {"error": f"Failed to get project info: {exc}"}


# ---------------------------------------------------------------------------
# System info & process management
# ---------------------------------------------------------------------------

async def get_system_info() -> dict[str, Any]:
    """Get CPU, RAM, disk, and GPU information."""
    info: dict[str, Any] = {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
    }

    try:
        import psutil

        mem = psutil.virtual_memory()
        info["ram"] = {
            "total_gb": round(mem.total / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "percent_used": mem.percent,
        }

        disk = psutil.disk_usage("/")
        info["disk"] = {
            "total_gb": round(disk.total / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "percent_used": disk.percent,
        }

        info["cpu_percent"] = psutil.cpu_percent(interval=0.5)
    except ImportError:
        info["ram"] = "psutil not installed"
        info["disk"] = "psutil not installed"
        info["cpu_percent"] = "psutil not installed"

    info["gpu"] = []
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    info["gpu"].append(
                        {
                            "name": parts[0],
                            "memory_total_mb": parts[1],
                            "memory_used_mb": parts[2],
                            "utilization_percent": parts[3],
                        }
                    )
    except Exception:
        pass

    if not info["gpu"]:
        info["gpu"] = "No GPU detected or nvidia-smi not available"

    return info


async def find_processes(name: str = "") -> dict[str, Any]:
    """Find running processes by name (case-insensitive substring match)."""
    processes: list[dict[str, Any]] = []

    try:
        import psutil

        for proc in psutil.process_iter(
            ["pid", "name", "cmdline", "cpu_percent", "memory_percent"]
        ):
            proc_name = proc.info.get("name") or ""
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if name.lower() in proc_name.lower() or name.lower() in cmdline.lower():
                processes.append(
                    {
                        "pid": proc.info.get("pid"),
                        "name": proc_name,
                        "cmdline": cmdline,
                        "cpu_percent": proc.info.get("cpu_percent"),
                        "memory_percent": round(
                            proc.info.get("memory_percent") or 0, 2
                        ),
                    }
                )
    except ImportError:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["tasklist", "/FO", "CSV"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n")[1:]:
                    parts = [p.strip('"') for p in line.split('","')]
                    if len(parts) >= 2 and name.lower() in parts[0].lower():
                        processes.append(
                            {
                                "pid": parts[1],
                                "name": parts[0],
                                "cmdline": "",
                                "cpu_percent": None,
                                "memory_percent": None,
                            }
                        )
        else:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n")[1:]:
                    if name.lower() in line.lower():
                        parts = line.split()
                        if len(parts) >= 11:
                            processes.append(
                                {
                                    "pid": parts[1],
                                    "name": parts[10],
                                    "cmdline": " ".join(parts[10:]),
                                    "cpu_percent": parts[2],
                                    "memory_percent": parts[3],
                                }
                            )

    return {"name": name, "processes": processes, "count": len(processes)}


async def kill_process(pid: int) -> dict[str, Any]:
    """Kill a process by PID."""
    try:
        try:
            import psutil

            proc = psutil.Process(pid)
            proc.terminate()
            gone, alive = psutil.wait_procs([proc], timeout=5)
            if proc in alive:
                proc.kill()
                return {"killed": True, "force": True, "pid": pid}
        except ImportError:
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    check=True,
                    timeout=10,
                )
            else:
                subprocess.run(
                    ["kill", "-9", str(pid)], check=True, timeout=10
                )

        return {"killed": True, "force": False, "pid": pid}
    except Exception as exc:
        return {"error": f"Failed to kill process {pid}: {exc}"}


# ---------------------------------------------------------------------------
# WorkspaceManager class — backward-compatible wrapper
# ---------------------------------------------------------------------------

class WorkspaceManager:
    """Central manager for filesystem and shell operations.

    Wraps the free functions so that ``file_ops.py`` and ``shell_runner.py``
    can continue to instantiate ``WorkspaceManager(project_path)``.
    """

    def __init__(self, project_path: str = "."):
        self.project_path = Path(project_path).resolve()

    def _resolve(self, path: str) -> str:
        """Resolve *path* relative to ``project_path`` if it is not absolute."""
        if Path(path).is_absolute():
            return path
        return str(self.project_path / path)

    def _resolve_path(self, path: str) -> Path:
        """Return a :class:`Path` resolved relative to ``project_path``."""
        if Path(path).is_absolute():
            return Path(path).resolve()
        return (self.project_path / path).resolve()

    def _validate_path(self, path: Path, _operation: str = "") -> None:
        """Raise ``PermissionError`` if *path* is outside ``project_path``."""
        try:
            path.relative_to(self.project_path)
        except ValueError:
            raise PermissionError(
                f"Path {path} is outside project root {self.project_path}"
            ) from None

    def _check_project_trust(self, _path: Path) -> None:
        """Raise ``PermissionError`` if the project is not trusted."""
        from backend.persistence.db import get_project_by_path

        project = get_project_by_path(str(self.project_path))
        if project and not project.get("trust", False):
            raise PermissionError(
                f"Project '{project['name']}' is NOT trusted. "
                "Enable trust in project settings before allowing file modifications."
            )

    async def read_file(self, path: str) -> dict[str, Any]:
        return await read_file_absolute(self._resolve(path))

    async def write_file(
        self,
        path: str,
        content: str,
        session_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        abs_path = self._resolve(path)

        # Trust verification — block writes to untrusted projects
        from backend.persistence.db import get_project_by_path

        project = get_project_by_path(str(self.project_path))
        if project and not project.get("trust", False):
            return {
                "error": (
                    f"Project '{project['name']}' is NOT trusted. "
                    "Enable trust in project settings before allowing file modifications."
                )
            }

        result = await write_file_absolute(abs_path, content)

        if session_id and "error" not in result:
            propose_change(
                session_id=session_id,
                project_id=project_id,
                file_path=str(Path(abs_path).relative_to(self.project_path)),
                operation="modify" if result.get("backup", {}).get("backed_up") else "create",
                new_content=content,
            )

        return result

    async def list_directory(self, path: str, recursive: bool = False) -> dict[str, Any]:
        return await list_dir_absolute(self._resolve(path), recursive=recursive)

    async def search_files(
        self, path: str, pattern: str, glob: str = "*.py"
    ) -> dict[str, Any]:
        # The legacy signature expects path + pattern + glob.
        # We perform a content search under *path* and filter by glob.
        search_root = self._resolve(path)
        results = []
        count = 0
        try:
            root = Path(search_root)
            for file_path in root.rglob(glob):
                if not file_path.is_file():
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                if pattern.lower() in content.lower():
                    lines = content.splitlines()
                    matches = [
                        (i + 1, line)
                        for i, line in enumerate(lines)
                        if pattern.lower() in line.lower()
                    ]
                    if matches:
                        results.append(
                            {
                                "path": str(file_path.relative_to(root)),
                                "matches": len(matches),
                                "preview": matches[:3],
                            }
                        )
                        count += 1
        except Exception as exc:
            return {"error": f"Search failed: {exc}"}

        return {"query": pattern, "results": results, "count": count}

    async def execute_shell(
        self, command: str, cwd: str | None = None, timeout: int = 120, env: dict[str, str] | None = None
    ) -> dict[str, Any]:
        resolved_cwd = self._resolve(cwd) if cwd else str(self.project_path)
        return await execute_shell(command, cwd=resolved_cwd, timeout=timeout, env=env)

    async def execute_python(
        self, code: str, cwd: str | None = None, timeout: int = 120
    ) -> dict[str, Any]:
        resolved_cwd = self._resolve(cwd) if cwd else str(self.project_path)
        return await execute_python(code, cwd=resolved_cwd, timeout=timeout)

    async def create_directory(self, path: str) -> dict[str, Any]:
        return await create_dir_absolute(self._resolve(path))

    async def delete_file(self, path: str, move_to_trash: bool = True) -> dict[str, Any]:
        return await delete_file_absolute(self._resolve(path), move_to_trash=move_to_trash)

    async def git_init(self, path: str | None = None) -> dict[str, Any]:
        return await git_init(self._resolve(path) if path else str(self.project_path))

    async def git_clone(self, url: str, path: str) -> dict[str, Any]:
        return await git_clone(url, self._resolve(path))

    async def git_commit_all(
        self, path: str | None = None, message: str = "auto: changes from NEXUS workspace"
    ) -> dict[str, Any]:
        return await git_commit_all(
            self._resolve(path) if path else str(self.project_path), message
        )

    async def git_push(
        self, path: str | None = None, remote: str = "origin", branch: str | None = None
    ) -> dict[str, Any]:
        return await git_push(
            self._resolve(path) if path else str(self.project_path), remote, branch
        )

    async def git_status(self, path: str | None = None) -> dict[str, Any]:
        return await git_status(self._resolve(path) if path else str(self.project_path))

    async def git_commit(
        self, repo_path: str = ".", message: str = "auto: changes from NEXUS agent"
    ) -> dict[str, Any]:
        """Safely commit changes (without add)."""
        return await git_commit_all(self._resolve(repo_path), message=message)

    async def get_system_info(self) -> dict[str, Any]:
        return await get_system_info()

    async def find_processes(self, name: str = "") -> dict[str, Any]:
        return await find_processes(name)

    async def kill_process(self, pid: int) -> dict[str, Any]:
        return await kill_process(pid)

    # ── Auto-trust ──────────────────────────────────────────────────────────

    def auto_trust_project(self, path: str | Path) -> None:
        """Mark a project path as auto-trusted (created by the system)."""
        from backend.persistence.db import get_project_by_path, update_project

        resolved = Path(path).resolve()
        logger.info("Auto-trusted project path: %s", resolved)

        try:
            project = get_project_by_path(str(resolved))
            if project and not project.get("trust", False):
                update_project(project["id"], trust=True)
                logger.info("Updated project %s trust status in database", project["id"])
        except Exception:
            logger.exception("Failed to update project trust in database")

    def create_project_auto_trusted(
        self,
        name: str,
        path: str,
        description: str = "",
        mode: str = "auto",
        preferred_model: str | None = None,
    ) -> dict[str, Any]:
        """Create a project and mark it as auto-trusted."""
        from backend.persistence.db import create_project

        project = create_project(
            name=name,
            path=path,
            description=description,
            mode=mode,
            preferred_model=preferred_model,
            trust=True,
        )
        self.auto_trust_project(path)
        return project

    # ── Audit logging ───────────────────────────────────────────────────────

    async def _log_operation(
        self,
        operation: str,
        args: dict[str, Any],
        result: Any,
        success: bool = True,
        error: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Log an operation to the audit log and database."""
        logger.info(
            "Workspace operation: %s success=%s error=%s",
            operation,
            success,
            error,
        )
        try:
            from backend.persistence.db import log_tool_execution

            log_tool_execution(
                session_id=session_id,
                tool_name=f"workspace.{operation}",
                args=args,
                result=result,
                success=success,
                error=error,
                duration_ms=0,
            )
        except Exception:
            logger.exception("Failed to log workspace operation to database")


# ---------------------------------------------------------------------------
# Tool registration — new absolute-path tools
# ---------------------------------------------------------------------------

from backend.tools.registry import ToolSpec, register_tool  # noqa: E402

register_tool(
    ToolSpec(
        name="read_file_absolute",
        description="Read any file using an absolute path (user permissions apply)",
        schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Absolute file path"}},
            "required": ["path"],
        },
        handler=read_file_absolute,
    )
)

register_tool(
    ToolSpec(
        name="write_file_absolute",
        description="Write any file using an absolute path. Creates a backup automatically.",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
        handler=write_file_absolute,
    )
)

register_tool(
    ToolSpec(
        name="list_dir_absolute",
        description="List any directory using an absolute path",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute directory path"},
                "recursive": {"type": "boolean", "default": False, "description": "Recursive listing"},
            },
            "required": ["path"],
        },
        handler=list_dir_absolute,
    )
)

register_tool(
    ToolSpec(
        name="create_dir_absolute",
        description="Create directories recursively using an absolute path",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute directory path"},
            },
            "required": ["path"],
        },
        handler=create_dir_absolute,
    )
)

register_tool(
    ToolSpec(
        name="delete_file_absolute",
        description="Delete a file using an absolute path (moves to trash by default)",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
                "move_to_trash": {
                    "type": "boolean",
                    "default": True,
                    "description": "Move to trash instead of permanent delete",
                },
            },
            "required": ["path"],
        },
        handler=delete_file_absolute,
    )
)

register_tool(
    ToolSpec(
        name="search_files_absolute",
        description="Grep-like search across files under an absolute root path",
        schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Text pattern to search for"},
                "root_path": {"type": "string", "description": "Absolute root directory to search in"},
                "max_results": {
                    "type": "integer",
                    "default": 100,
                    "description": "Maximum number of files to return",
                },
            },
            "required": ["pattern", "root_path"],
        },
        handler=search_files_absolute,
    )
)

register_tool(
    ToolSpec(
        name="execute_shell",
        description="Execute any shell command (dangerous patterns are blocked). Supports custom cwd, timeout and env.",
        schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "cwd": {"type": "string", "description": "Working directory (absolute path)"},
                "timeout": {"type": "integer", "default": 120, "description": "Timeout in seconds"},
                "env": {"type": "object", "description": "Additional environment variables"},
            },
            "required": ["command"],
        },
        handler=execute_shell,
    )
)

register_tool(
    ToolSpec(
        name="execute_python",
        description="Execute a Python code string in a temporary file",
        schema={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"},
                "cwd": {"type": "string", "description": "Working directory (absolute path)"},
                "timeout": {"type": "integer", "default": 120, "description": "Timeout in seconds"},
            },
            "required": ["code"],
        },
        handler=execute_python,
    )
)

register_tool(
    ToolSpec(
        name="execute_script",
        description="Execute any script file by absolute path (auto-detects interpreter)",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute script path"},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command-line arguments",
                },
                "cwd": {"type": "string", "description": "Working directory (absolute path)"},
                "timeout": {"type": "integer", "default": 120, "description": "Timeout in seconds"},
            },
            "required": ["path"],
        },
        handler=execute_script,
    )
)

register_tool(
    ToolSpec(
        name="git_init",
        description="Initialise a git repository at an absolute path",
        schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Absolute directory path"}},
            "required": ["path"],
        },
        handler=git_init,
    )
)

register_tool(
    ToolSpec(
        name="git_clone",
        description="Clone a git repository into an absolute path",
        schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Repository URL"},
                "path": {"type": "string", "description": "Absolute destination path"},
            },
            "required": ["url", "path"],
        },
        handler=git_clone,
    )
)

register_tool(
    ToolSpec(
        name="git_commit_all",
        description="Stage all changes and commit in a git repository",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute repository path"},
                "message": {
                    "type": "string",
                    "default": "auto: changes from NEXUS workspace",
                    "description": "Commit message",
                },
            },
            "required": ["path"],
        },
        handler=git_commit_all,
    )
)

register_tool(
    ToolSpec(
        name="git_push",
        description="Push commits from a git repository (allowed for workspace manager)",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute repository path"},
                "remote": {"type": "string", "default": "origin", "description": "Remote name"},
                "branch": {"type": "string", "description": "Branch name (optional)"},
            },
            "required": ["path"],
        },
        handler=git_push,
    )
)

register_tool(
    ToolSpec(
        name="git_status",
        description="Return git status for a repository at an absolute path",
        schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Absolute repository path"}},
            "required": ["path"],
        },
        handler=git_status,
    )
)

register_tool(
    ToolSpec(
        name="discover_projects",
        description="Discover git repos and common project structures under an absolute root path",
        schema={
            "type": "object",
            "properties": {
                "root_path": {"type": "string", "description": "Absolute root directory"},
            },
            "required": ["root_path"],
        },
        handler=discover_projects,
    )
)

register_tool(
    ToolSpec(
        name="get_project_info",
        description="Detect language, framework, dependencies and git status for a project path",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute project path"},
            },
            "required": ["path"],
        },
        handler=get_project_info,
    )
)
