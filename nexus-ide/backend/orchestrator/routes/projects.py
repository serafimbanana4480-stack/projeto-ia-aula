"""Projects endpoint - manage local projects with sandbox and context."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.models.api import ProjectCreateRequest, ProjectUpdateRequest
from backend.persistence.db import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    update_project,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/projects")
async def list_projects_endpoint() -> dict:
    """List all projects."""
    projects = list_projects()
    return {"projects": projects}


@router.post("/projects")
async def create_project_endpoint(req: ProjectCreateRequest) -> dict:
    """Create a new project. Creates the directory if it doesn't exist."""
    try:
        project_path = Path(req.path).resolve()

        # Create directory if it doesn't exist
        if not project_path.exists():
            project_path.mkdir(parents=True, exist_ok=True)
            logger.info("Created project directory: %s", project_path)

        if not project_path.is_dir():
            raise HTTPException(status_code=400, detail=f"Path is not a directory: {req.path}")

        project = create_project(
            name=req.name,
            path=str(project_path),
            description=req.description,
            mode=req.mode,
            preferred_model=req.preferred_model,
            trust=req.trust,
        )
        return {"project": project}
    except Exception as e:
        logger.error(f"Failed to create project: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/projects/{project_id}")
async def get_project_endpoint(project_id: str) -> dict:
    """Get a specific project."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project}


@router.put("/projects/{project_id}")
async def update_project_endpoint(project_id: str, req: ProjectUpdateRequest) -> dict:
    """Update a project."""
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    project = update_project(project_id, **fields)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project}


@router.delete("/projects/{project_id}")
async def delete_project_endpoint(project_id: str) -> dict:
    """Delete a project."""
    delete_project(project_id)
    return {"deleted": True}


@router.get("/projects/{project_id}/files")
async def list_project_files(project_id: str, recursive: bool = False) -> dict:
    """List files in a project (sandboxed)."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        project_path = Path(project["path"]).resolve()
        if not project_path.exists():
            return {"files": [], "error": "Project path does not exist"}

        files = []
        if recursive:
            for item in project_path.rglob("*"):
                if item.is_file():
                    files.append(
                        {
                            "path": str(item.relative_to(project_path)),
                            "size": item.stat().st_size,
                            "type": "file",
                        }
                    )
        else:
            for item in project_path.iterdir():
                files.append(
                    {
                        "path": item.name,
                        "size": item.stat().st_size if item.is_file() else 0,
                        "type": "file" if item.is_file() else "dir",
                    }
                )

        return {"files": files, "count": len(files)}
    except Exception as e:
        logger.error(f"Failed to list files: {e}")
        return {"files": [], "error": str(e)}
