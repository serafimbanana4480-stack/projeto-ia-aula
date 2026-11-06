"""Skills marketplace routes for NEXUS IDE — backed by persistent SkillsStore."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StrictStr

from backend.core.skills_store import SkillsStore
from backend.middleware.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter()

_store = SkillsStore.get_instance()

#: Upper bound for the list endpoints. A skill list is a UI-sized payload.
MAX_SKILL_LIMIT = 500
MAX_SEARCH_LIMIT = 100

SkillName = Annotated[StrictStr, Field(min_length=1, max_length=200)]
SkillType = Annotated[StrictStr, Field(min_length=1, max_length=64)]
SkillText = Annotated[StrictStr, Field(max_length=4_000)]
SkillTrigger = Annotated[StrictStr, Field(max_length=2_000)]
SkillSteps = Annotated[list[StrictStr], Field(max_length=200)]
SkillTags = Annotated[list[StrictStr], Field(max_length=100)]


class SkillCreateRequest(BaseModel):
    """Typed payload of ``POST /api/skills``.

    The model exists so a malformed payload is rejected at the edge instead
    of being persisted: ``steps`` used to accept a bare string, which was then
    rendered character by character.
    """

    name: SkillName = "Unnamed Skill"
    type: SkillType = "workflow"
    description: SkillText = ""
    trigger_pattern: SkillTrigger = ""
    steps: SkillSteps = Field(default_factory=list)
    verification: SkillText = ""
    tags: SkillTags = Field(default_factory=list)
    source: Annotated[StrictStr, Field(max_length=64)] = "manual"
    auto_apply: bool = False


class SkillUpdateRequest(BaseModel):
    """Typed payload of ``PUT /api/skills/{skill_id}``.

    Every field is optional; only the fields actually present in the request
    are written. ``record_use`` keeps the historical "log one usage" side
    effect.
    """

    name: SkillName | None = None
    type: SkillType | None = None
    description: SkillText | None = None
    trigger_pattern: SkillTrigger | None = None
    steps: SkillSteps | None = None
    verification: SkillText | None = None
    tags: SkillTags | None = None
    auto_apply: bool | None = None
    record_use: bool = False
    success: bool = True


#: The fields ``PUT`` may persist, mapped to the store's attribute names.
_UPDATABLE_FIELDS = {
    "name": "name",
    "type": "skill_type",
    "description": "description",
    "trigger_pattern": "trigger_pattern",
    "steps": "steps",
    "verification": "verification",
    "tags": "tags",
    "auto_apply": "auto_apply",
}


def _skill_payload(skill: Any) -> dict[str, Any]:
    """The public representation of one stored skill."""
    return {
        "id": skill.id,
        "name": skill.name,
        "type": skill.skill_type,
        "description": skill.description,
        "trigger_pattern": skill.trigger_pattern,
        "steps": list(skill.steps),
        "verification": skill.verification,
        "tags": list(skill.tags),
        "confidence": skill.confidence,
        "times_used": skill.times_used,
        "success_count": skill.success_count,
        "fail_count": skill.fail_count,
        "source": skill.source,
        "auto_apply": skill.auto_apply,
        "status": getattr(skill, "status", ""),
        "created_at": skill.created_at,
        "updated_at": skill.updated_at,
    }


def _transition_error(result: dict[str, Any], default: str) -> HTTPException:
    """Map a failed lifecycle transition to the right HTTP status."""
    detail = str(result.get("error") or default)
    if result.get("code") == "not_found":
        return HTTPException(status_code=404, detail=detail)
    return HTTPException(status_code=409, detail=detail)


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
    limit: int = Query(default=50, ge=1, le=MAX_SKILL_LIMIT),
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
                "status": getattr(s, "status", ""),
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
    limit: int = Query(default=10, ge=1, le=MAX_SEARCH_LIMIT),
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


@router.get("/skills/promotions")
async def read_promotions(
    limit: int = Query(default=100, ge=1, le=1000),
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Skill promotion audit trail (skill_id, from→to, actor, reason, timestamp)."""
    from backend.core.skill_runtime import read_promotion_log

    entries = await asyncio.to_thread(read_promotion_log, limit)
    return {"promotions": entries, "count": len(entries)}


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str, _user: dict = Depends(require_auth)) -> dict[str, Any]:
    skill = _store.get_skill(skill_id, user_id=str(_user.get("user_id") or ""))
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return _skill_payload(skill)


