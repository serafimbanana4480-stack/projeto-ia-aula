"""Skills marketplace routes for NEXUS IDE — backed by persistent SkillsStore."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from backend.core.skills_store import SkillsStore
from backend.middleware.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter()

_store = SkillsStore.get_instance()


@router.get("/skills")
async def list_skills(
    skill_type: str | None = None,
    tag: str | None = None,
    limit: int = 50,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    tags = [tag] if tag else None
    skills = _store.list_skills(skill_type=skill_type, tags=tags, limit=limit)
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
        "stats": _store.stats(),
    }


@router.get("/skills/search")
async def search_skills(
    q: str,
    limit: int = 10,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    skills = _store.search_skills(q, limit=limit)
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
    skill = _store.get_skill(skill_id)
    if not skill:
        return {"error": "Skill not found"}
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
    )
    return {"id": skill.id, "status": "created", "name": skill.name}


@router.put("/skills/{skill_id}")
async def update_skill(
    skill_id: str,
    data: dict[str, Any],
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    skill = _store.get_skill(skill_id)
    if not skill:
        return {"error": "Skill not found"}
    # Record use if applicable
    if data.get("record_use"):
        _store.record_use(skill_id, data.get("success", True))
    return {"status": "updated"}


@router.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: str,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    ok = _store.delete_skill(skill_id)
    return {"status": "deleted" if ok else "not_found"}


@router.get("/skills/match/{context}")
async def match_skills(
    context: str,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Find skills that match the given context."""
    skills = _store.find_matching_skills(context)
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