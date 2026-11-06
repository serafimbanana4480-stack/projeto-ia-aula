"""File routes for real local project file operations.

Project boundary
----------------
The client does not choose the filesystem root this API works in.

``project_path`` used to be taken at face value, and an **absolute** request
path skipped the project sandbox entirely (only the global blocklist
applied), so any registered user could read and write anywhere under the
host user's home directory.

The root is now chosen by the server:

* a ``project_path`` that names a project the instance knows — a row in
  ``projects`` — is accepted, because the file explorer legitimately works
  on a project the user picked;
* anything else is refused with ``400``: the client cannot point the API at
  an arbitrary directory;
* without a ``project_path`` the caller's own session project is used, then
  the instance's default project, then the backend's working directory.

Whatever the root is, every path the request touches has to resolve **inside**
it — the same rule the tool registry applies to a tool's path arguments.  The
``*_absolute`` helpers, which bypass the project sandbox by design, are
therefore not used here any more.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from backend.core.workspace_security import _is_blocked_path
from backend.middleware.auth import require_auth
from backend.models.api import FileListRequest, FileReadRequest, FileTreeEntry, FileWriteRequest
from backend.tools.file_ops import list_dir, read_file, write_file

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Upload security constants
# ---------------------------------------------------------------------------
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB

# Allowed extensions → expected MIME type prefixes (first match wins)
_UPLOAD_ALLOWLIST: dict[str, list[str]] = {
    # Code & markup
    ".py": ["text/x-python", "text/plain"],
    ".js": ["text/javascript", "application/javascript", "text/plain"],
    ".ts": ["text/plain", "application/typescript"],
    ".tsx": ["text/plain"],
    ".jsx": ["text/javascript", "text/plain"],
    ".html": ["text/html", "text/plain"],
    ".htm": ["text/html", "text/plain"],
    ".css": ["text/css", "text/plain"],
    ".scss": ["text/plain", "text/x-scss"],
    ".sass": ["text/plain", "text/x-sass"],
    ".json": ["application/json", "text/plain"],
    ".yaml": ["text/plain", "application/x-yaml"],
    ".yml": ["text/plain", "application/x-yaml"],
    ".xml": ["text/xml", "application/xml", "text/plain"],
    ".md": ["text/markdown", "text/plain"],
    ".rst": ["text/plain"],
    ".txt": ["text/plain"],
    ".cfg": ["text/plain"],
    ".ini": ["text/plain"],
    ".toml": ["text/plain"],
    # Images
    ".png": ["image/png"],
    ".jpg": ["image/jpeg"],
    ".jpeg": ["image/jpeg"],
    ".gif": ["image/gif"],
    ".svg": ["image/svg+xml", "text/plain"],
    ".webp": ["image/webp"],
    ".ico": ["image/x-icon", "image/vnd.microsoft.icon"],
    # Data / config
    ".csv": ["text/csv", "text/plain"],
    ".sql": ["text/plain", "application/sql"],
    ".sh": ["text/x-shellscript", "text/plain"],
    ".bat": ["text/plain"],
    ".ps1": ["text/plain"],
    ".dockerfile": ["text/plain"],
    ".env": ["text/plain"],
    ".gitignore": ["text/plain"],
    # Documentation
    ".pdf": ["application/pdf"],
}

# Magic bytes for common file types (first 8 bytes max)
_MAGIC_SIGNATURES: dict[bytes, str] = {
    b"\x89PNG\r\n\x1a\n": ".png",
    b"\xff\xd8\xff": ".jpg",
    b"GIF87a": ".gif",
    b"GIF89a": ".gif",
    b"\x00\x00\x01\x00": ".ico",
    b"\x00\x00\x02\x00": ".ico",
    b"RIFF": ".webp",  # RIFF....WEBP
    b"%PDF": ".pdf",
    b"<?xml ": ".xml",
    b"{": ".json",
}


def _validate_upload(file: UploadFile, content: bytes) -> tuple[bool, str]:
    """Validate an uploaded file against size, extension and magic-byte rules.

    Returns:
        ``(True, "")`` if the upload is acceptable, otherwise ``(False, reason)``.
    """
    # 1. Size check
    if len(content) > _MAX_UPLOAD_BYTES:
        return False, f"File exceeds maximum upload size ({_MAX_UPLOAD_BYTES / 1024 / 1024:.0f} MB)"

    # 2. Extension check
    if file.filename is None:
        return False, "Missing filename"

    suffix = Path(file.filename).suffix.lower()
    if suffix not in _UPLOAD_ALLOWLIST:
        return False, f"File extension '{suffix}' is not in the upload allowlist"

    # 3. Content-Type consistency (best-effort)
    declared = (file.content_type or "application/octet-stream").lower()
    allowed_types = [t.lower() for t in _UPLOAD_ALLOWLIST[suffix]]
    if declared not in allowed_types and not any(
        declared.startswith(a.split("/")[0]) for a in allowed_types
    ):
        logger.warning(
            "Upload content-type mismatch: declared %r for %s (expected one of %r)",
            declared,
            suffix,
            allowed_types,
        )
        # We warn but do NOT block here — content-type is client-supplied and unreliable.

    # 4. Magic-byte verification for binary types
    if suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf"):
        matched = False
        for magic, expected_ext in _MAGIC_SIGNATURES.items():
            if not content.startswith(magic):
                continue
            if expected_ext == ".webp":
                # RIFF header: require WEBP fourcc at offset 8
                if len(content) >= 12 and content[8:12] == b"WEBP":
                    if suffix == ".webp":
                        matched = True
                        break
                    return (
                        False,
                        f"File content ({expected_ext}) does not match expected format for {suffix}",
                    )
                # RIFF but not WEBP (e.g. WAV/AVI) — keep scanning other signatures
                continue
            # General case: magic matched a non-WEBP binary format
            if expected_ext == suffix:
                matched = True
                break
            # Normalize .jpg/.jpeg aliasing
            if expected_ext == ".jpg" and suffix == ".jpeg":
                matched = True
                break
            if expected_ext == ".jpeg" and suffix == ".jpg":
                matched = True
                break
            return (
                False,
                f"File content ({expected_ext}) does not match expected format for {suffix}",
            )
        if not matched:
            return False, f"File content does not match expected format for {suffix}"

    return True, ""


def _build_tree(root: Path, items: list[dict]) -> list[FileTreeEntry]:
    nodes: dict[tuple[str, ...], FileTreeEntry] = {}
    entries: list[FileTreeEntry] = []

    for item in sorted(items, key=lambda row: row["path"]):
        try:
            relative = Path(item["path"]).relative_to(root)
        except ValueError:
            relative = Path(item["path"])
        parts = relative.parts
        node = FileTreeEntry(
            path=item["path"],
            name=relative.name,
            type="file" if item["type"] == "file" else "directory",
            size=item.get("size", 0),
        )
        nodes[parts] = node
        if len(parts) == 1:
            entries.append(node)

    for parts, node in sorted(nodes.items(), key=lambda pair: len(pair[0])):
        if len(parts) == 1:
            continue
        parent = nodes.get(parts[:-1])
        if parent is not None:
            parent.children.append(node)

    return entries


# ---------------------------------------------------------------------------
# Project boundary
# ---------------------------------------------------------------------------


def _resolve(path: Path) -> Path:
    """The canonical form of *path* (symlinks resolved, ``~`` expanded)."""
    try:
        return path.expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Path cannot be resolved: {path}") from exc


def _known_project(path: Path) -> dict | None:
    """The registered project containing *path*, when the instance knows it."""
    from backend.persistence.db import get_project_by_path, list_projects

    try:
        project = get_project_by_path(str(path))
        if project is not None:
            return project
        target = os.path.normcase(str(path))
        for candidate in list_projects():
            try:
                resolved = os.path.normcase(str(_resolve(Path(candidate["path"]))))
            except (OSError, RuntimeError, ValueError, HTTPException):
                continue
            try:
                common = os.path.commonpath((target, resolved))
            except ValueError:
                continue
            if common == resolved:
                return candidate
    except Exception:
        logger.warning("Could not look up the project for %s", path, exc_info=True)
    return None


def _session_project(session_id: str | None, user_id: str) -> dict | None:
    """The project of the caller's own session."""
    from backend.persistence.db import get_project, get_session_for_user

    if not session_id or not user_id:
        return None
    try:
        session = get_session_for_user(session_id, user_id)
        if not session:
            return None
        project_id = session.get("project_id")
        if not project_id:
            return None
        return get_project(project_id)
    except Exception:
        logger.warning("Could not read the project of session %s", session_id, exc_info=True)
        return None


