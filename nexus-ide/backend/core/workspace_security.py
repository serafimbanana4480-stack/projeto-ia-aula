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
from functools import lru_cache
from pathlib import Path, PureWindowsPath
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

# Dangerous commands that must be matched as a WHOLE WORD.
#
# ``dd`` used to live in ``_BLOCKED_COMMAND_PATTERNS`` as the substring
# ``"dd "``, which also matched the trailing ``"dd "`` of ``git add .``,
# ``npm add lodash`` and ``yarn add lodash`` — three perfectly ordinary
# commands.  A substring match cannot tell "the dd utility" from "the last
# two letters of add", so these patterns are tokenised instead.
_BLOCKED_COMMAND_WORDS: set[str] = {"dd"}

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


@lru_cache(maxsize=1)
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
    except Exception as exc:
        logger.warning("Could not resolve current working directory: %s", exc)
    try:
        paths.add(Path(tempfile.gettempdir()).resolve())
    except Exception as exc:
        logger.warning("Could not resolve temp directory: %s", exc)
    return list(paths)


@lru_cache(maxsize=256)
def _resolved_blocked_system_path(path: str) -> Path:
    """Resolve stable blocklist entries once instead of once per file check."""
    return Path(path).resolve() if ":" not in path else Path(path)


def _normalised_path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _path_key_is_within(path_key: str, base: Path | str) -> bool:
    """Fast boundary-aware containment check for a normalised path key."""
    base_key = base if isinstance(base, str) else _normalised_path_key(base)
    return path_key == base_key or path_key.startswith(base_key.rstrip("\\/") + os.sep)


@lru_cache(maxsize=16)
def _blocked_path_entries(blocked_paths: tuple[str, ...]) -> tuple[tuple[Path, str], ...]:
    return tuple(
        (resolved, _normalised_path_key(resolved))
        for resolved in (_resolved_blocked_system_path(path) for path in blocked_paths)
    )


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

    # Windows-style absolute paths (e.g. "C:\Windows\System32") must be
    # checked with PureWindowsPath semantics *regardless of the host OS*.
    # A POSIX pathlib.Path treats backslashes as ordinary filename
    # characters (not separators), so on Linux/Mac hosts (Docker, CI, a
    # WSL-hosted backend, ...) "C:\Windows" would otherwise be silently
    # glued onto the current working directory as a harmless-looking
    # relative subpath and slip straight past the prefix check below —
    # even though the identical string is correctly recognised as the
    # Windows system root when this same process runs natively on Windows.
    # Agents supply paths as plain strings, so the guard must not depend on
    # the host OS to interpret them safely.
    if re.match(r"^[A-Za-z]:[\\/]", path):
        win_path = PureWindowsPath(path)
        for blocked in _BLOCKED_SYSTEM_PATHS:
            if ":" not in blocked:
                continue  # POSIX-style entry, not a Windows drive path
            try:
                win_path.relative_to(PureWindowsPath(blocked))
                return True, f"Access to system path '{blocked}' is blocked"
            except ValueError:
                continue

    try:
        raw = Path(path).expanduser()
    except (OSError, ValueError) as exc:
        return True, f"Invalid path: {exc}"

    # Explicit ``..`` traversal check before resolution so that symlinks
    # cannot be used to smuggle traversal past ``resolve()``.
    if ".." in raw.parts:
        return True, "Path traversal ('..') is not allowed"

    # Block Windows drive-relative paths (e.g. C:Windows\System32). These
    # are treated as relative by pathlib on every host OS (not just
    # Windows) but resolve to absolute system paths once combined with a
    # working directory, so this must run unconditionally rather than only
    # when this process itself happens to run on Windows.
    if re.search(r"^[A-Za-z]:[^/\\]", str(raw)):
        return True, "Windows drive-relative paths are not allowed"

    try:
        resolved = raw.resolve()
    except (OSError, ValueError) as exc:
        return True, f"Invalid path: {exc}"
    resolved_key = _normalised_path_key(resolved)

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
    blocked_paths = tuple(sorted(_BLOCKED_SYSTEM_PATHS, key=len, reverse=True))
    for bpath, blocked_key in _blocked_path_entries(blocked_paths):
        if _path_key_is_within(resolved_key, blocked_key):
            return True, f"Access to system path '{bpath}' is blocked"

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
        if _path_key_is_within(resolved_key, allowed):
            return False, ""

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
    # Read-only PowerShell cmdlets.
    #
    # The host is Windows and the agent system prompt explicitly tells the
    # model so ("This host is Windows with PowerShell", agents/base.py). Until
    # this entry existed the prompt steered the model straight into commands
    # the whitelist then rejected — session bf1e9435b9ec47c9 lost three
    # iterations and tripped the circuit breaker on nothing worse than
    # ``Get-ChildItem`` and ``Get-Location``.
    #
    # Only non-mutating verbs are listed. Anything that writes (Set-*, New-*,
    # Remove-*, Start-*, Stop-*, Invoke-*) is deliberately absent, and the
    # pattern blacklist plus the ``;``/``&&``/redirection rejection in
    # ``_validate_shell_command`` still apply to every segment.
    "get-childitem",
    "get-content",
    "get-location",
    "get-item",
    "get-itemproperty",
    "get-command",
    "get-date",
    "get-host",
    "get-member",
    "get-process",
    "select-object",
    "select-string",
    "where-object",
    "foreach-object",
    "sort-object",
    "measure-object",
    "format-list",
    "format-table",
    "out-string",
    "test-path",
    "resolve-path",
    "split-path",
    "join-path",
    "compare-object",
    "convertto-json",
    "convertfrom-json",
    "write-output",
    "write-host",
    # Common PowerShell aliases for the same read-only operations.
    "gci",
    "gc",
    "gl",
    "gi",
    "gcm",
    "gps",
    "sls",
    "ft",
    "fl",
}

