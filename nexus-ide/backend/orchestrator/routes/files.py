"""File routes for real local project file operations."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from backend.models.api import FileListRequest, FileReadRequest, FileTreeEntry, FileWriteRequest
from backend.tools.file_ops import list_dir, read_file, write_file

router = APIRouter()


def _build_tree(root: Path, items: list[dict]) -> list[FileTreeEntry]:
    nodes: dict[tuple[str, ...], FileTreeEntry] = {}
    entries: list[FileTreeEntry] = []

    for item in sorted(items, key=lambda row: row["path"]):
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
async def read_file_endpoint(req: FileReadRequest) -> dict:
    return await read_file(path=req.path, project_path=req.project_path)


@router.post("/files/list")
async def list_files_endpoint(req: FileListRequest) -> dict:
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
async def write_file_endpoint(req: FileWriteRequest) -> dict:
    return await write_file(
        path=req.path,
        content=req.content,
        project_path=req.project_path,
        session_id=req.session_id,
        project_id=req.project_id,
    )