def _default_project() -> dict | None:
    """The instance's default project (the first one registered)."""
    from backend.persistence.db import list_projects

    try:
        projects = list_projects()
    except Exception:
        logger.warning("Could not list the projects", exc_info=True)
        return None
    return projects[0] if projects else None


def _resolve_project_root(
    requested: str,
    session_id: str | None = None,
    user_id: str = "",
) -> Path:
    """The project root this request may work in — chosen by the server.

    A ``project_path`` inside a project this instance knows is honoured. This
    also allows the editor's frontend/backend/config presets to use a
    subdirectory as their working root. Anything outside registered roots is
    refused: the client cannot choose an arbitrary filesystem location.
    """
    text = (requested or "").strip()
    if text and text not in {".", "./", ".\\"}:
        candidate = _resolve(Path(text))
        if _known_project(candidate) is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "project_path must be inside a project this instance knows. Register it "
                    "with POST /api/projects first — the API will not operate on an "
                    "arbitrary directory."
                ),
            )
        return candidate

    project = _session_project(session_id, user_id) or _default_project()
    if project and project.get("path"):
        return _resolve(Path(project["path"]))
    return _resolve(Path.cwd())


def _relative_inside(root: Path, path: str) -> str | None:
    """*path* relative to *root*, or ``None`` when it escapes the project.

    Mirrors the tool registry's project rule: a relative path is resolved
    against the project root, an absolute one is accepted only when it is
    inside the root, and ``..`` cannot climb out of it.
    """
    raw = Path(path).expanduser()
    if ".." in raw.parts:
        return None
    try:
        target = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    try:
        relative = target.relative_to(root)
    except ValueError:
        return None
    return str(relative) if str(relative) != "." else "."