# cmd.exe builtins that are not standalone executables on Windows.
_WIN_CMD_INTERNALS: frozenset[str] = frozenset(
    {"echo", "dir", "type", "cd", "md", "rd", "copy", "move", "cls", "tree"}
)

_GIT_BLOCKED_SUBCOMMANDS: set[str] = {"push", "reset", "clean", "rebase", "cherry-pick"}
_GIT_BLOCKED_FLAGS: set[str] = {"--force", "--hard", "-f", "-D", "--delete"}

# Git subcommands that only READ repository state.  The shell tool is the
# "safe command" path, so it must not be able to mutate the repository, the
# index or the remote; mutating git work goes through the dedicated git
# tools, which apply their own confirmation policy.
_GIT_READONLY_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "status",
        "log",
        "diff",
        "show",
        "blame",
        "describe",
        "ls-files",
        "rev-parse",
        "shortlog",
    }
)

# Subcommands that are read-only only in an explicit read-only form:
# ``git branch --list`` lists, ``git branch -d`` deletes, ``git tag`` lists
# but ``git tag v1`` creates, ``git remote`` lists but ``git remote add``
# registers a new remote.
_GIT_READONLY_FLAG_SUBCOMMANDS: dict[str, frozenset[str]] = {
    "branch": frozenset(
        {
            "--list",
            "-l",
            "-a",
            "-r",
            "--all",
            "--remotes",
            "--show-current",
            "-v",
            "--verbose",
        }
    ),
    "remote": frozenset({"-v", "--verbose"}),
    "tag": frozenset({"--list", "-l"}),
}

# Global git options that either execute code or change the configuration
# git itself evaluates.  ``git -c alias.pwn=!<cmd> pwn`` runs an arbitrary
# shell command through an alias, which is the classic way of smuggling
# command execution through a "safe" git command.
_GIT_BLOCKED_GLOBAL_OPTIONS: frozenset[str] = frozenset(
    {
        "-c",
        "--config-env",
        "--exec-path",
        "--ext-diff",
        "--textconv",
        "--upload-pack",
        "--receive-pack",
    }
)

