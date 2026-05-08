"""Project file read/write with path-safety guards.

Blocked paths and extension allow-list from ARCHITECTURE.md §11.3.
"""
from __future__ import annotations

from pathlib import Path

ALLOWED_EXTENSIONS = {
    ".py", ".ts", ".js", ".tsx", ".jsx", ".rs", ".go", ".java",
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml",
}
BLOCKED_PATH_PARTS = {"/etc", "/sys", "/proc", ".ssh", ".aws"}


class UnsafePathError(ValueError):
    pass


def _validate(path: Path) -> None:
    resolved = path.resolve()
    for part in BLOCKED_PATH_PARTS:
        if part in str(resolved):
            raise UnsafePathError(f"Blocked path: {resolved}")
    if path.suffix and path.suffix not in ALLOWED_EXTENSIONS:
        raise UnsafePathError(f"Disallowed extension: {path.suffix}")


async def read_file(path: str) -> str:
    p = Path(path)
    _validate(p)
    raise NotImplementedError


async def write_file(path: str, content: str) -> None:
    p = Path(path)
    _validate(p)
    raise NotImplementedError
