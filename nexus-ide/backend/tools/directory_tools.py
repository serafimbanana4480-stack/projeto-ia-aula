"""Directory and file manipulation tools.

Provides safe directory creation, file copy, move, and delete operations
with sandbox validation to prevent path traversal outside project root.
"""

from __future__ import annotations

import logging
import shutil

from backend.core.file_locks import DeadlockError, FileLockManager, LockError
from backend.core.workspace_fs import delete_dir_absolute, get_file_info_absolute
from backend.tools.file_api import _validate_relative_path as _validate_path
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

_lock_manager = FileLockManager()


async def create_directory(path: str, project_path: str = ".") -> dict:
    """Create directories (nested supported).

    Args:
        path: Directory path relative to project root (supports nested paths).
        project_path: Project root path.

    Returns:
        Dict with created path and success status.
    """
    try:
        full_path = _validate_path(project_path, path)
        full_path.mkdir(parents=True, exist_ok=True)
        logger.info("Created directory %s", full_path)
        return {"path": str(full_path), "created": True}
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Failed to create directory: {e}"}


async def copy_file(src: str, dest: str, project_path: str = ".") -> dict:
    """Copy files within the project.

    Acquires a read lock on the source and a write lock on the destination
    to prevent concurrent corruption.

    Args:
        src: Source file path relative to project root.
        dest: Destination file path relative to project root.
        project_path: Project root path.

    Returns:
        Dict with source, destination, and success status.
    """
    try:
        src_path = _validate_path(project_path, src)
        dest_path = _validate_path(project_path, dest)

        if not src_path.exists():
            return {"error": f"Source file not found: {src}"}

        if src_path.is_dir():
            return {"error": f"Source is a directory, not a file: {src}"}

        if src_path.resolve() == dest_path.resolve():
            return {"error": "Source and destination are the same file"}

        src_str = str(src_path)
        dest_str = str(dest_path)
        agent = "anonymous"

        # Acquire locks in alphabetical order to prevent deadlocks
        locks = sorted([(src_str, "read"), (dest_str, "write")], key=lambda x: x[0])
        for p, lock_type in locks:
            if lock_type == "read":
                await _lock_manager.acquire_read_lock(p, agent)
            else:
                await _lock_manager.acquire_write_lock(p, agent)

        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_path), str(dest_path))
            logger.info("Copied %s to %s", src_path, dest_path)
            return {"src": str(src_path), "dest": str(dest_path), "copied": True}
        finally:
            _lock_manager.release_lock(src_str, agent)
            _lock_manager.release_lock(dest_str, agent)
    except PermissionError as e:
        return {"error": str(e)}
    except (LockError, DeadlockError) as e:
        return {"error": f"Lock error: {e}"}
    except Exception as e:
        return {"error": f"Failed to copy file: {e}"}


async def move_file(src: str, dest: str, project_path: str = ".") -> dict:
    """Move or rename files within the project.

    Acquires write locks on both source and destination to prevent
    concurrent corruption.

    Args:
        src: Source file path relative to project root.
        dest: Destination file path relative to project root.
        project_path: Project root path.

    Returns:
        Dict with source, destination, and success status.
    """
    try:
        src_path = _validate_path(project_path, src)
        dest_path = _validate_path(project_path, dest)

        if not src_path.exists():
            return {"error": f"Source file not found: {src}"}

        if src_path.is_dir():
            return {"error": f"Source is a directory, not a file: {src}"}

        if src_path.resolve() == dest_path.resolve():
            return {"error": "Source and destination are the same file"}

        src_str = str(src_path)
        dest_str = str(dest_path)
        agent = "anonymous"

        # Acquire locks in alphabetical order to prevent deadlocks
        for p in sorted([src_str, dest_str]):
            await _lock_manager.acquire_write_lock(p, agent)

        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_path), str(dest_path))
            logger.info("Moved %s to %s", src_path, dest_path)
            return {"src": str(src_path), "dest": str(dest_path), "moved": True}
        finally:
            _lock_manager.release_lock(src_str, agent)
            _lock_manager.release_lock(dest_str, agent)
    except PermissionError as e:
        return {"error": str(e)}
    except (LockError, DeadlockError) as e:
        return {"error": f"Lock error: {e}"}
    except Exception as e:
        return {"error": f"Failed to move file: {e}"}


