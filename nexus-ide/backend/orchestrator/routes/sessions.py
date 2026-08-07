"""Sessions API — list / create / rename / delete chat sessions.

Exposes:
    GET    /api/sessions                  — list sessions (with message counts)
    GET    /api/sessions/{id}            — fetch a single session
    POST   /api/sessions                  — create a new session
    PATCH  /api/sessions/{id}            — update title and/or mode
    DELETE /api/sessions/{id}            — delete session + its messages
    GET    /api/sessions/{id}/messages   — fetch messages for a session
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.middleware.auth import require_auth
from backend.persistence.db import (
    create_session,
    delete_session,
    get_messages,
    get_session,
    list_session_runs,
    list_sessions_with_counts,
    update_session,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SessionCreateBody(BaseModel):
    title: str = Field(default="Nova sessão", min_length=1, max_length=200)
    mode: str = Field(default="auto", min_length=1, max_length=32)
    project_id: str | None = Field(default=None, max_length=128)


class SessionUpdateBody(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    mode: str | None = Field(default=None, min_length=1, max_length=32)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def list_sessions_endpoint(
    project_id: str | None = None,
    limit: int = 100,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """List all chat sessions, with message counts.

    Sorted by ``last_active_at`` desc — most recent first.
    """
    sessions = list_sessions_with_counts(project_id=project_id, limit=limit)
    return {"sessions": sessions, "count": len(sessions)}


@router.get("/{session_id}")
async def get_session_endpoint(
    session_id: str,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return session


@router.post("")
async def create_session_endpoint(
    body: SessionCreateBody,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    session = create_session(
        project_id=body.project_id,
        title=body.title,
        mode=body.mode,
    )
    if session is None:
        raise HTTPException(status_code=500, detail="Failed to create session")
    return session


@router.patch("/{session_id}")
async def update_session_endpoint(
    session_id: str,
    body: SessionUpdateBody,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    existing = get_session(session_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    updated = update_session(session_id, title=body.title, mode=body.mode)
    if updated is None:
        raise HTTPException(status_code=500, detail="Failed to update session")
    return updated


@router.delete("/{session_id}")
async def delete_session_endpoint(
    session_id: str,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    existing = get_session(session_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    deleted = delete_session(session_id)
    return {"id": session_id, "deleted": deleted}


@router.get("/{session_id}/messages")
async def get_messages_endpoint(
    session_id: str,
    limit: int = 500,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Fetch persisted messages for a session (for reload + history view)."""
    if get_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return {"messages": get_messages(session_id, limit=limit), "count": limit}


@router.get("/{session_id}/runs")
async def get_runs_endpoint(
    session_id: str,
    limit: int = 20,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Return durable run/checkpoint history for recovery and observability."""
    if get_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return {"runs": list_session_runs(session_id, limit=limit)}


__all__ = ["router"]
