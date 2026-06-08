"""Workspace Manager — full filesystem and terminal access for NEXUS agents.

Replaces sandboxed file_ops / shell_runner with absolute-path operations.
Dangerous commands and system paths are blocked via blacklist; user home and
project directories are always allowed. All operations are logged and writes
are backed up to ``.nexus/backups/``.

Exposes both a :class:`WorkspaceManager` (used by legacy ``file_ops.py`` and
``shell_runner.py``) and free functions (registered as new absolute-path tools).
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import logging
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.persistence.db import propose_change

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Security configuration
# ---------------------------------------------------------------------------

# Maximum file size (in bytes) for read/write/backup/search operations.
# Files larger than this limit are rejected to prevent memory exhaustion.
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def _check_file_size_limit(path: Path) -> tuple[bool, int | None, str]:
    """Check whether *path* exceeds the configured file-size limit.

    Returns ``(ok, size_bytes, error_message)``.  ``ok`` is ``True`` when the
    file is within the limit or the size could not be determined.
    """
    try:
        size = path.stat().st_size
    except (OSError, ValueError):
        return True, None, ""
    if size > MAX_FILE_SIZE_BYTES:
        return (
            False,
            size,
            f"File exceeds size limit of {MAX_FILE_SIZE_BYTES} bytes (actual: {size} bytes)",
        )
    return True, size, ""


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

# Sensitive path components that are blocked anywhere in the resolved path
_BLOCKED_PATH_COMPONENTS: set[str] = {
    ".ssh",
    ".aws",
    ".env",
    ".git-credentials",
    ".docker",
    ".kube",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".pgpass",
    ".mysql_history",
    ".bash_history",
    ".zsh_history",
    ".psql_history",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "token",
    "tokens",
    "wallet",
    "wallets",
    "secret",
    "secrets",
    "credential",
    "credentials",
    "api_key",
    "apikey",
    "private_key",
    "privkey",
    "keystore",
    ".keystore",
    "seed",
    "mnemonic",
}

# Sensitive user paths that should NEVER be accessed by AI agents
_BLOCKED_SENSITIVE_PATHS: set[str] = {
    ".ssh",
    ".aws",
    ".gcloud",
    ".config/gcloud",
    ".kube",
    ".docker",
    ".npmrc",
    ".pypirc",
    ".git-credentials",
    ".netrc",
    ".pgpass",
    ".my.cnf",
    ".bash_history",
    ".zsh_history",
    ".env",
    ".env.local",
    ".env.production",
    ".env.backup",
    ".local/share/keyrings",
    ".config/Keychains",
    ".gnupg",
    ".password-store",
    ".vault",
    ".terraform.d",
    "id_rsa",
    "id_ecdsa",
    "id_ed25519",
    ".pem",
    ".p12",
    ".pfx",
    ".keystore",
    "AppData/Roaming/Mozilla",
    "AppData/Roaming/Google",
    "AppData/Local/Google",
    "AppData/Roaming/Microsoft/Credentials",
    "AppData/Local/Microsoft/Credentials",
}

def _verify_auth_token(token: str | None) -> tuple[bool, str]:
    """Validate a JWT access token."""
    if token is None:
        return False, "Authentication required"
    try:
        from jose import JWTError, jwt
        from backend.config.settings import get_settings

        settings = get_settings()
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("sub") is None:
            return False, "Invalid authentication token"
        return True, ""
    except JWTError as exc:
        return False, f"Authentication failed: {exc}"
    except Exception as exc:
        return False, f"Authentication failed: {exc}"


def _log_operation(
    tool_name: str,
    args: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """Log a workspace operation to the audit database."""
    try:
        from backend.persistence.db import log_tool_execution

        log_tool_execution(
            session_id=None,
            tool_name=tool_name,
            args=args,
            result=result,
            success="error" not in result,
            error=result.get("error"),
            duration_ms=0,
        )
    except Exception:
        logger.exception("Failed to log workspace operation to database")


def _get_allowed_base_paths() -> list[Path]:
    """Return a list of allowed base paths for absolute-path operations.

    A path is permitted only if it is located *under* one of these bases
    (prefix / ``relative_to`` matching).  Substring matching on individual
    path components is intentionally **not** used.
    """
    paths: set[Path] = set()
    paths.add(Path.home().resolve())
    try:
        paths.add(Path.cwd().resolve())
    except Exception:
        pass
    try:
        paths.add(Path(tempfile.gettempdir()).resolve())
    except Exception:
        pass
    return list(paths)


def _is_blocked_path(path: str) -> tuple[bool, str]:
    """Check whether *path* resolves to a blocked system directory.

    Paths under the user's home directory, the current working directory,
    or the system temp directory are permitted only if they do NOT also
    fall under a blocked system path.  All other paths are blocked by
    default (implicit deny).
    """
    try:
        raw = Path(path).expanduser()
    except (OSError, ValueError) as exc:
        return True, f"Invalid path: {exc}"

    # Explicit ``..`` traversal check before resolution so that symlinks
    # cannot be used to smuggle traversal past ``resolve()``.
    if ".." in raw.parts:
        return True, "Path traversal ('..') is not allowed"

    try:
        resolved = raw.resolve()
    except (OSError, ValueError) as exc:
        return True, f"Invalid path: {exc}"

    # 1. Blocked system paths (prefix matching) — checked FIRST so blocked
    #    always wins even when the path is inside an allowed base.
    for blocked in _BLOCKED_SYSTEM_PATHS:
        bpath = Path(blocked).resolve() if ":" not in blocked else Path(blocked)
        try:
            resolved.relative_to(bpath)
            return True, f"Access to system path '{blocked}' is blocked"
        except ValueError:
            continue

    # 1b. Blocked path components — checked before allowed bases
    # Block any path that contains sensitive components (single segments).
    parts_lower = [p.lower() for p in resolved.parts]
    for component in _BLOCKED_PATH_COMPONENTS:
        if component.lower() in parts_lower:
            return True, f"Access to sensitive component '{component}' is blocked"

    # 1c. Blocked sensitive multi-component paths — checked before allowed bases
    # These are multi-segment paths like .config/gcloud, AppData/Roaming/Mozilla.
    # We reconstruct the path string using forward slashes for consistent matching.
    path_str_normalized = str(resolved).lower().replace("\\", "/")
    for sensitive in _BLOCKED_SENSITIVE_PATHS:
        # Skip single-component entries already handled above
        if "/" not in sensitive:
            continue
        sens_normalized = sensitive.lower().replace("\\", "/")
        # Check if the normalized path contains this sensitive subpath
        if sens_normalized in path_str_normalized:
            return True, f"Access to sensitive path '{sensitive}' is blocked"

    # 2. Allowed bases (prefix matching)
    for allowed in _get_allowed_base_paths():
        try:
            resolved.relative_to(allowed)
            return False, ""
        except ValueError:
            continue

    # 3. Implicit deny — path is outside all allowed roots.
    return True, "Path is outside allowed directories"


_SHELL_WHITELIST: set[str] = {
    # Original whitelist
    "python",
    "python3",
    "py",
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
    # Expanded whitelist
    "cargo",
    "rustc",
    "go",
    "javac",
    "mvn",
    "gradle",
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

_SAFE_GIT_HOSTS: set[str] = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
}

# ---------------------------------------------------------------------------
# Python sandbox (AST-based — bypass-resistant)
# ---------------------------------------------------------------------------

_DANGEROUS_MODULES: set[str] = {
    "os",
    "subprocess",
    "socket",
    "urllib",
    "urllib.request",
    "ctypes",
    "pty",
}


def _check_python_sandbox(code: str) -> tuple[bool, str]:
    """Scan Python code for dangerous imports / operations using AST.

    Regex-based scanning is easily bypassed via encoding tricks, dynamic
    imports, string concatenation, etc.  AST parsing gives us a reliable
    view of every import and dangerous call in the code.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"Invalid Python syntax: {exc}"

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    base = alias.name.split(".")[0]
                    if base in _DANGEROUS_MODULES:
                        return False, f"import {alias.name} is blocked in sandbox mode"
            elif isinstance(node, ast.ImportFrom):
                base = (node.module or "").split(".")[0]
                if base in _DANGEROUS_MODULES:
                    return False, f"from {node.module} import is blocked in sandbox mode"

        if isinstance(node, ast.Call):
            # Block __import__ with dangerous modules
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                base = node.args[0].value.split(".")[0]
                if base in _DANGEROUS_MODULES:
                    return False, f"__import__({node.args[0].value}) is blocked in sandbox mode"

            # Block importlib.import_module with dangerous modules
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "importlib"
                and node.func.attr == "import_module"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                base = node.args[0].value.split(".")[0]
                if base in _DANGEROUS_MODULES:
                    return False, f"importlib.import_module({node.args[0].value}) is blocked in sandbox mode"

            # Block eval, exec, compile
            if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec", "compile"):
                return False, f"{node.func.id}() is blocked in sandbox mode"

            # Block os.system, os.popen, os.exec*, subprocess.call, etc.
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                if (
                    node.func.value.id in _DANGEROUS_MODULES
                    and node.func.attr in ("system", "popen", "exec", "execv", "execve", "fork", "kill", "spawn")
                ):
                    return False, f"{node.func.value.id}.{node.func.attr}() is blocked in sandbox mode"

    return True, ""


