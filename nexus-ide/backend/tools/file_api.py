"""Unified file API — read, write, list, delete, search.

Supports both relative paths (resolved against *project_path* and validated
via sandbox rules) and absolute paths (validated via
``backend.core.workspace_security``).

This module is the **single source of truth** for filesystem operations
inside the NEXUS tool layer.  Legacy modules such as
``backend.tools.file_ops`` are thin wrappers that delegate here.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

from backend.core.file_locks import DeadlockError, FileLockManager, LockError
from backend.core.rollback_manager import RollbackManager
from backend.core.workspace import WorkspaceManager
from backend.core.workspace_fs import (
    _path_for_security_check,
    delete_file_absolute,
    list_dir_absolute,
    read_file_absolute,
    read_multiple_files_absolute,
    search_files_absolute,
    write_file_absolute,
)
from backend.core.workspace_security import _is_blocked_path

logger = logging.getLogger(__name__)

_lock_manager = FileLockManager()

# Blocked file extensions for write operations (prevent malware drops)
_BLOCKED_EXTENSIONS: set[str] = {
    ".exe",
    ".dll",
    ".bat",
    ".cmd",
    ".com",
    ".scr",
    ".msi",
    ".vbs",
    ".wsf",
    ".jar",
}


def _resolve_path(path: str, project_path: str) -> Path:
    """Resolve *path* relative to *project_path* if it is not absolute."""
    project = Path(project_path).expanduser().resolve()
    if Path(path).is_absolute():
        target = Path(path).expanduser().resolve()
    else:
        target = (project / path).expanduser().resolve()
    return target


def _validate_relative_path(project_path: str, target_path: str) -> Path:
    """Validate that *target_path* is within *project_path* (sandbox).

    Raises ``PermissionError`` with a message containing *not allowed* so
    that legacy tests can match on that substring.
    """
    project = Path(project_path).expanduser().resolve()
    return _validate_relative_path_under(project, target_path)


def _validate_relative_path_under(project: Path, target_path: str) -> Path:
    """Validate a relative path when the project root is already resolved."""
    target = (project / target_path).expanduser().resolve()
    try:
        target.relative_to(project)
    except ValueError:
        raise PermissionError(
            f"Access not allowed — path {target} is outside project root {project}"
        ) from None
    return target


def _is_absolute(path: str) -> bool:
    return Path(path).is_absolute()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def read(
    path: str,
    project_path: str = ".",
    owner: str = "anonymous",
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Read a file. Supports absolute and relative paths."""
    if _is_absolute(path):
        blocked, reason = _is_blocked_path(_path_for_security_check(path))
        if blocked:
            return {"error": reason}
        return await read_file_absolute(path)

    # Relative path — sandbox + lock
    try:
        full_path = _validate_relative_path(project_path, path)
    except PermissionError as exc:
        return {"error": str(exc)}

    try:
        await _lock_manager.acquire_read_lock(str(full_path), owner, timeout=timeout_seconds)
        return await read_file_absolute(str(full_path))
    except (LockError, DeadlockError) as exc:
        return {"error": f"Lock error: {exc}"}
    except Exception as exc:
        return {"error": f"Failed to read: {exc}"}
    finally:
        _lock_manager.release_lock(str(full_path), owner)


async def read_multiple(
    paths: list[str],
    project_path: str = ".",
    owner: str = "anonymous",
    timeout_seconds: float = 30.0,
    max_total_bytes: int = 5 * 1024 * 1024,
    max_files: int = 100,
) -> dict[str, Any]:
    """Read multiple files in one call. Supports absolute and relative paths.

    Relative paths are resolved against *project_path* and validated against
    the project sandbox.  Absolute paths are validated against the global
    allowed-base security rules.
    """
    if not paths:
        return {
            "files": {},
            "errors": {},
            "read_count": 0,
            "skipped_count": 0,
            "total_bytes": 0,
        }

    resolved_paths: list[str] = []
    project_root = Path(project_path).expanduser().resolve()
    for path in paths:
        if _is_absolute(path):
            blocked, reason = _is_blocked_path(_path_for_security_check(path))
            if blocked:
                return {
                    "files": {},
                    "errors": {path: reason},
                    "read_count": 0,
                    "skipped_count": len(paths) - 1,
                    "total_bytes": 0,
                }
            resolved_paths.append(path)
        else:
            try:
                full_path = _validate_relative_path_under(project_root, path)
            except PermissionError as exc:
                return {
                    "files": {},
                    "errors": {path: str(exc)},
                    "read_count": 0,
                    "skipped_count": len(paths) - 1,
                    "total_bytes": 0,
                }
            resolved_paths.append(str(full_path))

    # Batch reads deliberately avoid one cross-process lock file per path.
    # Workspace writes are atomic and the batch reader verifies each file's
    # stat signature, which gives consistent individual reads without turning
    # a 100-file context load into hundreds of filesystem lock operations.
    try:
        return await read_multiple_files_absolute(
            resolved_paths,
            max_total_bytes=max_total_bytes,
            max_files=max_files,
        )
    except Exception as exc:
        return {"error": f"Failed to read multiple files: {exc}"}