async def delete_file(path: str, project_path: str = ".") -> dict:
    """Delete files with safety checks.

    Blocks deletion of critical files and directories.

    Args:
        path: File path relative to project root.
        project_path: Project root path.

    Returns:
        Dict with deleted path and success status.
    """
    try:
        full_path = _validate_path(project_path, path)

        if not full_path.exists():
            return {"error": f"File not found: {path}"}

        if full_path.is_dir():
            return {"error": "Use delete_file for files only. Directories are blocked for safety."}

        # Safety check: block deletion of critical config files
        critical_files = {
            ".env",
            ".env.example",
            ".gitignore",
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
            "package.json",
            "Cargo.toml",
            "go.mod",
            "requirements.txt",
            "docker-compose.yml",
            "Dockerfile",
        }
        if full_path.name.lower() in critical_files:
            return {"error": f"Deletion of critical file '{full_path.name}' is blocked for safety"}

        full_path.unlink()
        logger.info("Deleted file %s", full_path)
        return {"path": str(full_path), "deleted": True}
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Failed to delete file: {e}"}


async def delete_directory(path: str, project_path: str = ".", move_to_trash: bool = True) -> dict:
    """Delete a directory recursively with optional trash backup.

    Args:
        path: Directory path relative to project root.
        project_path: Project root path.
        move_to_trash: If True, move to trash instead of permanent deletion.

    Returns:
        Dict with deleted path and success status.
    """
    try:
        full_path = _validate_path(project_path, path)

        if not full_path.exists():
            return {"error": f"Directory not found: {path}"}

        if not full_path.is_dir():
            return {"error": f"Path is not a directory: {path}"}

        # Critical directories should never be deleted accidentally.
        critical_dirs = {".git", ".nexus", "node_modules", ".venv", "__pycache__"}
        if full_path.name.lower() in critical_dirs:
            return {
                "error": (
                    f"Deletion of protected directory '{full_path.name}' is blocked for safety"
                )
            }

        return await delete_dir_absolute(str(full_path), move_to_trash=move_to_trash)
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Failed to delete directory: {e}"}


async def get_file_info(path: str, project_path: str = ".") -> dict:
    """Get metadata for a file or directory.

    Args:
        path: Path relative to project root.
        project_path: Project root path.

    Returns:
        Dict with file/directory metadata.
    """
    try:
        full_path = _validate_path(project_path, path)
        return await get_file_info_absolute(str(full_path))
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Failed to get file info: {e}"}


# Register tools
register_tool(
    ToolSpec(
        name="create_directory",
        description="Create directories (nested supported) within the project workspace",
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to project root",
                },
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
            },
            "required": ["path"],
        },
        handler=create_directory,
    )
)

register_tool(
    ToolSpec(
        name="copy_file",
        description="Copy files within the project workspace",
        schema={
            "type": "object",
            "properties": {
                "src": {
                    "type": "string",
                    "description": "Source file path relative to project root",
                },
                "dest": {
                    "type": "string",
                    "description": "Destination file path relative to project root",
                },
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
            },
            "required": ["src", "dest"],
        },
        handler=copy_file,
    )
)

register_tool(
    ToolSpec(
        name="move_file",
        description="Move or rename files within the project workspace",
        schema={
            "type": "object",
            "properties": {
                "src": {
                    "type": "string",
                    "description": "Source file path relative to project root",
                },
                "dest": {
                    "type": "string",
                    "description": "Destination file path relative to project root",
                },
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
            },
            "required": ["src", "dest"],
        },
        handler=move_file,
    )
)

register_tool(
    ToolSpec(
        name="delete_file",
        description="Delete files with safety checks within the project workspace",
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
        handler=delete_file,
    )
)

register_tool(
    ToolSpec(
        name="delete_directory",
        description="Delete a directory recursively within the project workspace (moves to trash by default)",
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to project root",
                },
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
                "move_to_trash": {
                    "type": "boolean",
                    "default": True,
                    "description": "Move to trash instead of permanent delete",
                },
            },
            "required": ["path"],
        },
        handler=delete_directory,
    )
)

register_tool(
    ToolSpec(
        name="get_file_info",
        description="Get metadata for a file or directory within the project workspace",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to project root"},
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
            },
            "required": ["path"],
        },
        handler=get_file_info,
    )
)