# ---------------------------------------------------------------------------
# Dangerous pipe targets (curl piped to these is blocked)
# ---------------------------------------------------------------------------

_DANGEROUS_PIPE_TARGETS: set[str] = {
    "python",
    "python3",
    "py",
    "node",
    "bash",
    "sh",
    "zsh",
    "fish",
    "ruby",
    "perl",
    "php",
    "cmd",
    "powershell",
    "pwsh",
    "exec",
}


# ---------------------------------------------------------------------------
# Shell-command validation helpers
# ---------------------------------------------------------------------------

_DISALLOWED_METACHARACTERS = (";", "&&", "||", "`", "$(", ">>", ">", "<")


def _remove_quoted_parts(s: str) -> str:
    """Strip double-quoted and single-quoted substrings from *s*.

    Used so that metacharacters *inside* quotes do not trigger a block.
    """
    # Remove double-quoted strings (greedy is fine here).
    s = re.sub(r'"[^"]*"', '""', s)
    # Remove single-quoted strings.
    s = re.sub(r"'[^']*'", "''", s)
    return s


def _has_unquoted_metacharacters(command: str) -> bool:
    """Return ``True`` if *command* contains dangerous shell operators
    outside of quoted regions."""
    cleaned = _remove_quoted_parts(command)
    for op in _DISALLOWED_METACHARACTERS:
        if op in cleaned:
            return True
    return False