# Global options that consume the following argument (the argument is a
# value, not the subcommand).
_GIT_VALUE_OPTIONS: frozenset[str] = frozenset(
    {
        "-C",
        "--git-dir",
        "--work-tree",
        "--namespace",
        "--super-prefix",
        "--config-env",
        "--exec-path",
    }
)

# Global options that take no value.
_GIT_FLAG_OPTIONS: frozenset[str] = frozenset(
    {
        "--no-pager",
        "-p",
        "--paginate",
        "--bare",
        "--literal-pathspecs",
        "--no-replace-objects",
        "--no-optional-locks",
        "--no-advice",
        "--no-lazy-fetch",
        "--html-path",
        "--man-path",
        "--info-path",
        "--version",
        "--help",
        "-h",
    }
)

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

# Members of ``os`` that must never be reached — neither as ``os.system``
# nor as a bare ``system`` bound by ``from os import system``.
_BLOCKED_OS_MEMBERS: frozenset[str] = frozenset(
    {
        "system",
        "popen",
        "fork",
        "forkpty",
        "kill",
        "killpg",
        "remove",
        "unlink",
        "rename",
        "renames",
        "rmdir",
        "removedirs",
        "environ",
        "putenv",
        "unsetenv",
        "startfile",
        "truncate",
    }
)

# Members of ``shutil`` that copy or destroy whole data trees.
_BLOCKED_SHUTIL_MEMBERS: frozenset[str] = frozenset({"rmtree", "move"})

# Modules that must not be star-imported: ``from os import *`` binds every
# dangerous name at once and defeats any name-based check.
_BLOCKED_STAR_IMPORT_MODULES: frozenset[str] = frozenset(
    {"os", "shutil", "subprocess", "importlib", "ctypes", "pty", "socket", "urllib"}
)


def _fix_windows_path_literals(code: str) -> str:
    """Rewrite bare Windows drive-path string literals to raw strings."""
    pattern = re.compile(
        r'''(?P<prefix>^|[=\(\[\{,\s])'''
        r'''(?P<quote>["'])'''
        r'''(?P<path>[A-Za-z]:\\(?:[^'"\\]|\\.)*)'''
        r'''(?P=quote)''',
        re.MULTILINE,
    )

    def _repl(match: re.Match[str]) -> str:
        return (
            f"{match.group('prefix')}r{match.group('quote')}"
            f"{match.group('path')}{match.group('quote')}"
        )

    return pattern.sub(_repl, code)


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