def _outside_project_error(root: Path, path: str) -> dict:
    """The error body for a path that is not inside the project root."""
    return {
        "error": (
            f"Access not allowed — path {path} is outside the project root {root}. "
            "The project root is chosen by the server, not by the request."
        )
    }


@router.post("/files/read")
async def read_file_endpoint(req: FileReadRequest, _user: dict = Depends(require_auth)) -> dict:
    """Read a file from the caller's project.

    The project root is chosen by the server and the path has to resolve
    inside it; an absolute path outside the project is refused instead of
    being read.
    """
    root = _resolve_project_root(req.project_path, None, str(_user.get("user_id") or ""))
    relative = _relative_inside(root, req.path)
    if relative is None:
        return _outside_project_error(root, req.path)
    return await read_file(path=relative, project_path=str(root))


@router.post("/files/list")
async def list_files_endpoint(req: FileListRequest, _user: dict = Depends(require_auth)) -> dict:
    """List a directory of the caller's project."""
    root = _resolve_project_root(req.project_path, None, str(_user.get("user_id") or ""))
    relative = _relative_inside(root, req.path)
    if relative is None:
        return _outside_project_error(root, req.path)
    result = await list_dir(
        path=relative, project_path=str(root), recursive=req.recursive
    )
    if "error" in result:
        return result

    tree_root = Path(result["path"])
    tree = _build_tree(tree_root, result.get("items", [])) if req.recursive else []
    return {
        "path": result["path"],
        "count": result.get("count", 0),
        "items": result.get("items", []),
        "tree": tree,
    }


@router.post("/files/write")
async def write_file_endpoint(req: FileWriteRequest, _user: dict = Depends(require_auth)) -> dict:
    """Write a file inside the caller's project."""
    user_id = str(_user.get("user_id") or "")
    root = _resolve_project_root(req.project_path, req.session_id, user_id)
    relative = _relative_inside(root, req.path)
    if relative is None:
        return _outside_project_error(root, req.path)
    return await write_file(
        path=relative,
        content=req.content,
        project_path=str(root),
        session_id=req.session_id,
        project_id=req.project_id,
    )


@router.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    project_path: str = Form("."),
    session_id: str | None = Form(None),
    _user: dict = Depends(require_auth),
) -> dict:
    """Upload a file to the project workspace.

    Files are validated against an extension allowlist, size limit and
    (for binary formats) magic-byte signatures before being written, and
    the destination directory is the project root the server resolved — not
    a directory the request names.
    """
    try:
        root = _resolve_project_root(project_path, session_id, str(_user.get("user_id") or ""))
        blocked, reason = _is_blocked_path(str(root))
        if blocked:
            return {"error": reason}

        target_dir = root
        target_path = target_dir / (file.filename or "unnamed")

        # Path traversal guard. We must compare the *resolved* paths so the
        # ``..`` segments in the user-supplied filename are normalised before
        # the relative_to check — a string-level relative_to would let
        # ``../../etc/passwd`` pass.
        try:
            target_path.resolve().relative_to(target_dir)
        except ValueError:
            return {"error": "Invalid file path — outside project directory"}

        # Read at most one byte past the accepted limit. This lets the
        # existing validator reject oversized uploads without materializing
        # an unbounded request body in process memory.
        content = await file.read(_MAX_UPLOAD_BYTES + 1)

        # Security validation
        ok, reason = _validate_upload(file, content)
        if not ok:
            logger.warning("Upload rejected for %r: %s", file.filename, reason)
            return {"error": reason}

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)

        return {
            "filename": file.filename,
            "path": str(target_path),
            "size": len(content),
            "content_type": file.content_type,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Upload failed for %r", getattr(file, "filename", None))
        return {"error": f"Upload failed: {e}"}
