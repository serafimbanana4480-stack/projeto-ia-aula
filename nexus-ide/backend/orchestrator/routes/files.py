"""File routes for real local project file operations."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile

from backend.core.workspace_fs import (
    list_dir_absolute,
    read_file_absolute,
    write_file_absolute,
)

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
    if declared not in allowed_types and not any(declared.startswith(a.split("/")[0]) for a in allowed_types):
        logger.warning(
            "Upload content-type mismatch: declared %r for %s (expected one of %r)",
            declared,
            suffix,
            allowed_types,
        )
        # We warn but do NOT block here — content-type is client-supplied and unreliable.

    # 4. Magic-byte verification for binary types
    if suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf"):
        for magic, expected_ext in _MAGIC_SIGNATURES.items():
            if content.startswith(magic):
                if expected_ext == ".webp":
                    # RIFF header: verify WEBP fourcc at offset 8
                    if len(content) >= 12 and content[8:12] == b"WEBP":
                        break
                    continue
                break
        else:
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


@router.post("/files/read")
async def read_file_endpoint(req: FileReadRequest, _user: dict = Depends(require_auth)) -> dict:
    if Path(req.path).is_absolute():
        return await read_file_absolute(req.path)
    return await read_file(path=req.path, project_path=req.project_path)


@router.post("/files/list")
async def list_files_endpoint(req: FileListRequest, _user: dict = Depends(require_auth)) -> dict:
    if Path(req.path).is_absolute():
        result = await list_dir_absolute(req.path, recursive=req.recursive, max_results=5_000)
    else:
        result = await list_dir(path=req.path, project_path=req.project_path, recursive=req.recursive)
    if "error" in result:
        return result

    root = Path(result["path"])
    tree = _build_tree(root, result.get("items", [])) if req.recursive else []
    return {
        "path": result["path"],
        "count": result.get("count", 0),
        "items": result.get("items", []),
        "tree": tree,
    }


@router.post("/files/write")
async def write_file_endpoint(req: FileWriteRequest, _user: dict = Depends(require_auth)) -> dict:
    if Path(req.path).is_absolute():
        return await write_file_absolute(req.path, req.content, overwrite=req.overwrite)
    return await write_file(
        path=req.path,
        content=req.content,
        project_path=req.project_path,
        session_id=req.session_id,
        project_id=req.project_id,
    )


@router.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    project_path: str = ".",
    session_id: str | None = None,
    _user: dict = Depends(require_auth),
) -> dict:
    """Upload a file to the project workspace.

    Files are validated against an extension allowlist, size limit and
    (for binary formats) magic-byte signatures before being written.
    """
    try:
        target_dir = Path(project_path).resolve()
        target_path = target_dir / (file.filename or "unnamed")

        # Path traversal guard
        try:
            target_path.relative_to(target_dir)
        except ValueError:
            return {"error": "Invalid file path — outside project directory"}

        content = await file.read()

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
    except Exception as e:
        logger.exception("Upload failed for %r", getattr(file, "filename", None))
        return {"error": f"Upload failed: {e}"}
