"""Projects endpoint - manage local projects with sandbox and context."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend.core.workspace_security import _is_blocked_path
from backend.middleware.auth import require_auth
from backend.models.api import ProjectCreateRequest, ProjectUpdateRequest
from backend.persistence.db import (
    create_project,
    delete_project,
    get_project,
    get_project_by_path,
    list_projects,
    update_project,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/projects")
async def list_projects_endpoint(_user: dict = Depends(require_auth)) -> dict:
    """List all projects."""
    projects = list_projects()
    return {"projects": projects}


@router.post("/projects")
async def create_project_endpoint(
    req: ProjectCreateRequest,
    _user: dict = Depends(require_auth),
) -> dict:
    """Create a new project. Creates the directory if it doesn't exist."""
    try:
        project_path = Path(req.path).resolve()

        blocked, reason = _is_blocked_path(str(project_path))
        if blocked:
            raise HTTPException(status_code=400, detail=f"Blocked path: {reason}")

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
        # Bootstrap the project-scoped memory immediately.  It is deliberately
        # a compact local Markdown file, not a copy of the repository.
        try:
            from backend.knowledge.project_memory import ensure_project_memory

            ensure_project_memory(project_path)
        except Exception as exc:
            logger.warning("Project created but bootstrap memory failed: %s", exc)
        return {"project": project}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create project: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/projects/{project_id}")
async def get_project_endpoint(
    project_id: str,
    _user: dict = Depends(require_auth),
) -> dict:
    """Get a specific project."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project}


@router.put("/projects/{project_id}")
async def update_project_endpoint(
    project_id: str,
    req: ProjectUpdateRequest,
    _user: dict = Depends(require_auth),
) -> dict:
    """Update a project (including the trust flag)."""
    fields = {k: v for k, v in req.model_dump().items() if v is not None}

    # ``path`` gets the same validation as creation: an update must not be able
    # to point a project at a blocked location or at a directory that is not
    # there, and it must not create a second row for a path already tracked.
    new_path = fields.get("path")
    if new_path is not None:
        resolved = Path(new_path).resolve()
        blocked, reason = _is_blocked_path(str(resolved))
        if blocked:
            raise HTTPException(status_code=400, detail=f"Blocked path: {reason}")
        if not resolved.is_dir():
            raise HTTPException(status_code=400, detail=f"Path is not a directory: {new_path}")
        duplicate = get_project_by_path(str(resolved))
        if duplicate and duplicate["id"] != project_id:
            raise HTTPException(
                status_code=409,
                detail=f"Another project ('{duplicate['name']}') already uses this path",
            )
        fields["path"] = str(resolved)

    project = update_project(project_id, **fields)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project}


@router.delete("/projects/{project_id}")
async def delete_project_endpoint(
    project_id: str,
    _user: dict = Depends(require_auth),
) -> dict:
    """Delete a project."""
    delete_project(project_id)
    return {"deleted": True}


@router.get("/projects/{project_id}/files")
async def list_project_files(
    project_id: str,
    recursive: bool = False,
    _user: dict = Depends(require_auth),
) -> dict:
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
