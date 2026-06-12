"""Filesystem operations with absolute paths.

Provides read, write, directory listing, deletion, and search backed by
security validation and automatic backups.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

from backend.core.workspace_security import (
    MAX_FILE_SIZE_BYTES,
    _check_file_size_limit,
    _is_blocked_path,
    _log_operation,
    _verify_auth_token,
    logger,
)
from backend.core.workspace_backup import _backup_dir_for, _create_backup


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
    path: str, content: str, auth_token: str | None = None, overwrite: bool = True
) -> dict[str, Any]:
    """Write any file (absolute path) with backup of the original.

    The ``overwrite`` parameter is accepted for compatibility with agent calls
    but is ignored — the tool always writes (and backs up) the file.
    """
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


async def list_dir_absolute(path: str, recursive: bool = False, max_results: int = 10_000) -> dict[str, Any]:
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
        for item in raw_items[:max_results]:
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

        return {"path": str(target), "items": items, "count": len(items), "truncated": len(raw_items) > max_results}
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
            from datetime import UTC, datetime
            import hashlib
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
