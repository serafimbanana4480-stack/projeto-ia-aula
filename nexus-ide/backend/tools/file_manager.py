"""Project file read/write with path-safety guards.

Blocked paths and extension allow-list from ARCHITECTURE.md §11.3.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    ".py",
    ".ts",
    ".js",
    ".tsx",
    ".jsx",
    ".rs",
    ".go",
    ".java",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".html",
    ".css",
    ".scss",
    ".sh",
    ".bash",
    ".sql",
    ".csv",
    ".env",
    ".gitignore",
    ".dockerignore",
    ".cfg",
    ".ini",
    ".conf",
    ".xml",
    ".log",
}
BLOCKED_PATH_PARTS = {"/etc", "/sys", "/proc", ".ssh", ".aws", "/root", "/var/run"}


class UnsafePathError(ValueError):
    pass


def _validate(path: Path) -> None:
    """Validate that a path is safe to read/write.

    Blocked paths are detected by checking for blocked substrings in BOTH
    the original path AND the resolved absolute path (with both forward
    and backward slashes normalised) so that the check works on Windows
    where ``Path('/etc/passwd').resolve()`` returns ``C:\\etc\\passwd``.
    """
    resolved = path.resolve()
    # Build normalised strings to check against (both slash styles)
    raw_str = str(path).replace("\\", "/")
    resolved_str = str(resolved).replace("\\", "/")
    for part in BLOCKED_PATH_PARTS:
        normalised_part = part.replace("\\", "/")
        if (
            normalised_part in raw_str
            or normalised_part in resolved_str
            or part in str(resolved)
        ):
            raise UnsafePathError(f"Blocked path: {resolved}")
    if path.suffix and path.suffix not in ALLOWED_EXTENSIONS:
        raise UnsafePathError(f"Disallowed extension: {path.suffix}")


async def read_file(path: str) -> str:
    """Read a file's content as UTF-8 text.

    Args:
        path: Absolute or relative file path.

    Returns:
        The file content as a string.

    Raises:
        UnsafePathError: If the path or extension is blocked.
        FileNotFoundError: If the file does not exist.
        UnicodeDecodeError: If the file cannot be decoded as UTF-8.
    """
    p = Path(path)
    _validate(p)

    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")

    if not p.is_file():
        raise ValueError(f"Not a file: {p}")

    return p.read_text(encoding="utf-8")


async def write_file(path: str, content: str) -> None:
    """Write content to a file, creating parent directories as needed.

    Args:
        path: Absolute or relative file path.
        content: The text content to write.

    Raises:
        UnsafePathError: If the path or extension is blocked.
    """
    p = Path(path)
    _validate(p)

    # Create parent directories if they don't exist
    p.parent.mkdir(parents=True, exist_ok=True)

    p.write_text(content, encoding="utf-8")
    logger.info("Wrote %d bytes to %s", len(content), p)