def _split_on_pipes(command: str) -> list[str]:
    """Split *command* on unquoted ``|`` characters."""
    segments: list[str] = []
    current: list[str] = []
    in_double = False
    in_single = False
    for ch in command:
        if ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "'" and not in_double:
            in_single = not in_single
        elif ch == "|" and not in_double and not in_single:
            segments.append("".join(current))
            current = []
            continue
        current.append(ch)
    segments.append("".join(current))
    return [s.strip() for s in segments if s.strip()]


def _validate_single_command(command: str) -> tuple[bool, str]:
    """Validate one shell segment (no pipes, no chaining)."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.strip().split()

    if not tokens:
        return False, "Empty command"

    base_cmd = Path(tokens[0]).stem.lower()

    # Special handling for git
    if base_cmd == "git":
        if len(tokens) >= 2:
            subcmd = tokens[1].lower()
            if subcmd in _GIT_BLOCKED_SUBCOMMANDS:
                return False, f"Git subcommand '{subcmd}' is blocked for safety"
            cmd_lower = command.lower()
            for flag in _GIT_BLOCKED_FLAGS:
                if flag in cmd_lower:
                    return False, f"Git flag '{flag}' is blocked for safety"
        return True, ""

    # Block inline code execution flags that enable arbitrary code execution
    if base_cmd in ("python", "python3", "py"):
        if any(t == "-c" for t in tokens[1:]):
            return False, f"{base_cmd} -c (inline code execution) is blocked for safety"
    if base_cmd == "node":
        if any(t == "-e" for t in tokens[1:]):
            return False, "node -e (inline code execution) is blocked for safety"
    if base_cmd in ("bash", "sh", "zsh", "fish"):
        if any(t == "-c" for t in tokens[1:]):
            return False, f"{base_cmd} -c (inline code execution) is blocked for safety"

    if base_cmd not in _SHELL_WHITELIST:
        return False, f"Command '{base_cmd}' is not in the safe command whitelist"

    return True, ""


def _validate_shell_command(command: str) -> tuple[bool, str]:
    """Validate a shell command against blacklist and whitelist.

    Every segment produced by ``|`` is validated individually.  Commands
    containing ``;``, ``&&``, ``||``, backticks, ``$()``, or redirections
    are rejected outright.
    """
    if not command or not command.strip():
        return False, "Empty command"

    cmd_str = command.strip()
    cmd_lower = cmd_str.lower()

    # Blocked dangerous patterns (whole command)
    for pattern in _BLOCKED_COMMAND_PATTERNS:
        if pattern.lower() in cmd_lower:
            return False, f"Dangerous pattern '{pattern}' is blocked"

    # Blocked system paths in command string
    for blocked_path in _BLOCKED_SYSTEM_PATHS:
        if blocked_path.lower() in cmd_lower:
            return False, f"Access to system path '{blocked_path}' is blocked"

    # Reject shell metacharacters that allow command chaining / substitution
    if _has_unquoted_metacharacters(cmd_str):
        return False, "Shell metacharacters (;, &&, ||, `, $(), >, <, >>) are not allowed"

    # Split on pipes and validate every segment
    segments = _split_on_pipes(cmd_str)
    if not segments:
        return False, "Empty command"

    for segment in segments:
        is_safe, reason = _validate_single_command(segment)
        if not is_safe:
            return False, reason

    # Extra curl restriction: piping curl to an interpreter is forbidden
    # because it enables one-liner remote code execution.
    if len(segments) > 1:
        for seg in segments:
            try:
                base = Path(shlex.split(seg)[0]).name.lower()
            except ValueError:
                base = seg.strip().split()[0].lower()
            if base == "curl":
                for other in segments:
                    if other is seg:
                        continue
                    try:
                        other_base = Path(shlex.split(other)[0]).name.lower()
                    except ValueError:
                        other_base = other.strip().split()[0].lower()
                    if other_base in _DANGEROUS_PIPE_TARGETS:
                        return False, f"Piping curl to '{other_base}' is blocked for safety"

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

async def _backup_dir_for(path: Path) -> Path:
    """Return the backup directory for a given file path."""
    candidate = await asyncio.to_thread(path.resolve)
    parents = await asyncio.to_thread(lambda: list(candidate.parents))
    for parent in [candidate] + parents:
        if await asyncio.to_thread(parent.is_dir):
            git_root = await _get_git_root(parent)
            if git_root is not None:
                return git_root / ".nexus" / "backups"
        if await asyncio.to_thread((parent / ".nexus").exists):
            return parent / ".nexus" / "backups"
    return Path.home() / ".nexus" / "backups"


async def _create_backup(path: Path) -> dict[str, Any]:
    """Create a timestamped backup of *path* and return metadata."""
    if not await asyncio.to_thread(path.exists):
        return {"backed_up": False, "reason": "file did not exist"}

    ok, size, err = _check_file_size_limit(path)
    if not ok:
        logger.warning("Backup skipped for %s: %s", path, err)
        return {"backed_up": False, "reason": err, "size": size}

    try:
        original = await asyncio.to_thread(path.read_bytes)
    except Exception as exc:
        return {"backed_up": False, "reason": str(exc)}

    backup_dir = await _backup_dir_for(path)
    await asyncio.to_thread(backup_dir.mkdir, parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    hash_suffix = hashlib.sha256(str(path).encode()).hexdigest()[:8]
    backup_name = f"{path.name}.{timestamp}.{hash_suffix}.bak"
    backup_path = backup_dir / backup_name

    try:
        await asyncio.to_thread(backup_path.write_bytes, original)
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
        target = await asyncio.to_thread(lambda: Path(path).expanduser().resolve())
        ok, size, err = _check_file_size_limit(target)
        if not ok:
            return {"error": err, "path": str(target), "size": size}
        content = await asyncio.to_thread(target.read_text, encoding="utf-8")
        return {"path": str(target), "content": content, "size": len(content)}
    except FileNotFoundError:
        return {"error": f"File not found: {path}"}
    except PermissionError:
        return {"error": f"Permission denied: {path}"}
    except Exception as exc:
        return {"error": f"Failed to read file: {exc}"}


async def write_file_absolute(
    path: str, content: str, auth_token: str | None = None
) -> dict[str, Any]:
    """Write any file (absolute path) with backup of the original."""
    logger.info("write_file_absolute: %s (%d bytes)", path, len(content))

    if auth_token is not None:
        ok, reason = _verify_auth_token(auth_token)
        if not ok:
            return {"error": reason}

    blocked, reason = _is_blocked_path(path)
    if blocked:
        result = {"error": reason}
        _log_operation("write_file_absolute", {"path": path}, result)
        return result

    try:
        target = await asyncio.to_thread(lambda: Path(path).expanduser().resolve())
        backup_meta = await _create_backup(target)
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_text, content, encoding="utf-8")
        result = {"path": str(target), "written": True, "size": len(content), "backup": backup_meta}
        _log_operation("write_file_absolute", {"path": path}, result)
        return result
    except PermissionError:
        result = {"error": f"Permission denied: {path}"}
        _log_operation("write_file_absolute", {"path": path}, result)
        return result
    except Exception as exc:
        result = {"error": f"Failed to write file: {exc}"}
        _log_operation("write_file_absolute", {"path": path}, result)
        return result


async def list_dir_absolute(path: str, recursive: bool = False) -> dict[str, Any]:
    """List any directory (absolute path)."""
    logger.info("list_dir_absolute: %s (recursive=%s)", path, recursive)

    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": reason}

    try:
        target = await asyncio.to_thread(lambda: Path(path).expanduser().resolve())
        if not await asyncio.to_thread(target.exists):
            return {"error": f"Path not found: {path}"}
        if not await asyncio.to_thread(target.is_dir):
            return {"error": f"Path is not a directory: {path}"}

        if recursive:
            raw_items = await asyncio.to_thread(lambda: list(target.rglob("*")))
        else:
            raw_items = await asyncio.to_thread(lambda: list(target.iterdir()))

        items = []
        for item in raw_items:
            is_file = await asyncio.to_thread(item.is_file)
            size = await asyncio.to_thread(lambda: item.stat().st_size) if is_file else 0
            items.append(
                {
                    "path": str(item),
                    "name": item.name,
                    "type": "file" if is_file else "dir",
                    "size": size,
                }
            )

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
        target = await asyncio.to_thread(lambda: Path(path).expanduser().resolve())
        await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)
        return {"path": str(target), "created": True}
    except PermissionError:
        return {"error": f"Permission denied: {path}"}
    except Exception as exc:
        return {"error": f"Failed to create directory: {exc}"}


async def delete_file_absolute(
    path: str, move_to_trash: bool = True, auth_token: str | None = None
) -> dict[str, Any]:
    """Delete a file (absolute path) with optional trash/recovery."""
    logger.info("delete_file_absolute: %s (trash=%s)", path, move_to_trash)

    if auth_token is not None:
        ok, reason = _verify_auth_token(auth_token)
        if not ok:
            return {"error": reason}

    blocked, reason = _is_blocked_path(path)
    if blocked:
        result = {"error": reason}
        _log_operation("delete_file_absolute", {"path": path}, result)
        return result

    try:
        target = await asyncio.to_thread(lambda: Path(path).expanduser().resolve())
        if not await asyncio.to_thread(target.exists):
            result = {"error": f"File not found: {path}"}
            _log_operation("delete_file_absolute", {"path": path}, result)
            return result
        if await asyncio.to_thread(target.is_dir):
            result = {"error": "Path is a directory; use recursive directory deletion instead"}
            _log_operation("delete_file_absolute", {"path": path}, result)
            return result

        if move_to_trash:
            trash_dir = await _backup_dir_for(target) / "trash"
            await asyncio.to_thread(trash_dir.mkdir, parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            hash_suffix = hashlib.sha256(str(target).encode()).hexdigest()[:8]
            trash_name = f"{target.name}.{timestamp}.{hash_suffix}"
            trash_path = trash_dir / trash_name
            await asyncio.to_thread(shutil.move, str(target), str(trash_path))
            logger.info("Moved to trash: %s -> %s", target, trash_path)
            result = {"path": str(target), "deleted": True, "trash_path": str(trash_path)}
            _log_operation("delete_file_absolute", {"path": path}, result)
            return result

        await asyncio.to_thread(target.unlink)
        logger.info("Deleted permanently: %s", target)
        result = {"path": str(target), "deleted": True, "trash_path": None}
        _log_operation("delete_file_absolute", {"path": path}, result)
        return result
    except PermissionError:
        result = {"error": f"Permission denied: {path}"}
        _log_operation("delete_file_absolute", {"path": path}, result)
        return result
    except Exception as exc:
        result = {"error": f"Failed to delete file: {exc}"}
        _log_operation("delete_file_absolute", {"path": path}, result)
        return result


async def search_files_absolute(
    pattern: str, root_path: str, max_results: int = 100
) -> dict[str, Any]:
    """Grep-like search across files under *root_path*."""
    logger.info("search_files_absolute: pattern='%s' root='%s'", pattern, root_path)

    blocked, reason = _is_blocked_path(root_path)
    if blocked:
        return {"error": reason}

    try:
        root = await asyncio.to_thread(lambda: Path(root_path).expanduser().resolve())
        if not await asyncio.to_thread(root.exists):
            return {"error": f"Root path not found: {root_path}"}

        results = []
        file_paths = await asyncio.to_thread(lambda: list(root.rglob("*")))
        for file_path in file_paths:
            if not await asyncio.to_thread(file_path.is_file):
                continue
            try:
                stat = await asyncio.to_thread(file_path.stat)
                if stat.st_size > MAX_FILE_SIZE_BYTES:
                    continue
            except Exception:
                continue

            try:
                content = await asyncio.to_thread(file_path.read_text, encoding="utf-8", errors="ignore")
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
        # commands without pipes.  This eliminates quoting / injection issues
        # that only exist when a shell parses the command string.
        # Pipes require a real shell interpreter, so we keep create_subprocess_shell
        # for commands containing ``|``.
        has_pipes = "|" in command
        # On Windows, shlex.split does not handle spaces in paths reliably,
        # so we only use exec for simple commands without spaces on Windows.
        # POSIX systems can use exec for any command without pipes.
        has_spaces = " " in command
        use_exec = not has_pipes and (not sys.platform.startswith("win") or not has_spaces)
        if use_exec:
            try:
                # Windows quoting rules differ from POSIX; posix=False handles
                # backslashes and quotes in a Windows-compatible way.
                args = shlex.split(command, posix=not sys.platform.startswith("win"))
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
            # Pipes (|) require shell interpretation to connect stdout of one
            # process to stdin of another, so we must use create_subprocess_shell.
            # On Windows, commands with spaces also require the shell to parse
            # paths correctly.
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
    target = await asyncio.to_thread(lambda: Path(path).expanduser().resolve())
    await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)
    return await _git_raw(["init"], str(target))


async def git_clone(url: str, path: str) -> dict[str, Any]:
    """Clone a git repository into *path*."""
    logger.info("git_clone: %s -> %s", url, path)
    target = await asyncio.to_thread(lambda: Path(path).expanduser().resolve())
    await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
    return await _git_raw(["clone", url, str(target)], str(target.parent), timeout=180)


async def git_commit_all(
    path: str, message: str = "auto: changes from NEXUS workspace"
) -> dict[str, Any]:
    """Stage all changes and commit in *path*."""
    logger.info("git_commit_all: %s message='%s'", path, message)
    target = str(await asyncio.to_thread(lambda: Path(path).expanduser().resolve()))

    safe_message = message.replace('"', '\\"').replace("`", "").replace("$", "")[:500]

    add_res = await _git_raw(["add", "-A"], target)
    if "error" in add_res and add_res.get("exit_code", 0) != 0:
        return {"error": f"git add failed: {add_res.get('error')}", "add": add_res}

    commit_res = await _git_raw(["commit", "-m", safe_message], target)
    return {"add": add_res, "commit": commit_res}


def _is_safe_git_remote(url: str) -> bool:
    """Return True if *url* points to a known-safe host."""
    url_lower = url.lower()
    for host in _SAFE_GIT_HOSTS:
        if host in url_lower:
            return True
    return False


async def git_push(
    path: str, remote: str = "origin", branch: str | None = None
) -> dict[str, Any]:
    """Push commits from *path*. Only safe remotes are permitted."""
    logger.info("git_push: %s remote=%s branch=%s", path, remote, branch)
    target = str(await asyncio.to_thread(lambda: Path(path).expanduser().resolve()))

    # Validate remote URL before pushing
    remote_check = await _git_raw(["remote", "get-url", remote], target, timeout=30)
    if "error" in remote_check and remote_check.get("exit_code", 0) != 0:
        return {
            "error": f"Cannot verify remote '{remote}': {remote_check.get('error')}",
            "command": f"git push {remote}",
        }

    remote_url = remote_check.get("output", "")
    if not _is_safe_git_remote(remote_url):
        logger.warning("Blocked git_push to unsafe remote: %s", remote_url)
        return {
            "error": (
                f"Push to remote '{remote}' (URL: {remote_url}) is not allowed. "
                "Only GitHub, GitLab, and Bitbucket remotes are permitted."
            ),
            "command": f"git push {remote}",
        }

    args = ["push", remote]
    if branch:
        args.append(branch)
    return await _git_raw(args, target, timeout=120)


async def git_status(path: str) -> dict[str, Any]:
    """Return git status for *path*."""
    logger.info("git_status: %s", path)
    target = str(await asyncio.to_thread(lambda: Path(path).expanduser().resolve()))
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

_SKIP_DIRS: set[str] = {
    "node_modules",
    ".venv",
    "__pycache__",
    ".git",
    "dist",
    "build",
    ".next",
    "target",
    ".cargo",
}


async def _is_git_repo(path: Path) -> bool:
    """Detect whether *path* is inside a git repo by walking up the tree."""
    try:
        cwd = str(path) if await asyncio.to_thread(path.is_dir) else str(path.parent)
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "rev-parse", "--git-dir"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


async def _get_git_root(path: Path) -> Path | None:
    """Return the resolved top-level directory of the git repo containing *path*, or None."""
    try:
        cwd = str(path) if await asyncio.to_thread(path.is_dir) else str(path.parent)
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return await asyncio.to_thread(Path(result.stdout.strip()).resolve)
    except Exception:
        pass
    return None


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


async def _detect_language(project_path: Path) -> str:
    scores: dict[str, int] = {}
    for lang, indicators in _LANGUAGE_INDICATORS.items():
        for indicator in indicators:
            if await asyncio.to_thread((project_path / indicator).exists):
                scores[lang] = scores.get(lang, 0) + 1
    return max(scores, key=scores.get) if scores else "unknown"


async def _detect_framework(project_path: Path, language: str) -> str | None:
    for framework, indicators in _FRAMEWORK_INDICATORS.items():
        for indicator in indicators:
            if await asyncio.to_thread((project_path / indicator).exists):
                return framework
    return None


async def _get_dependencies(project_path: Path, language: str) -> list[str]:
    deps: list[str] = []
    try:
        if language == "python":
            req_file = project_path / "requirements.txt"
            if await asyncio.to_thread(req_file.exists):
                try:
                    text = await asyncio.to_thread(req_file.read_text, encoding="utf-8", errors="ignore")
                except (PermissionError, FileNotFoundError):
                    text = ""
                for line in text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        deps.append(line.split("=")[0].split("<")[0].split(">")[0].strip())
            elif await asyncio.to_thread((project_path / "pyproject.toml").exists):
                deps.append("pyproject.toml")
        elif language in ("javascript", "typescript"):
            pkg_file = project_path / "package.json"
            if await asyncio.to_thread(pkg_file.exists):
                try:
                    text = await asyncio.to_thread(pkg_file.read_text, encoding="utf-8")
                    data = json.loads(text)
                    deps.extend(data.get("dependencies", {}).keys())
                    deps.extend(data.get("devDependencies", {}).keys())
                except Exception:
                    pass
        elif language == "rust":
            if await asyncio.to_thread((project_path / "Cargo.toml").exists):
                deps.append("Cargo.toml")
        elif language == "go":
            if await asyncio.to_thread((project_path / "go.mod").exists):
                deps.append("go.mod")
    except (PermissionError, FileNotFoundError):
        pass
    return deps[:50]


# ---------------------------------------------------------------------------
# Discovery cache
# ---------------------------------------------------------------------------

_DISCOVERY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_DISCOVERY_CACHE_TTL = 300  # 5 minutes


async def discover_projects(
    root_path: str, max_depth: int = 5, max_results: int = 100
) -> dict[str, Any]:
    """Find all git repos and common project structures under *root_path*."""
    logger.info("discover_projects: %s", root_path)

    blocked, reason = _is_blocked_path(root_path)
    if blocked:
        return {"error": reason}

    try:
        root = await asyncio.to_thread(lambda: Path(root_path).expanduser().resolve())
        if not await asyncio.to_thread(root.exists):
            return {"error": f"Root path not found: {root_path}"}
        if not await asyncio.to_thread(root.is_dir):
            return {"error": f"Path is not a directory: {root_path}"}
    except (PermissionError, OSError) as exc:
        return {"error": f"Failed to access root path: {exc}"}

    cache_key = f"{root}:{max_depth}:{max_results}"
    now = time.monotonic()
    cached = _DISCOVERY_CACHE.get(cache_key)
    if cached is not None:
        cached_at, result = cached
        if now - cached_at < _DISCOVERY_CACHE_TTL:
            return {**result, "cached": True}

    projects: list[dict[str, Any]] = []
    seen: set[str] = set()

    async def _is_project_root(path: Path) -> tuple[bool, bool]:
        """Return (is_git_root, is_project) for *path*."""
        try:
            has_git = await asyncio.to_thread((path / ".git").exists)
        except (PermissionError, OSError):
            has_git = False
        is_project = False
        for indicators in _LANGUAGE_INDICATORS.values():
            for indicator in indicators:
                if await asyncio.to_thread((path / indicator).exists):
                    is_project = True
                    break
            if is_project:
                break
        return has_git, is_project

    # If root itself is a project, return it immediately.
    root_git, root_project = await _is_project_root(root)
    if root_git or root_project:
        lang = await _detect_language(root)
        projects.append(
            {
                "path": str(root),
                "name": root.name,
                "is_git_repo": root_git,
                "detected_language": lang,
                "detected_framework": await _detect_framework(root, lang),
            }
        )
        result = {"root": str(root), "projects": projects, "count": len(projects)}
        _DISCOVERY_CACHE[cache_key] = (now, result)
        return {**result, "cached": False}

    async def scan(path: Path, depth: int) -> None:
        if depth > max_depth or len(projects) >= max_results:
            return
        try:
            entries = await asyncio.to_thread(lambda: list(os.scandir(path)))
            for entry in entries:
                if not await asyncio.to_thread(entry.is_dir, follow_symlinks=False):
                    continue
                name = entry.name
                if name in _SKIP_DIRS or name.startswith("."):
                    continue
                child = Path(entry.path)
                child_key = str(child)
                if child_key in seen:
                    continue
                has_git, is_project = await _is_project_root(child)
                if has_git or is_project:
                    seen.add(child_key)
                    lang = await _detect_language(child)
                    projects.append(
                        {
                            "path": child_key,
                            "name": child.name,
                            "is_git_repo": has_git,
                            "detected_language": lang,
                            "detected_framework": await _detect_framework(child, lang),
                        }
                    )
                    # Don't recurse into identified projects — fixes deduplication
                    continue
                await scan(child, depth + 1)
        except PermissionError:
            pass
        except OSError:
            pass

    try:
        await scan(root, 1)
    except PermissionError:
        pass
    except OSError:
        pass

    result = {"root": str(root), "projects": projects, "count": len(projects)}
    _DISCOVERY_CACHE[cache_key] = (now, result)
    return {**result, "cached": False}


async def get_project_info(path: str) -> dict[str, Any]:
    """Detect language, framework, dependencies and git status for *path*."""
    logger.info("get_project_info: %s", path)

    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": reason}

    try:
        project = await asyncio.to_thread(lambda: Path(path).expanduser().resolve())
        if not await asyncio.to_thread(project.exists):
            return {"error": f"Path not found: {path}"}

        language = await _detect_language(project)
        framework = await _detect_framework(project, language)
        dependencies = await _get_dependencies(project, language)

        git_info: dict[str, Any] = {"is_repo": False}
        if await _is_git_repo(project):
            try:
                branch_proc = await asyncio.create_subprocess_exec(
                    "git", "rev-parse", "--abbrev-ref", "HEAD",
                    cwd=str(project),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                branch_stdout, _ = await asyncio.wait_for(branch_proc.communicate(), timeout=10)
                branch = branch_stdout.decode("utf-8", errors="replace").strip()

                remote_proc = await asyncio.create_subprocess_exec(
                    "git", "remote", "get-url", "origin",
                    cwd=str(project),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                remote_stdout, _ = await asyncio.wait_for(remote_proc.communicate(), timeout=10)
                remote = remote_stdout.decode("utf-8", errors="replace").strip()

                git_info = {"is_repo": True, "branch": branch, "remote": remote}
            except Exception:
                git_info = {"is_repo": True, "branch": "unknown", "remote": None}

        file_count = 0
        dir_count = 0
        try:
            entries = await asyncio.to_thread(lambda: list(project.rglob("*")))
            for e in entries:
                if await asyncio.to_thread(e.is_file):
                    file_count += 1
                elif await asyncio.to_thread(e.is_dir):
                    dir_count += 1
        except (PermissionError, FileNotFoundError, OSError):
            pass

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
        result = await asyncio.to_thread(
            subprocess.run,
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
            result = await asyncio.to_thread(
                subprocess.run,
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
            result = await asyncio.to_thread(
                subprocess.run,
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
                await asyncio.to_thread(
                    subprocess.run,
                    ["taskkill", "/PID", str(pid), "/F"],
                    check=True,
                    timeout=10,
                )
            else:
                await asyncio.to_thread(
                    subprocess.run,
                    ["kill", "-9", str(pid)],
                    check=True,
                    timeout=10,
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
            file_paths = await asyncio.to_thread(lambda: list(root.rglob(glob)))
            for file_path in file_paths:
                if not await asyncio.to_thread(file_path.is_file):
                    continue
                ok, _size, _err = _check_file_size_limit(file_path)
                if not ok:
                    continue
                try:
                    content = await asyncio.to_thread(file_path.read_text, encoding="utf-8", errors="ignore")
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
                "max_depth": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum recursion depth",
                },
                "max_results": {
                    "type": "integer",
                    "default": 100,
                    "description": "Maximum number of projects to return",
                },
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
