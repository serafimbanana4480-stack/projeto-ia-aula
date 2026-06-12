"""Security validation for workspace operations.

Contains path validation, shell-command validation, Python sandbox checks,
and authentication helpers used by the other workspace modules.
"""

from __future__ import annotations

import ast
import logging
import os
import re
import shlex
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# File-size limit
# ---------------------------------------------------------------------------

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
    "C:\\Windows",
    "C:\\Windows\\System32",
    "C:\\Windows\\SysWOW64",
    "C:\\Windows\\System",
    "C:\\ProgramData",
    "C:\\ProgramData\\Microsoft\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
    "/Windows",
    "/ProgramData",
    "/Program Files",
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
    ".env.development",
    ".env.test",
    ".env.*",
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
    session_id: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Log a workspace operation to the audit database.

    ``duration_ms`` is recorded when supplied so callers can measure real
    elapsed time.  If omitted it defaults to ``0`` for backward compatibility.
    """
    try:
        from backend.persistence.db import log_tool_execution

        log_tool_execution(
            session_id=session_id,
            tool_name=tool_name,
            args=args,
            result=result,
            success="error" not in result,
            error=result.get("error"),
            duration_ms=duration_ms if duration_ms is not None else 0,
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
    # Null-byte injection check
    if "\x00" in path:
        return True, "Null bytes in path are not allowed"

    try:
        raw = Path(path).expanduser()
    except (OSError, ValueError) as exc:
        return True, f"Invalid path: {exc}"

    # Explicit ``..`` traversal check before resolution so that symlinks
    # cannot be used to smuggle traversal past ``resolve()``.
    if ".." in raw.parts:
        return True, "Path traversal ('..') is not allowed"

    # Block Windows drive-relative paths (e.g. C:Windows\System32)
    # These are treated as relative by pathlib but resolve to absolute system paths.
    if platform.system() == "Windows":
        import re as _re
        if _re.search(r"^[A-Za-z]:[^/\\]", str(raw)):
            return True, "Windows drive-relative paths are not allowed"

    try:
        resolved = raw.resolve()
    except (OSError, ValueError) as exc:
        return True, f"Invalid path: {exc}"

    # Symlink check — if realpath differs from resolved path, the path
    # contains a symlink that may point outside allowed bases.
    try:
        real = Path(os.path.realpath(str(raw)))
        if real != resolved:
            # The symlink points somewhere else; validate the real target too
            for allowed in _get_allowed_base_paths():
                try:
                    real.relative_to(allowed)
                    break
                except ValueError:
                    continue
            else:
                return True, "Symlinks pointing outside allowed directories are not permitted"
    except (OSError, ValueError):
        pass  # If we can't verify, continue with normal checks

    # 1. Blocked system paths (prefix matching) — checked FIRST so blocked
    #    always wins even when the path is inside an allowed base.
    # Longer paths are checked first so the most specific match wins.
    for blocked in sorted(_BLOCKED_SYSTEM_PATHS, key=len, reverse=True):
        bpath = Path(blocked).resolve() if ":" not in blocked else Path(blocked)
        try:
            resolved.relative_to(bpath)
            return True, f"Access to system path '{bpath}' is blocked"
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
    parts_lower = [p.lower() for p in resolved.parts]
    for sensitive in _BLOCKED_SENSITIVE_PATHS:
        # Single-component entries (including wildcard .env.*) are handled by
        # checking individual path parts.
        if "/" not in sensitive:
            if sensitive == ".env.*":
                for part in parts_lower:
                    if part.startswith(".env.") and len(part) > len(".env."):
                        return True, "Access to sensitive env file is blocked"
                continue
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
    # Basic navigation & listing
    "ls",
    "dir",
    "pwd",
    "cd",
    "clear",
    "cls",
    "tree",
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

# Modules whose imports are blocked entirely
_BLOCKED_IMPORTS: set[str] = {
    "subprocess",
    "socket",
    "urllib",
    "urllib.request",
    "ctypes",
    "pty",
}

# Modules whose dangerous methods are blocked (import is allowed, but risky calls are not)
_DANGEROUS_MODULES: set[str] = {
    "os",
    "subprocess",
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

    def _resolve_string_arg(node: ast.expr) -> str | None:
        """Resolve an AST expression to a string constant if possible.
        Returns the resolved string for simple literals and concatenations,
        or None for dynamic expressions that cannot be safely resolved.
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = _resolve_string_arg(node.left)
            right = _resolve_string_arg(node.right)
            if left is not None and right is not None:
                return left + right
        # Cannot safely resolve dynamic expressions (calls, variables, etc.)
        return None

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    base = alias.name.split(".")[0]
                    if base in _BLOCKED_IMPORTS:
                        return False, f"import {alias.name} is blocked in sandbox mode"
            elif isinstance(node, ast.ImportFrom):
                base = (node.module or "").split(".")[0]
                if base in _BLOCKED_IMPORTS:
                    return False, f"from {node.module} import is blocked in sandbox mode"

        if isinstance(node, ast.Call):
            # Block __import__ with dangerous modules — reject dynamic args
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
                and node.args
            ):
                resolved = _resolve_string_arg(node.args[0])
                if resolved is None:
                    return False, "__import__ with dynamic argument is blocked in sandbox mode"
                base = resolved.split(".")[0]
                if base in _BLOCKED_IMPORTS:
                    return False, f"__import__({resolved}) is blocked in sandbox mode"

            # Block importlib.import_module with dangerous modules — reject dynamic args
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "importlib"
                and node.func.attr == "import_module"
                and node.args
            ):
                resolved = _resolve_string_arg(node.args[0])
                if resolved is None:
                    return False, "importlib.import_module with dynamic argument is blocked in sandbox mode"
                base = resolved.split(".")[0]
                if base in _BLOCKED_IMPORTS:
                    return False, f"importlib.import_module({resolved}) is blocked in sandbox mode"

            # Block getattr that resolves to dangerous names (e.g. getattr(__builtins__, 'ex'+'ec'))
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
            ):
                resolved = _resolve_string_arg(node.args[1])
                if resolved and resolved.lower() in ("eval", "exec", "compile", "__import__", "import_module"):
                    return False, f"getattr targeting '{resolved}' is blocked in sandbox mode"

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

            # Block access to __builtins__ via attribute (e.g. __builtins__['eval'])
            if isinstance(node.func, ast.Subscript):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "__builtins__":
                    return False, "__builtins__ access is blocked in sandbox mode"

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

