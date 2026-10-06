"""Skills marketplace routes for NEXUS IDE — backed by persistent SkillsStore."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.skills_store import SkillsStore
from backend.middleware.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter()

_store = SkillsStore.get_instance()


@router.get("/skills/catalog")
async def runtime_skill_catalog(
    project_path: str = Query(default="", max_length=4096),
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """The same discoverable instructions as the agent's list_skills tool."""
    from backend.core.skill_runtime import list_skill_summaries
    user_id = str(_user.get("user_id") or "")

    resolved_project: str | None = None
    if project_path:
        from pathlib import Path

        from backend.core.workspace_security import _is_blocked_path

        try:
            selected = Path(project_path).expanduser().resolve(strict=True)
            blocked, _reason = _is_blocked_path(str(selected))
            if not selected.is_dir() or blocked:
                raise ValueError("project_path must be a directory")
            resolved_project = str(selected)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid project path") from exc
    skills = await asyncio.to_thread(
        list_skill_summaries,
        resolved_project,
        include_memory=True,
        user_id=user_id,
    )
    return {"skills": skills, "count": len(skills), "source": "runtime_catalog"}


@router.get("/skills")
async def list_skills(
    skill_type: str | None = None,
    tag: str | None = None,
    limit: int = 50,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    user_id = str(_user.get("user_id") or "")
    tags = [tag] if tag else None
    skills = _store.list_skills(
        skill_type=skill_type, tags=tags, limit=limit, user_id=user_id
    )
    return {
        "skills": [
            {
                "id": s.id,
                "name": s.name,
                "type": s.skill_type,
                "description": s.description,
                "confidence": s.confidence,
                "times_used": s.times_used,
                "tags": s.tags,
                "source": s.source,
                "auto_apply": s.auto_apply,
                "updated_at": s.updated_at,
            }
            for s in skills
        ],
        "count": len(skills),
        "stats": _store.stats(user_id=user_id),
    }


@router.get("/skills/search")
async def search_skills(
    q: str,
    limit: int = 10,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    skills = _store.search_skills(
        q, limit=limit, user_id=str(_user.get("user_id") or "")
    )
    return {
        "skills": [
            {
                "id": s.id,
                "name": s.name,
                "type": s.skill_type,
                "description": s.description,
                "confidence": s.confidence,
                "trigger_pattern": s.trigger_pattern,
                "steps": s.steps,
                "tags": s.tags,
            }
            for s in skills
        ],
        "count": len(skills),
    }


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str, _user: dict = Depends(require_auth)) -> dict[str, Any]:
    skill = _store.get_skill(skill_id, user_id=str(_user.get("user_id") or ""))
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {
        "id": skill.id,
        "name": skill.name,
        "type": skill.skill_type,
        "description": skill.description,
        "trigger_pattern": skill.trigger_pattern,
        "steps": skill.steps,
        "verification": skill.verification,
        "tags": skill.tags,
        "confidence": skill.confidence,
        "times_used": skill.times_used,
        "success_count": skill.success_count,
        "fail_count": skill.fail_count,
        "source": skill.source,
        "auto_apply": skill.auto_apply,
        "created_at": skill.created_at,
        "updated_at": skill.updated_at,
    }


@router.post("/skills")
async def create_skill(
    data: dict[str, Any],
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    skill = _store.create_skill(
        name=data.get("name", "Unnamed Skill"),
        skill_type=data.get("type", "workflow"),
        description=data.get("description", ""),
        trigger_pattern=data.get("trigger_pattern", ""),
        steps=data.get("steps", []),
        verification=data.get("verification", ""),
        tags=data.get("tags", []),
        source=data.get("source", "manual"),
        auto_apply=data.get("auto_apply", False),
        user_id=str(_user.get("user_id") or ""),
    )
    return {"id": skill.id, "status": "created", "name": skill.name}


@router.put("/skills/{skill_id}")
async def update_skill(
    skill_id: str,
    data: dict[str, Any],
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    user_id = str(_user.get("user_id") or "")
    skill = _store.get_skill(skill_id, user_id=user_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    # Record use if applicable
    if data.get("record_use"):
        _store.record_use(skill_id, data.get("success", True), user_id=user_id)
    return {"status": "updated"}


@router.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: str,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    ok = _store.delete_skill(skill_id, user_id=str(_user.get("user_id") or ""))
    return {"status": "deleted" if ok else "not_found"}


@router.get("/skills/match/{context}")
async def match_skills(
    context: str,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Find skills that match the given context."""
    skills = _store.find_matching_skills(
        context, user_id=str(_user.get("user_id") or "")
    )
    return {
        "matches": [
            {
                "id": s.id,
                "name": s.name,
                "type": s.skill_type,
                "description": s.description,
                "confidence": s.confidence,
                "steps": s.steps,
                "auto_apply": s.auto_apply,
            }
            for s in skills
        ],
        "count": len(skills),
    }
