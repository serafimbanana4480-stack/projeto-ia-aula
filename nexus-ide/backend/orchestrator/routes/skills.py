"""Skills marketplace routes for NEXUS IDE."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from backend.middleware.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter()


_skills: dict[str, dict[str, Any]] = {}


@router.get("/skills")
async def list_skills(_user: dict = Depends(require_auth)) -> dict[str, Any]:
    return {"skills": list(_skills.values()), "count": len(_skills)}


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str, _user: dict = Depends(require_auth)) -> dict[str, Any]:
    skill = _skills.get(skill_id)
    if not skill:
        return {"error": "Skill not found"}
    return skill


@router.post("/skills")
async def create_skill(data: dict[str, Any], _user: dict = Depends(require_auth)) -> dict[str, Any]:
    skill_id = data.get("id", "")
    if not skill_id:
        from uuid import uuid4

        skill_id = str(uuid4()).replace("-", "")[:16]
    data["id"] = skill_id
    _skills[skill_id] = data
    return {"id": skill_id, "status": "created"}


@router.put("/skills/{skill_id}")
async def update_skill(
    skill_id: str, data: dict[str, Any], _user: dict = Depends(require_auth)
) -> dict[str, Any]:
    if skill_id not in _skills:
        return {"error": "Skill not found"}
    _skills[skill_id].update(data)
    _skills[skill_id]["id"] = skill_id
    return {"id": skill_id, "status": "updated"}


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str, _user: dict = Depends(require_auth)) -> dict[str, Any]:
    if skill_id in _skills:
        del _skills[skill_id]
    return {"id": skill_id, "status": "deleted"}
