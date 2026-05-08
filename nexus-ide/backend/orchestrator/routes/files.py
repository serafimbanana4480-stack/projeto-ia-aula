"""File routes for real local project file operations."""
from __future__ import annotations

from fastapi import APIRouter

from backend.models.api import FileReadRequest, FileWriteRequest
from backend.tools.file_ops import read_file, write_file

router = APIRouter()


@router.post("/files/read")
async def read_file_endpoint(req: FileReadRequest) -> dict:
    return await read_file(path=req.path, project_path=req.project_path)


@router.post("/files/write")
async def write_file_endpoint(req: FileWriteRequest) -> dict:
    return await write_file(
        path=req.path,
        content=req.content,
        project_path=req.project_path,
        session_id=req.session_id,
        project_id=req.project_id,
    )
