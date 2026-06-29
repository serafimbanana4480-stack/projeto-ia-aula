# backend/tools/append_file.py
"""Append content to a file safely with lock handling."""

from __future__ import annotations

import logging

from backend.core.file_locks import FileLockManager, LockError
from backend.core.workspace import WorkspaceManager
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)
_lock_manager = FileLockManager()


async def append_file(
    path: str,
    content: str,
    project_path: str = ".",
    owner: str = "anonymous",
    timeout_seconds: float = 30.0,
) -> dict:
    """Append `content` to `path` inside the workspace.

    Returns a dict with `ok`, `error` (if any) and the final file size.
    """
    mgr = WorkspaceManager(project_path)
    try:
        full_path = mgr._resolve_path(path)
    except PermissionError as exc:
        return {"error": str(exc)}

    # security – block dangerous extensions
    if full_path.suffix.lower() in {
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
    }:
        return {"error": f"Appending to '{full_path.suffix}' files is blocked"}

    try:
        await _lock_manager.acquire_write_lock(str(full_path), owner, timeout=timeout_seconds)
        # open in append‑binary mode to avoid encoding surprises
        with open(full_path, "ab") as fp:
            fp.write(content.encode("utf-8"))
        size = full_path.stat().st_size
        return {"ok": True, "size": size}
    except (LockError, Exception) as exc:
        return {"error": str(exc)}
    finally:
        _lock_manager.release_lock(str(full_path), owner)


# Register the tool
register_tool(
    ToolSpec(
        name="append_file",
        description="Append textual content to an existing file (UTF‑8).",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to project root"},
                "content": {"type": "string", "description": "Text to append"},
                "project_path": {"type": "string", "default": "."},
                "owner": {"type": "string", "default": "anonymous"},
            },
            "required": ["path", "content"],
        },
        handler=append_file,
    )
)
