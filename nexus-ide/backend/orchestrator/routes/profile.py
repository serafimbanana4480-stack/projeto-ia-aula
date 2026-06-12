"""Profile, routines and persistent memory routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from backend.middleware.auth import require_auth
from backend.models.api import (
    MemoryCreateRequest,
    RoutineCreateRequest,
    UserPreferencesUpdateRequest,
)
from backend.persistence.profile_db import (
    ensure_user_profile,
    get_memories,
    get_routines,
    create_memory,
    create_routine,
    update_preferences,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("/me")
async def get_profile(
    current_user: dict = Depends(require_auth),
) -> dict[str, Any]:
    user_id = current_user["user_id"]
    profile = ensure_user_profile(user_id)
    return {"profile": profile}


@router.put("/preferences")
async def update_user_preferences(
    req: UserPreferencesUpdateRequest,
    current_user: dict = Depends(require_auth),
) -> dict[str, Any]:
    user_id = current_user["user_id"]
    profile = update_preferences(user_id, req.preferences)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )
    return {"profile": profile}


@router.get("/routines")
async def list_user_routines(
    current_user: dict = Depends(require_auth),
) -> dict[str, Any]:
    user_id = current_user["user_id"]
    routines = get_routines(user_id)
    return {"routines": routines}


@router.post("/routines")
async def add_user_routine(
    req: RoutineCreateRequest,
    current_user: dict = Depends(require_auth),
) -> dict[str, Any]:
    user_id = current_user["user_id"]
    routine = create_routine(
        user_id=user_id,
        name=req.name,
        description=req.description,
        schedule_cron=req.schedule_cron,
    )
    return {"routine": routine}


@router.get("/memories")
async def list_user_memories(
    memory_type: str | None = None,
    current_user: dict = Depends(require_auth),
) -> dict[str, Any]:
    user_id = current_user["user_id"]
    memories = get_memories(user_id, memory_type=memory_type)
    return {"memories": memories}


@router.post("/memories")
async def add_user_memory(
    req: MemoryCreateRequest,
    current_user: dict = Depends(require_auth),
) -> dict[str, Any]:
    user_id = current_user["user_id"]
    memory = create_memory(
        user_id=user_id,
        content=req.content,
        memory_type=req.memory_type,
        importance=req.importance,
    )
    return {"memory": memory}