import platform

_DISALLOWED_METACHARACTERS_BASE = (";", "&&", "||", "`", "$(", ">>", ">", "<")
if sys.platform.startswith("win"):
    _DISALLOWED_METACHARACTERS = _DISALLOWED_METACHARACTERS_BASE + ("&", "^")
else:
    _DISALLOWED_METACHARACTERS = _DISALLOWED_METACHARACTERS_BASE


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


def _is_safe_git_remote(url: str) -> bool:
    """Return True if *url* points to a known-safe host."""
    url_lower = url.lower()
    for host in _SAFE_GIT_HOSTS:
        if host in url_lower:
            return True
    return False


def _is_allowed_path(path: str) -> bool:
    """Public helper: return True if *path* is inside an allowed base.

    This is the inverse of :func:`_is_blocked_path` but only checks allowed
    bases (not blocked system paths).  Useful for callers that already know
    the path is not sensitive/system and just want the implicit-deny check.
    """
    blocked, _ = _is_blocked_path(path)
    return not blocked


def _is_path_within_project(project_path: str, target_path: str) -> tuple[bool, str]:
    """Return whether *target_path* resolves safely under *project_path*.

    Resolves both paths, rejects traversal through ``..`` or symlinks that
    leave the project root, and returns a human-readable reason on failure.
    """
    try:
        project = Path(project_path).expanduser().resolve()
        raw = Path(target_path).expanduser()
    except (OSError, ValueError) as exc:
        return False, f"Invalid path: {exc}"

    if ".." in raw.parts:
        return False, "Path traversal ('..') is not allowed"

    try:
        target = raw.resolve()
    except (OSError, ValueError) as exc:
        return False, f"Invalid path: {exc}"

    # Reject symlinks that escape the project root
    try:
        real = Path(os.path.realpath(str(raw)))
        if real != target:
            try:
                real.relative_to(project)
            except ValueError:
                return False, "Symlinks pointing outside project root are not permitted"
    except (OSError, ValueError):
        pass

    try:
        target.relative_to(project)
        return True, ""
    except ValueError:
        return False, f"Path {target} is outside project root {project}"
