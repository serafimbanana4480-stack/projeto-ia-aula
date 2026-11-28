"""File operations tool — thin wrapper around backend.tools.file_api for backward compatibility.

Delegates filesystem operations to :class:`backend.tools.file_api` while
preserving shared/exclusive file locks for concurrent safety and legacy
behaviour such as trust checks and audit logging (``propose_change``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.core.file_locks import FileLockManager
from backend.core.workspace import WorkspaceManager
from backend.persistence.db import propose_change
from backend.tools.file_api import (
    list_files as _list,
)
from backend.tools.file_api import (
    read as _read,
)
from backend.tools.file_api import (
    read_multiple as _read_multiple,
)
from backend.tools.file_api import (
    search as _search,
)
from backend.tools.file_api import (
    write as _write,
)
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


#: Editing is a read-modify-write over the whole file. A huge file would spend
#: the agent's context (and memory) before any edit happens; such files need a
#: shell/script edit instead.
_MAX_EDIT_BYTES = 2 * 1024 * 1024


def _slice_content_window(
    result: dict[str, Any], offset: int | None, limit: int | None
) -> dict[str, Any]:
    """Apply a 0-based line window to a read result.

    ``read_file`` used to return whole files only. The tool-result budget then
    truncated the middle of anything larger than a few thousand characters and
    told the model to "call the tool again with offset/limit" — parameters the
    tool did not have, so the omitted region was unreachable. Paging fixes that
    and keeps a large file from consuming the context in one call.
    """
    start = max(0, int(offset or 0))
    max_lines = int(limit or 0)
    if start == 0 and max_lines <= 0:
        return result
    content = result.get("content")
    if not isinstance(content, str):
        return result
    lines = content.splitlines(keepends=True)
    total = len(lines)
    end = total if max_lines <= 0 else min(total, start + max_lines)
    windowed = dict(result)
    windowed["content"] = "".join(lines[start:end])
    windowed["total_lines"] = total
    windowed["offset"] = start
    windowed["returned_lines"] = max(0, end - start)
    windowed["next_offset"] = end if end < total else None
    if start >= total:
        windowed["note"] = (
            f"offset {start} is past the end of the file ({total} lines); "
            "content is empty."
        )
    return windowed


async def read_file(
    path: str,
    project_path: str = ".",
    owner: str = "anonymous",
    timeout_seconds: float = 30.0,
    offset: int = 0,
    limit: int | None = None,
) -> dict[str, Any]:
    """Read file contents, optionally a line window (0-based offset)."""
    result = await _read(
        path,
        project_path=project_path,
        owner=owner,
        timeout_seconds=timeout_seconds,
    )
    return _slice_content_window(result, offset, limit)


async def write_file(
    path: str,
    content: str,
    project_path: str = ".",
    session_id: str | None = None,
    project_id: str | None = None,
    owner: str = "anonymous",
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Write content to file. Logs as proposed change for audit.

    Trust check: writes to a project that is not trusted are blocked, with or
    without a session. An interactive session is not consent: the agent runs
    with one on every turn, so honouring it turned the gate into a no-op (QA
    C4). The refusal carries the data the UI needs to offer a one-click grant.

    Backward-compatible wrapper around ``file_api.write`` with legacy
    trust verification and ``propose_change`` logging.
    """
    manager = WorkspaceManager(project_path)
    try:
        full_path = manager._resolve_path(path)
    except PermissionError as exc:
        return {"error": str(exc)}

    # Block dangerous executable extensions
    if full_path.suffix.lower() in _BLOCKED_EXTENSIONS:
        return {
            "error": (f"Writing files with extension '{full_path.suffix}' is blocked for security")
        }

    # Trust verification — block writes to untrusted projects
    from backend.persistence.db import get_project_by_path

    project = get_project_by_path(str(Path(project_path).resolve()))
    if project and not project.get("trust", False):
        return {
            "error": (
                f"Project '{project['name']}' is NOT trusted, so the file was NOT "
                "written. Grant trust in Projects -> Edit -> Trust (or "
                f"PUT /api/projects/{project['id']} with {{\"trust\": true}}) and "
                "run the tool again."
            ),
            "requires_trust": True,
            "project_id": project["id"],
            "project_name": project["name"],
            "project_path": project["path"],
            "trust_endpoint": f"/api/projects/{project['id']}",
        }

    result = await _write(
        path,
        content,
        project_path=project_path,
        owner=owner,
        timeout_seconds=timeout_seconds,
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


def _apply_edit(
    content: str, old_text: str, new_text: str, replace_all: bool
) -> tuple[str, int, str]:
    """Replace *old_text* in *content*, tolerating newline-style differences.

    Models routinely emit ``\\n`` for a file that uses CRLF, so an exact
    match-only tool fails on every Windows checkout. The exact replacement is
    tried first; when that misses, both sides are normalised for matching and
    the result is converted back to the file's original newline style.

    Returns ``(updated_content, replacements, newline_style)``.
    """
    occurrences = content.count(old_text)
    if occurrences:
        # Always report the real occurrence count. The caller refuses an
        # ambiguous edit (occurrences > 1 without replace_all); reporting 1
        # here made that check unreachable, so the first match was silently
        # rewritten instead (found 2026-11-21 while validating edit_file).
        updated = content.replace(old_text, new_text, -1 if replace_all else 1)
        return updated, occurrences, "exact"

    if "\r\n" not in content and "\r" not in content:
        return content, 0, "exact"
    style = "\r\n" if "\r\n" in content else "\r"
    normalized_content = content.replace("\r\n", "\n").replace("\r", "\n")
    normalized_old = old_text.replace("\r\n", "\n").replace("\r", "\n")
    occurrences = normalized_content.count(normalized_old)
    if not occurrences:
        return content, 0, "exact"
    normalized_new = new_text.replace("\r\n", "\n").replace("\r", "\n")
    updated = normalized_content.replace(normalized_old, normalized_new, -1 if replace_all else 1)
    return updated.replace("\n", style), occurrences, style


async def edit_file(
    path: str,
    old_text: str,
    new_text: str,
    project_path: str = ".",
    replace_all: bool = False,
    session_id: str | None = None,
    project_id: str | None = None,
    owner: str = "anonymous",
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Replace an exact snippet inside an existing file.

    This is the surgical edit path for agents. Without it the only way to
    change one line was ``write_file`` with the complete new contents, which
    makes a small local model re-emit the whole file (token cost, truncation
    risk, and formatting drift). The snippet must be unique unless
    ``replace_all`` is true, so an ambiguous edit fails loudly instead of
    silently changing the wrong occurrence.
    """
    if not isinstance(old_text, str) or not old_text:
        return {"error": "old_text must be a non-empty string"}

    current = await _read(
        path,
        project_path=project_path,
        owner=owner,
        timeout_seconds=timeout_seconds,
    )
    if "error" in current:
        return current
    content = current.get("content") or ""
    if len(content) > _MAX_EDIT_BYTES:
        return {
            "error": (
                f"File is too large to edit in memory ({len(content)} bytes). "
                "Use a script via execute_code or a shell edit instead."
            ),
            "path": current.get("path", path),
        }

    updated, replacements, newline_style = _apply_edit(
        content, old_text, new_text, bool(replace_all)
    )
    if replacements == 0:
        return {
            "error": (
                "old_text was not found in the file. Read the file and copy the "
                "snippet exactly (including indentation), or use write_file for a "
                "full rewrite."
            ),
            "path": current.get("path", path),
            "replaced": False,
        }
    if replacements > 1 and not replace_all:
        return {
            "error": (
                f"old_text occurs {replacements} times; the edit was not applied. "
                "Pass a longer snippet that is unique, or set replace_all=true."
            ),
            "path": current.get("path", path),
            "replaced": False,
            "occurrences": replacements,
        }

    result = await write_file(
        path,
        updated,
        project_path=project_path,
        session_id=session_id,
        project_id=project_id,
        owner=owner,
        timeout_seconds=timeout_seconds,
    )
    if "error" in result:
        return result
    return {
        **result,
        "replaced": True,
        "replacements": replacements,
        "newline_style": newline_style,
    }


async def read_multiple_files(
    paths: list[str],
    project_path: str = ".",
    owner: str = "anonymous",
    timeout_seconds: float = 30.0,
    max_total_bytes: int = 5 * 1024 * 1024,
    max_files: int = 100,
) -> dict[str, Any]:
    """Read multiple files in one call. Backward-compatible wrapper."""
    return await _read_multiple(
        paths,
        project_path=project_path,
        owner=owner,
        timeout_seconds=timeout_seconds,
        max_total_bytes=max_total_bytes,
        max_files=max_files,
    )


async def list_dir(
    path: str = ".", project_path: str = ".", recursive: bool = False
) -> dict[str, Any]:
    """List directory contents. Backward-compatible wrapper."""
    return await _list(path, project_path=project_path, recursive=recursive)


async def search_in_files(
    query: str, project_path: str = ".", file_pattern: str = "*"
) -> dict[str, Any]:
    """Search for text in files. Backward-compatible wrapper.

    The old default (``*.py``) made a search silently miss every Markdown,
    JSON, TypeScript or config file unless the model remembered to widen the
    pattern. Searching everything text-like is the useful default; callers
    that want one language still pass an explicit pattern.
    """
    return await _search(
        query,
        path=".",
        project_path=project_path,
        file_pattern=file_pattern,
    )


# Register tools
register_tool(
    ToolSpec(
        name="read_file",
        description=(
            "Read the contents of a file from the project workspace. For large "
            "files use offset/limit to read a line window (0-based offset) "
            "instead of the whole file."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to project root"},
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "0-based line index to start reading from",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Maximum number of lines to return. Omit to read to the "
                        "end of the file."
                    ),
                },
            },
            "required": ["path"],
        },
        handler=read_file,
    )
)

register_tool(
    ToolSpec(
        name="read_multiple_files",
        description="Read multiple files from the project workspace in one call",
        schema={
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths relative to project root",
                },
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
                "max_total_bytes": {
                    "type": "integer",
                    "default": 5 * 1024 * 1024,
                    "description": "Maximum combined bytes to return",
                },
                "max_files": {
                    "type": "integer",
                    "default": 100,
                    "description": "Maximum number of files to read",
                },
            },
            "required": ["paths"],
        },
        handler=read_multiple_files,
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
        name="edit_file",
        description=(
            "Replace an exact snippet in an existing file. Prefer this over "
            "write_file when changing part of a file: only old_text is sent, "
            "not the whole new file. old_text must be unique unless "
            "replace_all is true."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to project root",
                },
                "old_text": {
                    "type": "string",
                    "description": (
                        "Exact existing text to replace, including indentation. "
                        "Keep it unique; include surrounding lines when needed."
                    ),
                },
                "new_text": {
                    "type": "string",
                    "description": "Replacement text (may be empty to delete the snippet)",
                },
                "replace_all": {
                    "type": "boolean",
                    "default": False,
                    "description": "Replace every occurrence instead of requiring a unique match",
                },
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
            },
            "required": ["path", "old_text", "new_text"],
        },
        category="file",
        tags=["file", "write", "edit", "fs"],
        risk="medium",
        when_to_use=(
            "Make a targeted change to an existing file: rename a symbol, change "
            "a line, insert or remove a block. Read the file first so old_text "
            "matches exactly."
        ),
        handler=edit_file,
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
        description=(
            "Search for literal text across project files (grep-style, case "
            "insensitive). Use it to find where a symbol, string or error "
            "message appears before reading whole files."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Literal text to search for",
                },
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
                "file_pattern": {
                    "type": "string",
                    "default": "*",
                    "description": (
                        "Glob filter for file names, e.g. '*.py' or '*.tsx'. "
                        "Defaults to all files."
                    ),
                },
            },
            "required": ["query"],
        },
        handler=search_in_files,
    )
)

# ---------------------------------------------------------------------------
# Absolute-path tools — used by agents via auto-upgrade (base.py:857-872)
# Bypass project_path resolution for direct filesystem access.
# ---------------------------------------------------------------------------


async def _read_file_absolute_handler(
    path: str,
    max_size: int | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> dict[str, Any]:
    """Read a file at an absolute path with security checks.

    Bypasses ``project_path`` resolution by delegating directly to
    ``workspace_fs.read_file_absolute``, which validates against the
    global allowed-base blocklist.
    """
    from backend.core.workspace_fs import read_file_absolute as _read_abs

    result = await _read_abs(path)
    if max_size is not None and "error" not in result:
        content = result.get("content", "")
        if len(content) > max_size:
            result["content"] = content[:max_size]
            result["truncated"] = True
            result["original_size"] = len(content)
    return _slice_content_window(result, offset, limit)


async def _write_file_absolute_handler(
    path: str,
    content: str,
    create_dirs: bool = True,
) -> dict[str, Any]:
    """Write a file at an absolute path with workspace security.

    Delegates to ``workspace_fs.write_file_absolute``, which enforces
    the global allowed-base blocklist, creates backups, and runs
    write-back verification.  Parent directories are created on demand
    (``mkdir -p`` behaviour) when *create_dirs* is ``True``.
    """
    from backend.core.workspace_fs import write_file_absolute as _write_abs

    if create_dirs:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    return await _write_abs(path, content)


async def _list_dir_absolute_handler(
    path: str,
    recursive: bool = False,
    max_results: int = 10_000,
    include_hidden: bool = True,
    include_files: bool = True,
    include_dirs: bool = True,
    glob_pattern: str | None = None,
) -> dict[str, Any]:
    """List a directory at an absolute path.

    Delegates to ``workspace_fs.list_dir_absolute`` with the same
    security and recursion behaviour.

    The full parameter set is exposed deliberately. The wrapper used to accept
    only ``path``/``recursive`` while the underlying function supported six
    parameters, so a model that (correctly) inferred ``include_hidden`` from
    the behaviour got a raw ``TypeError`` — see session bf1e9435b9ec47c9,
    DEBUGGER iteration 6. Narrowing a signature at the tool boundary hides
    capability and converts a valid call into a hard failure.
    """
    from backend.core.workspace_fs import list_dir_absolute as _list_abs

    return await _list_abs(
        path,
        recursive=recursive,
        max_results=max_results,
        include_hidden=include_hidden,
        include_files=include_files,
        include_dirs=include_dirs,
        glob_pattern=glob_pattern,
    )


register_tool(ToolSpec(
    name="read_file_absolute",
    description=(
        "Read a file using an absolute path (bypasses project_path resolution). "
        "For large files use offset/limit (0-based line offset)."
    ),
    schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file"},
            "max_size": {"type": "integer", "description": "Max content size in bytes (default: no limit)"},
            "offset": {
                "type": "integer",
                "minimum": 0,
                "default": 0,
                "description": "0-based line index to start reading from",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum number of lines to return (omit for the whole file)",
            },
        },
        "required": ["path"],
    },
    handler=_read_file_absolute_handler,
))

register_tool(ToolSpec(
    name="write_file_absolute",
    description="Write a file at an absolute path. Subject to workspace security checks.",
    schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file"},
            "content": {"type": "string", "description": "File content"},
            "create_dirs": {
                "type": "boolean",
                "description": "Create parent dirs if missing",
                "default": True,
            },
        },
        "required": ["path", "content"],
    },
    handler=_write_file_absolute_handler,
))

register_tool(ToolSpec(
    name="list_dir_absolute",
    description="List files/directories at an absolute path.",
    schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute directory path"},
            "recursive": {
                "type": "boolean",
                "description": "Recurse into subdirectories",
                "default": False,
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum entries to return",
                "default": 10000,
            },
            "include_hidden": {
                "type": "boolean",
                "description": "Include entries whose name starts with '.'",
                "default": True,
            },
            "include_files": {
                "type": "boolean",
                "description": "Include files in the listing",
                "default": True,
            },
            "include_dirs": {
                "type": "boolean",
                "description": "Include directories in the listing",
                "default": True,
            },
            "glob_pattern": {
                "type": "string",
                "description": "Optional glob filter, e.g. '*.py'",
            },
        },
        "required": ["path"],
    },
    handler=_list_dir_absolute_handler,
))
