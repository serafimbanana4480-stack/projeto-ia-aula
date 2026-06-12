"""Backup and restore operations for workspace files.

All backups are stored under ``.nexus/backups/`` (inside the nearest git root
or project directory) or in the user's home ``.nexus/backups/`` as a fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.core.workspace_security import _check_file_size_limit, logger


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
        logger.debug("Failed to get git root for %s", path, exc_info=True)
    return None


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


async def _restore_backup(backup_path: str, target_path: str) -> dict[str, Any]:
    """Restore a backup file to its original location.

    Returns metadata about the restore operation.
    """
    from backend.core.workspace_security import _is_blocked_path

    blocked, reason = _is_blocked_path(target_path)
    if blocked:
        return {"restored": False, "error": reason}

    try:
        backup = Path(backup_path).expanduser().resolve()
        target = Path(target_path).expanduser().resolve()
        if not await asyncio.to_thread(backup.exists):
            return {"restored": False, "error": f"Backup not found: {backup_path}"}

        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            target.write_bytes,
            await asyncio.to_thread(backup.read_bytes),
        )
        logger.info("Restored backup: %s -> %s", backup, target)
        return {"restored": True, "backup_path": str(backup), "target_path": str(target)}
    except PermissionError:
        return {"restored": False, "error": f"Permission denied: {target_path}"}
    except Exception as exc:
        logger.warning("Failed to restore backup %s: %s", backup_path, exc)
        return {"restored": False, "error": str(exc)}


async def _list_backups(path: str) -> dict[str, Any]:
    """List available backups for files under *path*.

    Returns a dict with ``backups`` (list of backup metadata) and ``count``.
    """
    from backend.core.workspace_security import _is_blocked_path

    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": reason}

    try:
        target = await asyncio.to_thread(lambda: Path(path).expanduser().resolve())
        if not await asyncio.to_thread(target.exists):
            return {"error": f"Path not found: {path}"}

        backup_dir = await _backup_dir_for(target)
        if not await asyncio.to_thread(backup_dir.exists):
            return {"backups": [], "count": 0, "backup_dir": str(backup_dir)}

        backups = []
        for item in await asyncio.to_thread(lambda: list(backup_dir.iterdir())):
            if await asyncio.to_thread(item.is_file) and item.suffix == ".bak":
                stat = await asyncio.to_thread(item.stat)
                backups.append(
                    {
                        "path": str(item),
                        "name": item.name,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                    }
                )
        backups.sort(key=lambda b: b["modified"], reverse=True)
        return {"backups": backups, "count": len(backups), "backup_dir": str(backup_dir)}
    except PermissionError:
        return {"error": f"Permission denied: {path}"}
    except Exception as exc:
        return {"error": f"Failed to list backups: {exc}"}
