"""File operations tool - read, write, list, search files in project workspace.

CRITICAL: This tool enables agents to modify REAL files on disk, not just output in chat.
Includes sandbox validation to prevent path traversal outside project root.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from backend.persistence.db import propose_change
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


def _validate_path(project_path: str, target_path: str) -> Path:
    """Validate that target_path is within project_path (sandbox)."""
    project = Path(project_path).resolve()
    target = (project / target_path).resolve() if not Path(target_path).is_absolute() else Path(target_path).resolve()
    try:
        target.relative_to(project)
    except ValueError:
        raise PermissionError(f"Path {target} is outside project root {project}")
    return target


async def read_file(path: str, project_path: str = ".") -> dict:
    """Read file contents."""
    try:
        full_path = _validate_path(project_path, path)
        content = full_path.read_text(encoding="utf-8")
        return {"path": str(full_path), "content": content, "size": len(content)}
    except FileNotFoundError:
        return {"error": f"File not found: {path}"}
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Failed to read: {e}"}


async def write_file(path: str, content: str, project_path: str = ".",
                     session_id: Optional[str] = None, project_id: Optional[str] = None) -> dict:
    """Write content to file. Logs as proposed change for audit."""
    try:
        full_path = _validate_path(project_path, path)
        existing = ""
        if full_path.exists():
            existing = full_path.read_text(encoding="utf-8")
        
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        
        if session_id:
            propose_change(
                session_id=session_id,
                project_id=project_id,
                file_path=str(full_path.relative_to(Path(project_path).resolve())),
                operation="modify" if existing else "create",
                new_content=content,
            )
        
        return {"path": str(full_path), "written": True, "size": len(content)}
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Failed to write: {e}"}


async def list_dir(path: str = ".", project_path: str = ".", recursive: bool = False) -> dict:
    """List directory contents."""
    try:
        full_path = _validate_path(project_path, path)
        if not full_path.exists():
            return {"error": f"Path not found: {path}"}
        
        if recursive:
            items = []
            for item in full_path.rglob("*"):
                items.append({
                    "path": str(item.relative_to(Path(project_path).resolve())),
                    "type": "file" if item.is_file() else "dir",
                    "size": item.stat().st_size if item.is_file() else 0,
                })
        else:
            items = []
            for item in full_path.iterdir():
                items.append({
                    "path": str(item.relative_to(Path(project_path).resolve())),
                    "type": "file" if item.is_file() else "dir",
                    "size": item.stat().st_size if item.is_file() else 0,
                })
        
        return {"path": str(full_path), "items": items, "count": len(items)}
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Failed to list: {e}"}


async def search_in_files(query: str, project_path: str = ".", file_pattern: str = "*.py") -> dict:
    """Search for text in files."""
    try:
        project = Path(project_path).resolve()
        results = []
        
        for file_path in project.rglob(file_pattern):
            if file_path.is_file():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    if query.lower() in content.lower():
                        lines = content.split("\n")
                        matches = [(i+1, line) for i, line in enumerate(lines) if query.lower() in line.lower()]
                        if matches:
                            results.append({
                                "path": str(file_path.relative_to(project)),
                                "matches": len(matches),
                                "preview": matches[:3],
                            })
                except Exception:
                    continue
        
        return {"query": query, "results": results, "count": len(results)}
    except Exception as e:
        return {"error": f"Failed to search: {e}"}


# Register tools
register_tool(ToolSpec(
    name="read_file",
    description="Read the contents of a file from the project workspace",
    schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to project root"},
            "project_path": {"type": "string", "default": ".", "description": "Project root path"},
        },
        "required": ["path"],
    },
    handler=read_file,
))

register_tool(ToolSpec(
    name="write_file",
    description="Write content to a file in the project workspace. Logs as proposed change.",
    schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to project root"},
            "content": {"type": "string", "description": "Content to write"},
            "project_path": {"type": "string", "default": ".", "description": "Project root path"},
        },
        "required": ["path", "content"],
    },
    handler=write_file,
))

register_tool(ToolSpec(
    name="list_dir",
    description="List files and directories in a path",
    schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": ".", "description": "Path to list"},
            "project_path": {"type": "string", "default": ".", "description": "Project root path"},
            "recursive": {"type": "boolean", "default": False, "description": "Recursive listing"},
        },
    },
    handler=list_dir,
))

register_tool(ToolSpec(
    name="search_in_files",
    description="Search for text in files matching a pattern",
    schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Text to search for"},
            "project_path": {"type": "string", "default": ".", "description": "Project root path"},
            "file_pattern": {"type": "string", "default": "*.py", "description": "File pattern (glob)"},
        },
        "required": ["query"],
    },
    handler=search_in_files,
))
