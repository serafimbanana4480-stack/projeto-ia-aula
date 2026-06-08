"""File operations tool — read, write, list, search files via WorkspaceManager.

Delegates filesystem operations to :class:`backend.core.workspace.WorkspaceManager`
while preserving shared/exclusive file locks for concurrent safety.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend.core.file_locks import DeadlockError, FileLockManager, LockError
from backend.core.workspace import WorkspaceManager
from backend.persistence.db import propose_change
from backend.tools.registry import ToolSpec, register_tool

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


async def read_file(
    path: str,
    project_path: str = ".",
    owner: str = "anonymous",
    timeout_seconds: float = 30.0,
) -> dict:
    """Read file contents.

    Acquires a shared read lock to prevent concurrent writes.
    """
    manager = WorkspaceManager(project_path)
    full_path = manager._resolve_path(path)
    try:
        await _lock_manager.acquire_read_lock(
            str(full_path), owner, timeout=timeout_seconds
        )
        return await manager.read_file(path)
    except (LockError, DeadlockError) as e:
        return {"error": f"Lock error: {e}"}
    except Exception as e:
        return {"error": f"Failed to read: {e}"}
    finally:
        _lock_manager.release_lock(str(full_path), owner)


async def write_file(
    path: str,
    content: str,
    project_path: str = ".",
    session_id: str | None = None,
    project_id: str | None = None,
    owner: str = "anonymous",
    timeout_seconds: float = 30.0,
) -> dict:
    """Write content to file. Logs as proposed change for audit.

    Trust check: if the project is not trusted, the write is blocked
    unless a session_id is provided (interactive mode).

    Acquires an exclusive write lock to prevent concurrent reads/writes.
    """
    manager = WorkspaceManager(project_path)
    full_path = manager._resolve_path(path)

    # Block dangerous executable extensions
    if full_path.suffix.lower() in _BLOCKED_EXTENSIONS:
        return {"error": f"Writing files with extension '{full_path.suffix}' is blocked for security"}

    try:
        await _lock_manager.acquire_write_lock(
            str(full_path), owner, timeout=timeout_seconds
        )

        # Trust verification — block writes to untrusted projects
        from backend.persistence.db import get_project_by_path

        project = get_project_by_path(str(Path(project_path).resolve()))
        if project and not project.get("trust", False):
            return {
                "error": (
                    f"Project '{project['name']}' is NOT trusted. "
                    "Enable trust in project settings before allowing file modifications."
                )
            }

        result = await manager.write_file(
            path, content, session_id=session_id, project_id=project_id
        )

        # Re-log with relative path for consistency with legacy behaviour
        if session_id and "error" not in result:
            propose_change(
                session_id=session_id,
                project_id=project_id,
                file_path=str(full_path.relative_to(Path(project_path).resolve())),
                operation="modify" if result.get("backup", {}).get("backed_up") else "create",
                new_content=content,
            )

        return result
    except (LockError, DeadlockError) as e:
        return {"error": f"Lock error: {e}"}
    except Exception as e:
        return {"error": f"Failed to write: {e}"}
    finally:
        _lock_manager.release_lock(str(full_path), owner)


async def list_dir(
    path: str = ".", project_path: str = ".", recursive: bool = False
) -> dict:
    """List directory contents."""
    manager = WorkspaceManager(project_path)
    return await manager.list_directory(path, recursive=recursive)


async def search_in_files(
    query: str, project_path: str = ".", file_pattern: str = "*.py"
) -> dict:
    """Search for text in files."""
    manager = WorkspaceManager(project_path)
    return await manager.search_files(path=".", pattern=query, glob=file_pattern)


# Register tools
register_tool(
    ToolSpec(
        name="read_file",
        description="Read the contents of a file from the project workspace",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to project root"},
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
            },
            "required": ["path"],
        },
        handler=read_file,
    )
)

register_tool(
    ToolSpec(
        name="write_file",
        description="Write content to a file in the project workspace. Logs as proposed change.",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to project root"},
                "content": {"type": "string", "description": "Content to write"},
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
            },
            "required": ["path", "content"],
        },
        handler=write_file,
    )
)

register_tool(
    ToolSpec(
        name="list_dir",
        description="List files and directories in a path",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": ".", "description": "Path to list"},
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
                "recursive": {
                    "type": "boolean",
                    "default": False,
                    "description": "Recursive listing",
                },
            },
        },
        handler=list_dir,
    )
)

register_tool(
    ToolSpec(
        name="search_in_files",
        description="Search for text in files matching a pattern",
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search for"},
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
                "file_pattern": {
                    "type": "string",
                    "default": "*.py",
                    "description": "File pattern (glob)",
                },
            },
            "required": ["query"],
        },
        handler=search_in_files,
    )
)
