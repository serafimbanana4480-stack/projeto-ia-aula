"""Project file read/write with path-safety guards.

Blocked paths and extension allow-list from ARCHITECTURE.md §11.3.
This module is kept for legacy callers; new code should prefer the
richer :mod:`backend.tools.file_api` or :mod:`backend.core.workspace_fs`
APIs which support absolute paths, backups and metadata.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.core.workspace_security import _is_path_within_project

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    # Python / backend
    ".py",
    ".pyi",
    ".pyc",
    ".pyw",
    ".ipynb",
    # JavaScript / TypeScript
    ".ts",
    ".js",
    ".tsx",
    ".jsx",
    ".mjs",
    ".cjs",
    ".mts",
    ".cts",
    # Web
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".vue",
    ".svelte",
    # Java / JVM
    ".java",
    ".kt",
    ".kts",
    ".scala",
    ".clj",
    ".gradle",
    ".properties",
    # C / C++ / C# / .NET
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cc",
    ".cs",
    ".fs",
    ".fsx",
    ".vb",
    # Go / Rust / Ruby / PHP / Lua / etc.
    ".rs",
    ".go",
    ".rb",
    ".erb",
    ".php",
    ".pl",
    ".pm",
    ".lua",
    ".r",
    ".swift",
    # Mobile
    ".m",
    ".mm",
    # Shell / scripts
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".psm1",
    ".bat",
    ".cmd",
    # Config / data
    ".json",
    ".jsonc",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".ini",
    ".cfg",
    ".conf",
    ".config",
    ".lock",
    ".sum",
    ".mod",
    ".work",
    ".proto",
    ".graphql",
    ".prisma",
    # Markup / docs
    ".md",
    ".mdx",
    ".rst",
    ".txt",
    ".log",
    # Data
    ".csv",
    ".sql",
    ".sqlite",
    ".db",
    # Docker / infra
    ".dockerfile",
    ".env",
    ".gitignore",
    ".dockerignore",
    ".npmignore",
    ".editorconfig",
    ".gitattributes",
}
# Kept for backward compatibility with existing tests and callers.
# The validation now uses component-based matching (see below) to avoid
# false positives on legitimate paths that happen to contain these
# substrings (e.g. ``/home/user/my.ssh.project`` or ``/etcetera/file.txt``).
BLOCKED_PATH_PARTS = {"/etc", "/sys", "/proc", ".ssh", ".aws", "/root", "/var/run"}

# Component-level blocklist used for accurate path matching.
_BLOCKED_PATH_COMPONENTS = frozenset(
    part.strip("/").lower() for part in BLOCKED_PATH_PARTS
)


class UnsafePathError(ValueError):
    pass


def _validate(path: Path, project_path: Path | None = None) -> None:
    """Validate that a path is safe to read/write.

    Blocked paths are detected by checking individual path *components*
    (not substrings) against the blocklist.  This prevents false positives
    on legitimate directory or file names that happen to contain blocked
    substrings (e.g. ``my.ssh.project`` or ``etcetera``) while still
    blocking real system paths such as ``/etc/passwd``.

    When *project_path* is supplied, relative paths are also checked to
    ensure they do not escape the project root via ``..`` or symlinks.
    """
    resolved = path.expanduser().resolve()
    if project_path is not None:
        ok, reason = _is_path_within_project(str(project_path), str(resolved))
        if not ok:
            raise UnsafePathError(f"Blocked path: {resolved} — {reason}")

    # Component-based matching — substring checks are intentionally avoided
    # because they break valid paths like ``/home/user/etcetera/config.txt``.
    resolved_parts = {p.lower() for p in resolved.parts}
    raw_parts = {p.lower() for p in path.expanduser().parts}
    for component in _BLOCKED_PATH_COMPONENTS:
        if component in resolved_parts or component in raw_parts:
            raise UnsafePathError(f"Blocked path: {resolved}")
    if path.suffix and path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise UnsafePathError(f"Disallowed extension: {path.suffix}")


async def read_file(path: str, project_path: str | None = None) -> str:
    """Read a file's content as UTF-8 text.

    Args:
        path: Absolute or relative file path.
        project_path: Optional project root to sandbox relative paths.

    Returns:
        The file content as a string.

    Raises:
        UnsafePathError: If the path or extension is blocked.
        FileNotFoundError: If the file does not exist.
        UnicodeDecodeError: If the file cannot be decoded as UTF-8.
    """
    p = Path(path)
    project = Path(project_path).expanduser().resolve() if project_path else None
    _validate(p, project)

    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")

    if not p.is_file():
        raise ValueError(f"Not a file: {p}")

    return p.read_text(encoding="utf-8")


async def write_file(path: str, content: str, project_path: str | None = None) -> dict[str, Any]:
    """Write content to a file, creating parent directories as needed.

    Args:
        path: Absolute or relative file path.
        content: The text content to write.
        project_path: Optional project root to sandbox relative paths.

    Returns:
        Metadata dict with ``path`` and ``size``.

    Raises:
        UnsafePathError: If the path or extension is blocked.
    """
    p = Path(path)
    project = Path(project_path).expanduser().resolve() if project_path else None
    _validate(p, project)

    # Create parent directories if they don't exist
    p.parent.mkdir(parents=True, exist_ok=True)

    p.write_text(content, encoding="utf-8")
    logger.info("Wrote %d bytes to %s", len(content), p)
    return {"path": str(p.expanduser().resolve()), "size": len(content), "written": True}