def _resolve_path_expr(node: ast.expr) -> Path | None:
    """Resolve an AST expression to a filesystem path when it is a literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return Path(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve_path_expr(node.left)
        right = _resolve_path_expr(node.right)
        if left is not None and right is not None:
            return Path(f"{left}{right}")
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                return None
        return Path("".join(parts))
    return None


def _is_blocked_module_member(module: str, member: str) -> bool:
    """Return ``True`` when ``module.member`` must not be used in sandbox mode.

    The decision is made on the SYMBOL, never on the call syntax: ``system``
    reached through ``from os import system`` is exactly as dangerous as
    ``os.system``.
    """
    if module == "os":
        # ``exec*`` / ``spawn*`` cover the whole family of process-replacing
        # helpers, including ones added by newer CPython releases.
        if member.startswith("exec") or member.startswith("spawn"):
            return True
        return member in _BLOCKED_OS_MEMBERS
    if module == "shutil":
        return member in _BLOCKED_SHUTIL_MEMBERS or member.startswith("copy")
    if module == "importlib":
        return member == "import_module"
    return module == "subprocess"


def _collect_import_bindings(tree: ast.AST) -> tuple[dict[str, str], dict[str, str]]:
    """Collect the names bound by the imports of *tree*.

    Returns ``(module_aliases, symbol_aliases)``:

    * *module_aliases* maps a local name to the module it refers to
      (``import os as o`` -> ``{"o": "os"}``);
    * *symbol_aliases* maps a local name to the fully qualified symbol it
      refers to (``from os import system`` -> ``{"system": "os.system"}``).
    """
    module_aliases: dict[str, str] = {}
    symbol_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                module_aliases[bound] = alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name
                symbol_aliases[bound] = f"{module}.{alias.name}"
    return module_aliases, symbol_aliases


def _resolve_module_expr(node: ast.expr, module_aliases: dict[str, str]) -> str | None:
    """Return the module an expression refers to, when it can be resolved.

    Handles a plain imported name (``os``), an aliased import (``o`` for
    ``import os as o``) and the two dynamic import helpers
    (``__import__("os")`` / ``importlib.import_module("os")``).
    """
    if isinstance(node, ast.Name):
        return module_aliases.get(node.id)
    if isinstance(node, ast.Call):
        func = node.func
        is_import = isinstance(func, ast.Name) and func.id == "__import__"
        is_import_module = isinstance(func, ast.Attribute) and func.attr == "import_module"
        if (is_import or is_import_module) and node.args:
            resolved = _resolve_string_arg(node.args[0])
            if resolved:
                return resolved.split(".")[0]
    return None


def _sandbox_root(project_root: str | None) -> Path:
    """Return the directory model-supplied code is allowed to write to."""
    if project_root:
        try:
            return Path(project_root).expanduser().resolve()
        except (OSError, ValueError):
            pass
    try:
        return Path.cwd().resolve()
    except (OSError, ValueError):  # pragma: no cover - deleted cwd
        return Path(".").resolve()


def _open_write_escape_reason(node: ast.Call, root: Path) -> str:
    """Return a rejection reason when ``open(...)`` writes outside *root*.

    Only write modes (``w``/``a``/``x``/``+``) are considered: reading a file
    outside the project is handled by the path validators, while *writing*
    one is how a sandboxed script plants a payload.
    """
    if not node.args:
        return ""
    target = _resolve_path_expr(node.args[0])
    if target is None:
        return ""
    mode: str | None = None
    if len(node.args) > 1:
        mode = _resolve_string_arg(node.args[1])
    else:
        for keyword in node.keywords:
            if keyword.arg == "mode":
                mode = _resolve_string_arg(keyword.value)
    if not mode or not any(ch in mode for ch in ("w", "a", "x", "+")):
        return ""
    try:
        resolved = target.expanduser()
        if not resolved.is_absolute():
            resolved = root / resolved
        resolved = resolved.resolve()
    except (OSError, ValueError):
        return ""
    try:
        resolved.relative_to(root)
    except ValueError:
        return (
            f"open('{target}', '{mode}') writes outside the project root "
            "and is blocked in sandbox mode"
        )
    return ""


def _check_python_sandbox(
    code: str, project_root: str | None = None
) -> tuple[bool, str]:
    """Scan Python code for dangerous imports / operations using AST.

    Regex-based scanning is easily bypassed via encoding tricks, dynamic
    imports, string concatenation, etc.  AST parsing gives us a reliable
    view of every import and dangerous call in the code.

    The check resolves the SYMBOL and not the call syntax.  ``from os import
    system`` binds the bare name ``system``, which looks nothing like the
    attribute access ``os.system`` — a purely syntactic check therefore never
    fired while the code still ran with the full privileges of the backend
    process.

    Args:
        code: Source code to inspect.
        project_root: Directory the code may write to.  Defaults to the
            current working directory.

    Returns:
        ``(is_safe, reason)`` — *reason* is empty when the code is safe.
    """
    parse_candidates = (code,)
    if "\\" in code:
        parse_candidates = (code, _fix_windows_path_literals(code))
    tree = None
    last_exc: SyntaxError | None = None
    for candidate in parse_candidates:
        try:
            tree = ast.parse(candidate)
            break
        except SyntaxError as exc:
            last_exc = exc
    if tree is None:
        message = str(last_exc) if last_exc else "unknown syntax error"
        if "unicodeescape" in message.lower():
            return (
                False,
                "Invalid Python syntax: Windows paths in strings must use raw "
                "strings (r'C:\\\\Users\\\\...') or forward slashes",
            )
        return False, f"Invalid Python syntax: {last_exc}"

    module_aliases, symbol_aliases = _collect_import_bindings(tree)
    root = _sandbox_root(project_root)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name.split(".")[0]
                if base in _BLOCKED_IMPORTS:
                    return False, f"import {alias.name} is blocked in sandbox mode"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            base = module.split(".")[0]
            if base in _BLOCKED_IMPORTS:
                return False, f"from {node.module} import is blocked in sandbox mode"
            for alias in node.names:
                if alias.name == "*":
                    if base in _BLOCKED_STAR_IMPORT_MODULES:
                        return False, (
                            f"from {module} import * is blocked in sandbox mode"
                        )
                    continue
                # ``from os import system`` binds the bare name ``system``:
                # the import itself has to be refused, otherwise the call
                # looks like an ordinary local function.
                if _is_blocked_module_member(base, alias.name):
                    return False, (
                        f"from {module} import {alias.name} is blocked in sandbox mode"
                    )

        if isinstance(node, ast.Call):
            # Block __import__ with dangerous modules — reject dynamic args
            if isinstance(node.func, ast.Name) and node.func.id == "__import__" and node.args:
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
                    return (
                        False,
                        "importlib.import_module with dynamic argument is blocked in sandbox mode",
                    )
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
                if resolved and resolved.lower() in (
                    "eval",
                    "exec",
                    "compile",
                    "__import__",
                    "import_module",
                ):
                    return False, f"getattr targeting '{resolved}' is blocked in sandbox mode"
                # getattr(os, "system") is just another spelling of os.system.
                if resolved:
                    target_module = _resolve_module_expr(node.args[0], module_aliases)
                    if target_module and _is_blocked_module_member(target_module, resolved):
                        return False, (
                            f"getattr({target_module}, '{resolved}') is blocked in sandbox mode"
                        )

            # Block eval, exec, compile
            if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec", "compile"):
                return False, f"{node.func.id}() is blocked in sandbox mode"

            # Block a dangerous member reached through a bound name
            # (``from os import system`` -> ``system(...)``).
            if isinstance(node.func, ast.Name):
                symbol = symbol_aliases.get(node.func.id)
                if symbol:
                    symbol_module, _, symbol_member = symbol.partition(".")
                    if _is_blocked_module_member(symbol_module, symbol_member):
                        return False, (
                            f"{node.func.id}() (bound from {symbol_module}) "
                            "is blocked in sandbox mode"
                        )
            # Block os.system, os.popen, os.exec*, shutil.rmtree, ...
            elif isinstance(node.func, ast.Attribute):
                module = _resolve_module_expr(node.func.value, module_aliases)
                if module is None:
                    base_name = (
                        node.func.value.id if isinstance(node.func.value, ast.Name) else None
                    )
                    if base_name in _DANGEROUS_MODULES:
                        module = base_name
                if module and _is_blocked_module_member(module, node.func.attr):
                    return (
                        False,
                        f"{module}.{node.func.attr}() is blocked in sandbox mode",
                    )

            # Block open(..., "w"/"a"/"x") that targets a path outside the
            # project root.
            if isinstance(node.func, ast.Name) and node.func.id == "open":
                reason = _open_write_escape_reason(node, root)
                if reason:
                    return False, reason

            # Block access to __builtins__ via attribute (e.g. __builtins__['eval'])
            if (
                isinstance(node.func, ast.Subscript)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "__builtins__"
            ):
                return False, "__builtins__ access is blocked in sandbox mode"

        elif isinstance(node, ast.Attribute):
            # Attribute access that is not a call: ``os.environ`` reads the
            # whole environment, ``x = os.system`` smuggles the callable out.
            module = _resolve_module_expr(node.value, module_aliases)
            if module is None:
                base_name = node.value.id if isinstance(node.value, ast.Name) else None
                if base_name in _DANGEROUS_MODULES:
                    module = base_name
            if module and _is_blocked_module_member(module, node.attr):
                return False, f"{module}.{node.attr} is blocked in sandbox mode"

    return True, ""


# ---------------------------------------------------------------------------
# Environment scrubbing for model-supplied code
# ---------------------------------------------------------------------------

# Variables that may cross the process boundary into model-supplied code.
# Everything else is dropped, so an API key held by the server process can
# never be read back by the code the model wrote.
_PYTHON_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "HOME",
        "LANG",
        "PYTHONIOENCODING",
        "PYTHONHASHSEED",
    }
)

# Name fragments that mark a variable as credential-bearing.
_CREDENTIAL_NAME_MARKERS: tuple[str, ...] = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "AUTH",
    "PRIVATE",
)


def _looks_like_credential(name: str) -> bool:
    """Return ``True`` when the variable *name* looks credential-bearing."""
    upper = name.upper()
    return any(marker in upper for marker in _CREDENTIAL_NAME_MARKERS)


def _python_child_environment() -> dict[str, str]:
    """Build a minimal environment for model-supplied Python code.

    The server process environment holds provider API keys, signing secrets
    and database credentials.  Handing it over to code the model wrote
    leaks every one of them (``print(os.environ)`` was enough to read
    ``OPENROUTER_API_KEY`` and friends), so the child only receives an
    explicit allow-list plus the non-secret ``NEXUS_*`` settings, and every
    credential-shaped variable is dropped.
    """
    child: dict[str, str] = {}
    for name, value in os.environ.items():
        if _looks_like_credential(name):
            continue
        upper = name.upper()
        if upper in _PYTHON_ENV_ALLOWLIST or upper.startswith("NEXUS_"):
            child[name] = value
    return child



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

# A line break is a command separator for cmd.exe / sh just like ``;`` is, so an
# embedded newline must never survive into ``Popen(..., shell=True)`` (which
# receives the original string, not the shlex tokenisation).
_LINE_BREAK_CHARS = ("\n", "\r", "\x0b", "\x0c")

# ``&`` is backgrounding on POSIX and command chaining on cmd.exe, and nothing in
# this allowlist legitimately needs a bare ``&`` as a shell *word*, so it is
# blocked on every platform (it used to be Windows-only, which let
# ``ls & whoami`` through on Linux/macOS).  ``&&`` is a separate, longer entry:
# it is still matched first when both are present, so chaining is reported the
# same way it always was.
_DISALLOWED_METACHARACTERS_BASE = (
    ";",
    "&&",
    "||",
    "`",
    "$(",
    ">>",
    ">",
    "<",
    "&",
) + _LINE_BREAK_CHARS
if sys.platform.startswith("win"):
    # ``^`` is cmd.exe's escape character: it strips the meaning of the next
    # character, so it can only ever be used to smuggle one past this list.
    _DISALLOWED_METACHARACTERS = _DISALLOWED_METACHARACTERS_BASE + ("^",)
else:
    _DISALLOWED_METACHARACTERS = _DISALLOWED_METACHARACTERS_BASE


def _contains_line_break(command: str) -> bool:
    """Return ``True`` if *command* embeds a line break anywhere.

    Unlike the other metacharacters this inspects the raw string: a newline
    inside quotes is still a separator for the real shell, so quoting is not a
    way to smuggle one past the allowlist.
    """
    return any(br in command for br in _LINE_BREAK_CHARS)


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
    return any(op in cleaned for op in _DISALLOWED_METACHARACTERS)


def _split_on_separators(command: str) -> list[str]:
    """Split *command* on unquoted ``|`` / ``&`` and on line breaks.

    Line breaks split unconditionally (quoting cannot hide a separator from the
    shell) so every resulting segment is validated on its own.  ``&`` splits
    only when unquoted, exactly like ``|``, so a quoted ``&`` stays data while
    a backgrounding/chaining ``&`` is broken into two independently validated
    segments.
    """
    segments: list[str] = []
    current: list[str] = []
    in_double = False
    in_single = False
    for ch in command:
        if ch in _LINE_BREAK_CHARS:
            segments.append("".join(current))
            current = []
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "'" and not in_double:
            in_single = not in_single
        elif ch in "|&" and not in_double and not in_single:
            segments.append("".join(current))
            current = []
            continue
        current.append(ch)
    segments.append("".join(current))
    return [s.strip() for s in segments if s.strip()]


def _validate_git_invocation(tokens: list[str], command: str) -> tuple[bool, str]:
    """Validate a ``git`` invocation against a read-only allow-list.

    ``git`` is on the command allow-list, so anything it accepts is reachable
    by the model.  That includes ``git -c alias.pwn=!<cmd> pwn``, which runs
    an arbitrary shell command through an alias: the command is a *git*
    command, but it executes whatever the alias expands to.

    Args:
        tokens: The tokenised command (``tokens[0]`` is ``git``).
        command: The raw command string.

    Returns:
        ``(is_safe, reason)`` — *reason* is empty when the command is safe.
    """
    # A ``!`` inside a git invocation is the marker of a shell alias
    # (``alias.pwn=!cmd``); git expands it in the caller's shell.
    if "!" in command:
        return False, "Git commands containing '!' (alias expansion) are blocked for safety"

    args = tokens[1:]
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in _GIT_BLOCKED_GLOBAL_OPTIONS or arg.startswith(
            ("--exec-path=", "--config-env=")
        ):
            return False, f"Git option '{arg}' is blocked for safety"
        if arg in _GIT_VALUE_OPTIONS:
            index += 2
            continue
        if arg in _GIT_FLAG_OPTIONS:
            index += 1
            continue
        if arg.startswith("-"):
            # Unknown global option: refuse rather than guess what it does.
            return False, f"Git option '{arg}' is blocked for safety"
        break
    else:
        # No subcommand at all ("git", "git --version"): nothing to run.
        return True, ""

    subcmd = args[index].lower()
    rest = args[index + 1 :]

    if subcmd in _GIT_READONLY_SUBCOMMANDS:
        return True, ""

    allowed_flags = _GIT_READONLY_FLAG_SUBCOMMANDS.get(subcmd)
    if allowed_flags is not None:
        if all(flag in allowed_flags for flag in rest):
            return True, ""
        return False, (
            f"Git subcommand '{subcmd}' is blocked for safety "
            "(only its read-only form is allowed)"
        )

    return False, (
        f"Git subcommand '{subcmd}' is blocked for safety "
        "(not in the read-only allow-list)"
    )


def _validate_single_command(command: str) -> tuple[bool, str]:
    """Validate one shell segment (no pipes, no chaining)."""
    # Defence in depth: this helper is the last gate before a segment is handed
    # to the shell, so it must never accept a string that still carries a
    # separator.  The git branch below returns early without inspecting the
    # remaining tokens, which is exactly where an injected ``\n whoami`` would
    # otherwise slip through.
    unquoted = _remove_quoted_parts(command)
    if _contains_line_break(command) or "|" in unquoted or "&" in unquoted:
        return False, "Command separators (|, &, line breaks) are not allowed in a single command"

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
            for flag in _GIT_BLOCKED_FLAGS:
                # Token based: a substring match would flag ``--follow`` and
                # ``--format`` because they contain "-f".
                if any(tok == flag or tok.startswith(f"{flag}=") for tok in tokens[1:]):
                    return False, f"Git flag '{flag}' is blocked for safety"
            return _validate_git_invocation(tokens, command)
        return True, ""

    # Block inline code execution flags that enable arbitrary code execution
    if base_cmd in ("python", "python3", "py") and any(t == "-c" for t in tokens[1:]):
        return False, f"{base_cmd} -c (inline code execution) is blocked for safety"
    if base_cmd == "node" and any(t == "-e" for t in tokens[1:]):
        return False, "node -e (inline code execution) is blocked for safety"
    if base_cmd in ("bash", "sh", "zsh", "fish") and any(t == "-c" for t in tokens[1:]):
        return False, f"{base_cmd} -c (inline code execution) is blocked for safety"

    if base_cmd not in _SHELL_WHITELIST:
        return False, f"Command '{base_cmd}' is not in the safe command whitelist"

    return True, ""


def _validate_shell_command(command: str) -> tuple[bool, str]:
    """Validate a shell command against blacklist and whitelist.

    Every segment produced by ``|`` or an unquoted ``&`` is validated
    individually.  Commands containing ``;``, ``&&``, ``||``, ``&``, backticks,
    ``$()``, redirections or an embedded line break are rejected outright.
    """
    if not command or not command.strip():
        return False, "Empty command"

    cmd_str = command.strip()
    cmd_lower = cmd_str.lower()

    # Blocked dangerous patterns (whole command)
    for pattern in _BLOCKED_COMMAND_PATTERNS:
        if pattern.lower() in cmd_lower:
            return False, f"Dangerous pattern '{pattern}' is blocked"

    # Blocked dangerous commands matched as a WHOLE WORD.  A substring match
    # on "dd " also matched "git add .", "npm add lodash" and "yarn add
    # lodash", which are perfectly ordinary commands.
    for word in _BLOCKED_COMMAND_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", cmd_lower):
            return False, f"Dangerous pattern '{word}' is blocked"

    # Blocked system paths in command string
    for blocked_path in _BLOCKED_SYSTEM_PATHS:
        if blocked_path.lower() in cmd_lower:
            return False, f"Access to system path '{blocked_path}' is blocked"

    # Reject an embedded line break outright: cmd.exe / sh treat it as a command
    # separator, so the original string that reaches Popen(shell=True) would run
    # more than the segment we validated.
    if _contains_line_break(cmd_str):
        return False, "Embedded line breaks are not allowed in a command"

    # Reject shell metacharacters that allow command chaining / substitution
    if _has_unquoted_metacharacters(cmd_str):
        return False, "Shell metacharacters (;, &, &&, ||, `, $(), >, <, >>) are not allowed"

    # Split on pipes, unquoted ampersands and line breaks, then validate every segment
    segments = _split_on_separators(cmd_str)
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


def argv_for_validated_shell_command(command: str) -> list[str]:
    """Build ``Popen`` argv for a command that passed ``_validate_shell_command``.

    Callers must validate first. Pipelines use a single ``cmd.exe /c`` on Windows
    (metacharacters already rejected) or a POSIX pipeline executed in
    :func:`backend.core.workspace_shell.execute_shell`.
    """
    cmd_str = command.strip()
    segments = _split_on_separators(cmd_str)
    if not segments:
        raise ValueError("empty command")
    if len(segments) == 1:
        segment = segments[0]
        if os.name == "nt":
            try:
                base = Path(shlex.split(segment)[0]).stem.lower()
            except (ValueError, IndexError):
                base = segment.strip().split()[0].lower()
            if base in _WIN_CMD_INTERNALS:
                return ["cmd.exe", "/d", "/s", "/c", segment]
        try:
            return shlex.split(segment)
        except ValueError:
            parts = segment.strip().split()
            if not parts:
                raise ValueError("empty command") from None
            return parts
    if os.name == "nt":
        return ["cmd.exe", "/d", "/s", "/c", cmd_str]
    raise ValueError("posix pipeline")


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
    return any(host in url_lower for host in _SAFE_GIT_HOSTS)


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
    except (OSError, ValueError) as exc:
        logger.debug("Symlink resolution skipped: %s", exc)

    try:
        target.relative_to(project)
        return True, ""
    except ValueError:
        return False, f"Path {target} is outside project root {project}"
