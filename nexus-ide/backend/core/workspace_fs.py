"""Filesystem operations with absolute paths.

Provides read, write, directory listing, deletion, and search backed by
security validation and automatic backups.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.core.workspace_backup import _backup_dir_for, _create_backup
from backend.core.workspace_security import (
    MAX_FILE_SIZE_BYTES,
    _check_file_size_limit,
    _is_blocked_path,
    _log_operation,
    _verify_auth_token,
    logger,
)

_WINDOWS_TMP = None
_IGNORED_PROJECT_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "playwright-report",
}
_IGNORED_PROJECT_DIR_PREFIXES = (".next", ".pytest-", ".venv")
_IGNORED_PROJECT_DIR_SUFFIXES = (".egg-info",)


def _is_ignored_project_dir(name: str) -> bool:
    return (
        name in _IGNORED_PROJECT_DIRS
        or name.startswith(_IGNORED_PROJECT_DIR_PREFIXES)
        or name.endswith(_IGNORED_PROJECT_DIR_SUFFIXES)
    )


def _is_ignored_project_path(path: Path) -> bool:
    """Return whether a project path is generated, cached, or dependency data."""
    return any(_is_ignored_project_dir(part) for part in path.parts)


def _resolve_posix_tmp(path: str) -> Path:
    """Map ``/tmp`` and ``/tmp/...`` to the real Windows temp directory.

    On Windows the Python ``Path`` API treats ``/tmp`` as a relative path
    rooted at the current drive's root, which silently fails or creates files
    at ``C:\\tmp\\...``. This helper redirects those paths to
    ``%LOCALAPPDATA%\\Temp\\tmp\\...`` so Linux-targeted callers (including
    automation scripts) continue to work transparently.
    """
    if os.name != "nt":
        return Path(path)
    global _WINDOWS_TMP
    if _WINDOWS_TMP is None:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or tempfile.gettempdir()
        _WINDOWS_TMP = Path(base) / "tmp"
    if path == "/tmp" or path.startswith("/tmp/"):
        rel = path[len("/tmp/") :] if len(path) > 4 else ""
        target = _WINDOWS_TMP / rel if rel else _WINDOWS_TMP
        return target
    return Path(path)


def _resolve_path(path: str) -> Path:
    """Resolve *path* handling POSIX ``/tmp`` on Windows."""
    return _resolve_posix_tmp(path).expanduser().resolve()


def _resolve_write(path: str) -> Path:
    """Alias for :func:`_resolve_path` used by write helpers."""
    return _resolve_path(path)


def _path_for_security_check(path: str) -> str:
    """Normalize *path* (including POSIX ``/tmp`` on Windows) before security checks."""
    return str(_resolve_posix_tmp(path).expanduser())


def _verify_written(path: Path, expected_content: str) -> dict[str, Any]:
    """Read-back verification: confirm the file content matches what was requested.

    Skips verification for files larger than 1 MB to avoid doubling I/O
    on large writes — verification is most valuable for small config/code files.
    """
    if len(expected_content) > 1_048_576:  # 1 MB
        return {
            "ok": True,
            "size": len(expected_content),
            "skipped": "file too large for verification",
        }
    try:
        actual = path.read_text(encoding="utf-8")
        if actual == expected_content:
            return {"ok": True, "size": len(actual)}
        return {
            "ok": False,
            "error": "Write-back verification failed: content mismatch",
            "expected": expected_content[:500],
            "actual": actual[:500],
            "size": len(actual),
        }
    except Exception as exc:
        return {"ok": False, "error": f"Write-back verification failed: {exc}"}


def _deepest_existing_ancestor(target: Path) -> Path | None:
    """Return the deepest ancestor of *target* that actually exists on disk."""
    current = target.parent
    while True:
        if current.exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _collect_not_found_diagnostic(target: Path) -> dict[str, Any]:
    """Build recovery hints for a missing file.

    Autonomous agents routinely hallucinate conventional layouts (for example
    ``backend/app/main.py``) that do not exist in the real project. A bare
    "File not found" forces the model to guess again; a structured diagnostic
    (parent listing + same-name matches + same-suffix matches near the
    project) lets it self-correct on the next turn instead of failing the task.
    """
    diagnostic: dict[str, Any] = {}

    anchor = _deepest_existing_ancestor(target)
    if anchor is None:
        return diagnostic

    diagnostic["existing_ancestor"] = str(anchor)

    try:
        entries = sorted(
            entry.name + ("/" if entry.is_dir() else "") for entry in anchor.iterdir()
        )
        diagnostic["parent_listing"] = entries[:50]
    except OSError:
        pass

    wanted_name = target.name.lower()
    wanted_suffix = target.suffix.lower()
    name_matches: list[str] = []
    suffix_matches: list[str] = []
    scanned = 0
    try:
        for root, dirs, files in os.walk(anchor):
            dirs[:] = [d for d in dirs if not _is_ignored_project_dir(d)]
            depth = len(Path(root).relative_to(anchor).parts)
            if depth >= 4:
                dirs[:] = []
            for fname in files:
                scanned += 1
                if scanned > 4000 or len(name_matches) >= 10 and len(suffix_matches) >= 15:
                    break
                full = Path(root) / fname
                lower = fname.lower()
                if lower == wanted_name:
                    name_matches.append(str(full))
                elif wanted_suffix and lower.endswith(wanted_suffix) and len(suffix_matches) < 15:
                    suffix_matches.append(str(full))
            if scanned > 4000:
                break
    except OSError:
        pass

    if name_matches:
        diagnostic["same_name_files"] = name_matches[:10]
    if suffix_matches:
        diagnostic["same_suffix_files"] = suffix_matches[:15]
    return diagnostic


def _file_not_found_result(path: str, target: Path) -> dict[str, Any]:
    """Structured, recoverable "file not found" tool result."""
    result: dict[str, Any] = {
        "error": f"File not found: {path}",
        "recoverable": True,
        "resolved_path": str(target),
        "hint": (
            "The file does not exist at this exact path. Do NOT retry the same "
            "path. Inspect 'existing_ancestor', 'parent_listing' and "
            "'same_name_files' below to find the real location, or call "
            "list_dir_absolute / search_files_absolute to locate it, then read "
            "the corrected path."
        ),
    }
    try:
        result.update(_collect_not_found_diagnostic(target))
    except Exception as exc:  # diagnostics must never break the tool result
        logger.debug("not-found diagnostic failed for %s: %s", target, exc)
    logger.warning(
        "read_file_absolute: %s not found (ancestor=%s, %d same-name, %d same-suffix suggestions)",
        path,
        result.get("existing_ancestor"),
        len(result.get("same_name_files", [])),
        len(result.get("same_suffix_files", [])),
    )
    return result


async def read_file_absolute(path: str) -> dict[str, Any]:
    """Read any file the user has permission to read (absolute path)."""
    logger.info("read_file_absolute: %s", path)

    blocked, reason = _is_blocked_path(_path_for_security_check(path))
    if blocked:
        return {"error": reason}

    try:
        target = await asyncio.to_thread(_resolve_path, path)
        # Windows raises PermissionError — not IsADirectoryError — when
        # read_text() is given a directory. The resulting "Permission denied"
        # sent agents hunting for a non-existent access problem (session
        # bf1e9435b9ec47c9, DEBUGGER iteration 5, on the project root) instead
        # of simply switching tool. Name the real problem and the fix.
        if await asyncio.to_thread(target.is_dir):
            return {
                "error": (
                    f"'{path}' is a directory, not a file. Use list_dir_absolute "
                    "to list its contents, or pass the path of a file inside it."
                ),
                "path": str(target),
                "is_directory": True,
            }
        ok, size, err = _check_file_size_limit(target)
        if not ok:
            return {"error": err, "path": str(target), "size": size}
        content = await asyncio.to_thread(target.read_text, encoding="utf-8")
        return {"path": str(target), "content": content, "size": len(content)}
    except FileNotFoundError:
        return _file_not_found_result(path, target)
    except IsADirectoryError:
        return {
            "error": (
                f"'{path}' is a directory, not a file. Use list_dir_absolute to "
                "list its contents, or pass the path of a file inside it."
            ),
            "is_directory": True,
        }
    except PermissionError:
        return {"error": f"Permission denied: {path}"}
    except Exception as exc:
        return {"error": f"Failed to read file: {exc}"}


async def write_file_absolute(
    path: str, content: str, auth_token: str | None = None, overwrite: bool = True
) -> dict[str, Any]:
    """Write any file (absolute path) with backup of the original.

    ``overwrite`` defaults to ``True``.  When ``False`` and the file already
    exists, the write is rejected without modifying the existing file.
    """
    logger.info("write_file_absolute: %s (%d bytes) overwrite=%s", path, len(content), overwrite)

    if auth_token is not None:
        ok, reason = _verify_auth_token(auth_token)
        if not ok:
            return {"error": reason}

    blocked, reason = _is_blocked_path(_path_for_security_check(path))
    if blocked:
        result = {"error": reason}
        _log_operation("write_file_absolute", {"path": path, "overwrite": overwrite}, result)
        return result

    try:
        target = await asyncio.to_thread(_resolve_write, path)
        if not overwrite and await asyncio.to_thread(target.exists):
            result = {
                "error": f"File already exists: {target}",
                "path": str(target),
                "exists": True,
            }
            _log_operation("write_file_absolute", {"path": path, "overwrite": overwrite}, result)
            return result

        backup_meta = await _create_backup(target)
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)

        def _write() -> None:
            """Replace the destination atomically so readers never see a partial file."""
            existing_mode = target.stat().st_mode if target.exists() else None
            temp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="",
                    dir=target.parent,
                    prefix=f".{target.name}.",
                    suffix=".nexus-tmp",
                    delete=False,
                ) as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                    temp_path = Path(handle.name)
                if existing_mode is not None:
                    temp_path.chmod(existing_mode)
                os.replace(temp_path, target)
                temp_path = None
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)

        await asyncio.to_thread(_write)

        verification = await asyncio.to_thread(_verify_written, target, content)
        if not verification.get("ok", False):
            result = {
                "path": str(target),
                "written": False,
                "size": len(content),
                "backup": backup_meta,
                "error": verification.get("error", "Write-back verification failed"),
                "verification": verification,
            }
            _log_operation("write_file_absolute", {"path": path, "overwrite": overwrite}, result)
            return result

        result = {
            "path": str(target),
            "written": True,
            "size": len(content),
            "backup": backup_meta,
            "verified": True,
        }
        _log_operation("write_file_absolute", {"path": path, "overwrite": overwrite}, result)
        return result
    except PermissionError:
        result = {"error": f"Permission denied: {path}"}
        _log_operation("write_file_absolute", {"path": path, "overwrite": overwrite}, result)
        return result
    except Exception as exc:
        result = {"error": f"Failed to write file: {exc}"}
        _log_operation("write_file_absolute", {"path": path, "overwrite": overwrite}, result)
        return result


async def list_dir_absolute(
    path: str,
    recursive: bool = False,
    max_results: int = 10_000,
    include_hidden: bool = True,
    include_files: bool = True,
    include_dirs: bool = True,
    glob_pattern: str | None = None,
) -> dict[str, Any]:
    """List any directory (absolute path).

    ``include_hidden`` controls whether entries whose name starts with ``.``
    are returned.  Hiding hidden entries makes large project trees easier to
    navigate while still allowing the caller to opt-in.

    ``include_files`` / ``include_dirs`` can be used to return only one kind
    of entry (e.g. only source files).  ``glob_pattern`` applies an optional
    fnmatch filter to the entry name.
    """
    logger.info("list_dir_absolute: %s (recursive=%s)", path, recursive)

    blocked, reason = _is_blocked_path(_path_for_security_check(path))
    if blocked:
        return {"error": reason}

    try:
        target = await asyncio.to_thread(_resolve_path, path)
        if not await asyncio.to_thread(target.exists):
            return {"error": f"Path not found: {path}"}
        if not await asyncio.to_thread(target.is_dir):
            return {"error": f"Path is not a directory: {path}"}

        def _scan() -> tuple[list[dict[str, Any]], int, bool]:
            items: list[dict[str, Any]] = []
            skipped_hidden = 0
            truncated = False
            pending = [target]

            while pending:
                current = pending.pop()
                try:
                    entries = list(os.scandir(current))
                except (FileNotFoundError, PermissionError, OSError):
                    continue

                for entry_index, entry in enumerate(entries):
                    item = Path(entry.path)
                    name = entry.name
                    is_dir = entry.is_dir(follow_symlinks=False)
                    if recursive and is_dir and not _is_ignored_project_dir(name):
                        pending.append(item)

                    if not include_hidden and name.startswith("."):
                        skipped_hidden += 1
                        continue
                    if recursive and _is_ignored_project_path(item.relative_to(target)):
                        continue
                    if glob_pattern and not fnmatch.fnmatch(name, glob_pattern):
                        continue

                    is_file = entry.is_file(follow_symlinks=False)
                    if (is_file and not include_files) or (is_dir and not include_dirs):
                        continue
                    if not is_file and not is_dir:
                        continue

                    size = entry.stat(follow_symlinks=False).st_size if is_file else 0
                    items.append(
                        {
                            "path": str(item),
                            "name": name,
                            "type": "file" if is_file else "dir",
                            "size": size,
                        }
                    )
                    if len(items) >= max_results:
                        truncated = bool(pending) or entry_index + 1 < len(entries)
                        return items, skipped_hidden, truncated

                if not recursive:
                    break

            return items, skipped_hidden, truncated

        items, skipped_hidden, truncated = await asyncio.to_thread(_scan)

        return {
            "path": str(target),
            "items": items,
            "count": len(items),
            "truncated": truncated,
            "skipped_hidden": skipped_hidden,
            "include_hidden": include_hidden,
            "include_files": include_files,
            "include_dirs": include_dirs,
            "glob_pattern": glob_pattern,
        }
    except PermissionError:
        return {"error": f"Permission denied: {path}"}
    except Exception as exc:
        return {"error": f"Failed to list directory: {exc}"}


async def create_dir_absolute(path: str) -> dict[str, Any]:
    """Create directories recursively (absolute path)."""
    logger.info("create_dir_absolute: %s", path)

    blocked, reason = _is_blocked_path(_path_for_security_check(path))
    if blocked:
        return {"error": reason}

    try:
        target = await asyncio.to_thread(_resolve_path, path)
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

    blocked, reason = _is_blocked_path(_path_for_security_check(path))
    if blocked:
        result = {"error": reason}
        _log_operation(
            "delete_file_absolute", {"path": path, "move_to_trash": move_to_trash}, result
        )
        return result

    try:
        target = await asyncio.to_thread(_resolve_path, path)
        if not await asyncio.to_thread(target.exists):
            result = {"error": f"File not found: {path}"}
            _log_operation(
                "delete_file_absolute", {"path": path, "move_to_trash": move_to_trash}, result
            )
            return result
        if await asyncio.to_thread(target.is_dir):
            result = {"error": "Path is a directory; use recursive directory deletion instead"}
            _log_operation(
                "delete_file_absolute", {"path": path, "move_to_trash": move_to_trash}, result
            )
            return result

        if move_to_trash:
            trash_dir = await _backup_dir_for(target) / "trash"
            await asyncio.to_thread(trash_dir.mkdir, parents=True, exist_ok=True)
            import hashlib

            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            hash_suffix = hashlib.sha256(str(target).encode()).hexdigest()[:8]
            trash_name = f"{target.name}.{timestamp}.{hash_suffix}"
            trash_path = trash_dir / trash_name
            await asyncio.to_thread(shutil.move, str(target), str(trash_path))
            logger.info("Moved to trash: %s -> %s", target, trash_path)
            result = {"path": str(target), "deleted": True, "trash_path": str(trash_path)}
            _log_operation(
                "delete_file_absolute", {"path": path, "move_to_trash": move_to_trash}, result
            )
            return result

        await asyncio.to_thread(target.unlink)
        logger.info("Deleted permanently: %s", target)
        result = {"path": str(target), "deleted": True, "trash_path": None}
        _log_operation(
            "delete_file_absolute", {"path": path, "move_to_trash": move_to_trash}, result
        )
        return result
    except PermissionError:
        result = {"error": f"Permission denied: {path}"}
        _log_operation(
            "delete_file_absolute", {"path": path, "move_to_trash": move_to_trash}, result
        )
        return result
    except Exception as exc:
        result = {"error": f"Failed to delete file: {exc}"}
        _log_operation(
            "delete_file_absolute", {"path": path, "move_to_trash": move_to_trash}, result
        )
        return result


async def delete_dir_absolute(
    path: str, move_to_trash: bool = True, auth_token: str | None = None
) -> dict[str, Any]:
    """Delete a directory recursively (absolute path) with optional trash backup.

    When ``move_to_trash`` is ``True`` the entire directory tree is moved to
    ``.nexus/backups/trash/`` so it can be recovered.  Permanent deletion is
    destructive and requires explicit opt-out.
    """
    logger.info("delete_dir_absolute: %s (trash=%s)", path, move_to_trash)

    if auth_token is not None:
        ok, reason = _verify_auth_token(auth_token)
        if not ok:
            return {"error": reason}

    blocked, reason = _is_blocked_path(_path_for_security_check(path))
    if blocked:
        result = {"error": reason}
        _log_operation(
            "delete_dir_absolute", {"path": path, "move_to_trash": move_to_trash}, result
        )
        return result

    try:
        target = await asyncio.to_thread(_resolve_path, path)
        if not await asyncio.to_thread(target.exists):
            result = {"error": f"Directory not found: {path}"}
            _log_operation(
                "delete_dir_absolute", {"path": path, "move_to_trash": move_to_trash}, result
            )
            return result
        if not await asyncio.to_thread(target.is_dir):
            result = {"error": f"Path is not a directory: {path}"}
            _log_operation(
                "delete_dir_absolute", {"path": path, "move_to_trash": move_to_trash}, result
            )
            return result

        if move_to_trash:
            trash_dir = await _backup_dir_for(target) / "trash"
            await asyncio.to_thread(trash_dir.mkdir, parents=True, exist_ok=True)
            import hashlib

            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            hash_suffix = hashlib.sha256(str(target).encode()).hexdigest()[:8]
            trash_name = f"{target.name}.{timestamp}.{hash_suffix}"
            trash_path = trash_dir / trash_name
            await asyncio.to_thread(shutil.move, str(target), str(trash_path))
            logger.info("Moved directory to trash: %s -> %s", target, trash_path)
            result = {
                "path": str(target),
                "deleted": True,
                "trash_path": str(trash_path),
                "items_moved": None,
            }
            _log_operation(
                "delete_dir_absolute", {"path": path, "move_to_trash": move_to_trash}, result
            )
            return result

        await asyncio.to_thread(shutil.rmtree, str(target))
        logger.info("Deleted directory permanently: %s", target)
        result = {"path": str(target), "deleted": True, "trash_path": None, "items_moved": None}
        _log_operation(
            "delete_dir_absolute", {"path": path, "move_to_trash": move_to_trash}, result
        )
        return result
    except PermissionError:
        result = {"error": f"Permission denied: {path}"}
        _log_operation(
            "delete_dir_absolute", {"path": path, "move_to_trash": move_to_trash}, result
        )
        return result
    except Exception as exc:
        result = {"error": f"Failed to delete directory: {exc}"}
        _log_operation(
            "delete_dir_absolute", {"path": path, "move_to_trash": move_to_trash}, result
        )
        return result


async def move_file_absolute(src: str, dest: str, auth_token: str | None = None) -> dict[str, Any]:
    """Move or rename a file or directory (absolute paths)."""
    logger.info("move_file_absolute: %s -> %s", src, dest)

    if auth_token is not None:
        ok, reason = _verify_auth_token(auth_token)
        if not ok:
            return {"error": reason}

    for p in (src, dest):
        blocked, reason = _is_blocked_path(_path_for_security_check(p))
        if blocked:
            result = {"error": reason}
            _log_operation("move_file_absolute", {"src": src, "dest": dest}, result)
            return result

    try:
        src_path = await asyncio.to_thread(_resolve_path, src)
        dest_path = await asyncio.to_thread(_resolve_path, dest)

        if not await asyncio.to_thread(src_path.exists):
            return {"error": f"Source not found: {src}"}
        if await asyncio.to_thread(dest_path.exists):
            return {"error": f"Destination already exists: {dest}"}

        await asyncio.to_thread(dest_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(src_path), str(dest_path))
        result = {"src": str(src_path), "dest": str(dest_path), "moved": True}
        _log_operation("move_file_absolute", {"src": src, "dest": dest}, result)
        return result
    except PermissionError:
        result = {"error": f"Permission denied: {src}"}
        _log_operation("move_file_absolute", {"src": src, "dest": dest}, result)
        return result
    except Exception as exc:
        result = {"error": f"Failed to move file: {exc}"}
        _log_operation("move_file_absolute", {"src": src, "dest": dest}, result)
        return result


async def copy_file_absolute(src: str, dest: str, auth_token: str | None = None) -> dict[str, Any]:
    """Copy a file (absolute paths).  Directories are not supported."""
    logger.info("copy_file_absolute: %s -> %s", src, dest)

    if auth_token is not None:
        ok, reason = _verify_auth_token(auth_token)
        if not ok:
            return {"error": reason}

    for p in (src, dest):
        blocked, reason = _is_blocked_path(_path_for_security_check(p))
        if blocked:
            result = {"error": reason}
            _log_operation("copy_file_absolute", {"src": src, "dest": dest}, result)
            return result

    try:
        src_path = await asyncio.to_thread(_resolve_path, src)
        dest_path = await asyncio.to_thread(_resolve_path, dest)

        if not await asyncio.to_thread(src_path.exists):
            return {"error": f"Source not found: {src}"}
        if await asyncio.to_thread(src_path.is_dir):
            return {"error": "Source is a directory; use directory copy instead"}
        if await asyncio.to_thread(dest_path.exists):
            return {"error": f"Destination already exists: {dest}"}

        await asyncio.to_thread(dest_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, str(src_path), str(dest_path))
        result = {"src": str(src_path), "dest": str(dest_path), "copied": True}
        _log_operation("copy_file_absolute", {"src": src, "dest": dest}, result)
        return result
    except PermissionError:
        result = {"error": f"Permission denied: {src}"}
        _log_operation("copy_file_absolute", {"src": src, "dest": dest}, result)
        return result
    except Exception as exc:
        result = {"error": f"Failed to copy file: {exc}"}
        _log_operation("copy_file_absolute", {"src": src, "dest": dest}, result)
        return result


async def get_file_info_absolute(path: str) -> dict[str, Any]:
    """Return metadata for a file or directory (absolute path)."""
    logger.info("get_file_info_absolute: %s", path)

    blocked, reason = _is_blocked_path(_path_for_security_check(path))
    if blocked:
        return {"error": reason}

    try:
        target = await asyncio.to_thread(_resolve_path, path)
        if not await asyncio.to_thread(target.exists):
            return {"error": f"Path not found: {path}"}

        stat = await asyncio.to_thread(target.stat)
        is_file = await asyncio.to_thread(target.is_file)
        is_dir = await asyncio.to_thread(target.is_dir)
        info = {
            "path": str(target),
            "name": target.name,
            "type": "file" if is_file else ("dir" if is_dir else "other"),
            "size": stat.st_size,
            "created": stat.st_ctime,
            "modified": stat.st_mtime,
            "accessed": stat.st_atime,
            "exists": True,
        }
        if is_dir:
            try:
                entries = await asyncio.to_thread(lambda: list(target.iterdir()))
                info["children_count"] = len(entries)
            except Exception:
                info["children_count"] = None
        return info
    except PermissionError:
        return {"error": f"Permission denied: {path}"}
    except Exception as exc:
        return {"error": f"Failed to get file info: {exc}"}


async def read_multiple_files_absolute(
    paths: list[str],
    max_total_bytes: int = 5 * 1024 * 1024,
    max_files: int = 100,
) -> dict[str, Any]:
    """Read multiple files in a single call (absolute paths).

    Each path is validated against the security blocklist and file-size
    limits.  Failures for individual files are collected in ``errors``
    without aborting the whole batch, so agents can safely request many
    files at once.

    Args:
        paths: List of absolute file paths to read.
        max_total_bytes: Maximum combined size of all successful reads.
        max_files: Maximum number of paths that will be processed.

    Returns:
        Dict with ``files`` (path -> content), ``errors`` (path -> reason),
        ``read_count``, ``skipped_count``, and ``total_bytes``.
    """
    logger.info("read_multiple_files_absolute: %d paths", len(paths))

    if not paths:
        return {
            "files": {},
            "errors": {},
            "read_count": 0,
            "skipped_count": 0,
            "total_bytes": 0,
        }

    if len(paths) > max_files:
        skipped = paths[max_files:]
        paths = paths[:max_files]
    else:
        skipped = []

    def _read_batch() -> tuple[dict[str, str], dict[str, str], int]:
        files: dict[str, str] = {}
        errors: dict[str, str] = {}
        total_bytes = 0

        for raw_path in paths:
            blocked, reason = _is_blocked_path(_path_for_security_check(raw_path))
            if blocked:
                errors[raw_path] = reason
                continue

            try:
                target = _resolve_path(raw_path)
                ok, _size, err = _check_file_size_limit(target)
                if not ok:
                    errors[str(target)] = err or "File too large"
                    continue
                if not target.exists():
                    errors[str(target)] = f"File not found: {raw_path}"
                    continue
                if not target.is_file():
                    errors[str(target)] = f"Not a file: {raw_path}"
                    continue

                # Writers in NEXUS use atomic replacement.  The before/after
                # signature also detects external, non-atomic writes and
                # retries once instead of returning torn content.
                before = target.stat()
                content = target.read_text(encoding="utf-8")
                after = target.stat()
                if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                    content = target.read_text(encoding="utf-8")
                content_bytes = len(content.encode("utf-8"))
                if total_bytes + content_bytes > max_total_bytes:
                    errors[str(target)] = (
                        f"Skipped: would exceed max_total_bytes ({max_total_bytes} bytes)"
                    )
                    continue
                files[str(target)] = content
                total_bytes += content_bytes
            except PermissionError:
                errors[raw_path] = f"Permission denied: {raw_path}"
            except Exception as exc:
                errors[raw_path] = f"Failed to read file: {exc}"
        return files, errors, total_bytes

    files, errors, total_bytes = await asyncio.to_thread(_read_batch)

    for skipped_path in skipped:
        errors[skipped_path] = f"Skipped: exceeded max_files ({max_files})"

    return {
        "files": files,
        "errors": errors,
        "read_count": len(files),
        "skipped_count": len(skipped),
        "total_bytes": total_bytes,
    }


async def search_files_absolute(
    pattern: str,
    root_path: str,
    max_results: int = 100,
    glob_pattern: str | None = None,
) -> dict[str, Any]:
    """Grep-like search across files under *root_path*."""
    logger.info("search_files_absolute: pattern='%s' root='%s'", pattern, root_path)

    blocked, reason = _is_blocked_path(_path_for_security_check(root_path))
    if blocked:
        return {"error": reason}

    try:
        root = await asyncio.to_thread(_resolve_path, root_path)
        if not await asyncio.to_thread(root.exists):
            return {"error": f"Root path not found: {root_path}"}

        results: list[dict[str, Any]] = []
        rg = shutil.which("rg")
        if rg:
            cmd = [
                rg,
                "--json",
                "--fixed-strings",
                "--ignore-case",
                "--max-filesize",
                str(MAX_FILE_SIZE_BYTES),
            ]
            if glob_pattern:
                cmd.extend(["--glob", glob_pattern])
            cmd.extend([pattern, str(root)])
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await proc.communicate()
            by_path: dict[str, dict[str, Any]] = {}
            for raw_line in stdout.splitlines():
                try:
                    event = json.loads(raw_line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if event.get("type") != "match":
                    continue
                data = event.get("data", {})
                path_text = data.get("path", {}).get("text")
                line_text = data.get("lines", {}).get("text", "").rstrip("\r\n")
                if not path_text:
                    continue
                absolute = (
                    str((root / path_text).resolve())
                    if not Path(path_text).is_absolute()
                    else path_text
                )
                if absolute not in by_path and len(by_path) >= max_results:
                    break
                item = by_path.setdefault(
                    absolute,
                    {"path": absolute, "matches": [], "match_count": 0},
                )
                item["match_count"] += 1
                if len(item["matches"]) < 5:
                    item["matches"].append(
                        {"line": int(data.get("line_number") or 0), "text": line_text}
                    )
            results = list(by_path.values())[:max_results]
        else:

            def _search_fallback() -> list[dict[str, Any]]:
                found: list[dict[str, Any]] = []
                lowered = pattern.lower()
                for current, dirs, files in os.walk(root):
                    dirs[:] = [d for d in dirs if not _is_ignored_project_dir(d)]
                    for filename in files:
                        if glob_pattern and not fnmatch.fnmatch(filename, glob_pattern):
                            continue
                        file_path = Path(current) / filename
                        try:
                            if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
                                continue
                            lines = file_path.read_text(
                                encoding="utf-8", errors="ignore"
                            ).splitlines()
                        except (OSError, UnicodeError):
                            continue
                        matches = [
                            {"line": index + 1, "text": line}
                            for index, line in enumerate(lines)
                            if lowered in line.lower()
                        ]
                        if matches:
                            found.append(
                                {
                                    "path": str(file_path),
                                    "matches": matches[:5],
                                    "match_count": len(matches),
                                }
                            )
                            if len(found) >= max_results:
                                return found
                return found

            results = await asyncio.to_thread(_search_fallback)

        return {"pattern": pattern, "root": str(root), "results": results, "count": len(results)}
    except PermissionError:
        return {"error": f"Permission denied: {root_path}"}
    except Exception as exc:
        return {"error": f"Search failed: {exc}"}