async def write(
    path: str,
    content: str,
    project_path: str = ".",
    owner: str = "anonymous",
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Write content to a file. Supports absolute and relative paths.

    This is the *core* write operation.  Trust checks and audit logging
    (``propose_change``) are the responsibility of the caller — see
    ``backend.tools.file_ops.write_file`` for the legacy wrapper that adds
    those extras.
    """
    if _is_absolute(path):
        full_path = path
    else:
        try:
            full_path = str(_validate_relative_path(project_path, path))
        except PermissionError as exc:
            return {"error": str(exc)}

    existing_content: str | None = None
    with contextlib.suppress(Exception):
        existing_content = await read_file_absolute(full_path)

    try:
        await RollbackManager().record_snapshot(
            project_path=project_path,
            artifact_id=owner,
            file_path=full_path,
            content_before=existing_content,
            metadata={"tool": "write_file", "owner": owner},
        )
    except Exception as exc:
        logger.warning("Failed to record rollback snapshot: %s", exc)

    if _is_absolute(path):
        blocked, reason = _is_blocked_path(_path_for_security_check(path))
        if blocked:
            return {"error": reason}
        if Path(path).suffix.lower() in _BLOCKED_EXTENSIONS:
            return {
                "error": (
                    f"Writing files with extension '{Path(path).suffix}' is blocked for security"
                )
            }
        return await write_file_absolute(path, content)

    # Relative path — sandbox + lock + blocked ext
    if Path(full_path).suffix.lower() in _BLOCKED_EXTENSIONS:
        return {
            "error": (
                f"Writing files with extension '{Path(full_path).suffix}' is blocked for security"
            )
        }

    try:
        await _lock_manager.acquire_write_lock(str(full_path), owner, timeout=timeout_seconds)
        return await write_file_absolute(str(full_path), content)
    except (LockError, DeadlockError) as exc:
        return {"error": f"Lock error: {exc}"}
    except Exception as exc:
        return {"error": f"Failed to write: {exc}"}
    finally:
        _lock_manager.release_lock(str(full_path), owner)


async def list_files(
    path: str = ".",
    project_path: str = ".",
    recursive: bool = False,
) -> dict[str, Any]:
    """List directory contents. Supports absolute and relative paths."""
    if _is_absolute(path):
        blocked, reason = _is_blocked_path(_path_for_security_check(path))
        if blocked:
            return {"error": reason}
        return await list_dir_absolute(path, recursive=recursive)

    # Relative path — sandbox
    try:
        full_path = _validate_relative_path(project_path, path)
    except PermissionError as exc:
        return {"error": str(exc)}

    return await list_dir_absolute(str(full_path), recursive=recursive)


async def delete(
    path: str,
    project_path: str = ".",
    move_to_trash: bool = True,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Delete a file. Supports absolute and relative paths."""
    if _is_absolute(path):
        blocked, reason = _is_blocked_path(_path_for_security_check(path))
        if blocked:
            return {"error": reason}
        return await delete_file_absolute(path, move_to_trash=move_to_trash, auth_token=auth_token)

    # Relative path — sandbox
    try:
        full_path = _validate_relative_path(project_path, path)
    except PermissionError as exc:
        return {"error": str(exc)}

    if full_path.is_dir():
        return {"error": "Path is a directory; use recursive directory deletion instead"}

    return await delete_file_absolute(str(full_path), move_to_trash=move_to_trash)


async def search(
    query: str,
    path: str = ".",
    project_path: str = ".",
    file_pattern: str = "*.py",
    max_results: int = 100,
) -> dict[str, Any]:
    """Search for text in files. Supports absolute and relative paths.

    For relative paths the legacy result format (``path`` relative to root,
    ``matches`` as an int, ``preview`` as a list of ``(line, text)`` tuples)
    is preserved by delegating to :class:`WorkspaceManager`.

    For absolute paths the cleaner ``workspace_fs`` format is returned.
    """
    if _is_absolute(path):
        blocked, reason = _is_blocked_path(_path_for_security_check(path))
        if blocked:
            return {"error": reason}
        return await search_files_absolute(query, path, max_results=max_results)

    # Relative path — use WorkspaceManager for legacy result format
    manager = WorkspaceManager(project_path)
    return await manager.search_files(path=path, pattern=query, glob=file_pattern)