@router.post("/skills/{skill_id}/promote")
async def promote_skill(
    skill_id: str,
    data: dict[str, Any],
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Promote a reviewed DRAFT skill to ACTIVE through the runtime gate.

    The authenticated caller is the approving operator: their identity is
    recorded as both actor and approver in the promotion audit log.
    """
    from backend.core.skill_runtime import promote_skill as runtime_promote

    user_id = str(_user.get("user_id") or "")
    reason = str(data.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="reason is required to promote a skill")
    confidence = data.get("confidence")
    result = await asyncio.to_thread(
        runtime_promote,
        skill_id,
        actor=user_id,
        reason=reason,
        approved_by=str(data.get("approved_by") or "").strip() or user_id,
        confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
        user_id=user_id,
    )
    if not result.get("ok"):
        raise _transition_error(result, "promotion rejected")
    return result


@router.post("/skills/{skill_id}/deprecate")
async def deprecate_skill(
    skill_id: str,
    data: dict[str, Any],
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Retire an ACTIVE skill (ACTIVE → DEPRECATED)."""
    from backend.core.skill_runtime import deprecate_skill as runtime_deprecate

    user_id = str(_user.get("user_id") or "")
    reason = str(data.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="reason is required to deprecate a skill")
    result = await asyncio.to_thread(
        runtime_deprecate, skill_id, actor=user_id, reason=reason, user_id=user_id
    )
    if not result.get("ok"):
        raise _transition_error(result, "transition rejected")
    return result


@router.post("/skills/{skill_id}/disable")
async def disable_skill(
    skill_id: str,
    data: dict[str, Any],
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Kill switch: force a skill to DISABLED from any state (audited)."""
    from backend.core.skill_runtime import disable_skill as runtime_disable

    user_id = str(_user.get("user_id") or "")
    reason = str(data.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="reason is required to disable a skill")
    result = await asyncio.to_thread(
        runtime_disable, skill_id, actor=user_id, reason=reason, user_id=user_id
    )
    if not result.get("ok"):
        raise _transition_error(result, "transition rejected")
    return result


@router.post("/skills")
async def create_skill(
    data: SkillCreateRequest,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    skill = _store.create_skill(
        name=data.name,
        skill_type=data.type,
        description=data.description,
        trigger_pattern=data.trigger_pattern,
        steps=list(data.steps),
        verification=data.verification,
        tags=list(data.tags),
        source=data.source,
        auto_apply=data.auto_apply,
        user_id=str(_user.get("user_id") or ""),
    )
    return {
        "id": skill.id,
        "status": "created",
        "name": skill.name,
        "skill": _skill_payload(skill),
    }


@router.put("/skills/{skill_id}")
async def update_skill(
    skill_id: str,
    data: SkillUpdateRequest,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Persist the submitted fields of a skill.

    Every field present in the request is written to the store; the response
    echoes the persisted skill so the caller can see what was actually saved.
    """
    user_id = str(_user.get("user_id") or "")
    skill = _store.get_skill(skill_id, user_id=user_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if data.record_use:
        _store.record_use(skill_id, data.success, user_id=user_id)
    changes: dict[str, Any] = {}
    for field, attribute in _UPDATABLE_FIELDS.items():
        if field in data.model_fields_set:
            changes[attribute] = getattr(data, field)
    if changes:
        updated = _store.update_skill(skill_id, user_id=user_id, **changes)
        if updated is None:
            raise HTTPException(status_code=404, detail="Skill not found")
        skill = updated
    return {"status": "updated", "skill": _skill_payload(skill)}


@router.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: str,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    ok = _store.delete_skill(skill_id, user_id=str(_user.get("user_id") or ""))
    if not ok:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"status": "deleted"}


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
