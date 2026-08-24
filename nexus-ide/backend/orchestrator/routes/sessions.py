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

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.middleware.auth import require_auth
from backend.models.api import StreamEvent
from backend.orchestrator.events import OrchestratorEvent, get_event_store
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

_PUBLIC_STREAM_TYPES = {
    "routing",
    "agent_started",
    "token",
    "thinking",
    "tool_call",
    "tool_result",
    "tool_error",
    "tool_confirmation",
    "progress",
    "agent_finished",
    "error",
    "metric",
    "done",
    "mission_brief",
    "mission_plan",
    "mission_wave",
    "mission_agent",
    "mission_decision",
    "mission_verification",
    "mission_completed",
}


def _event_to_chat_frame(event: OrchestratorEvent) -> str:
    """Convert a persisted orchestrator event into the public chat contract."""
    event_type = getattr(event.event_type, "value", str(event.event_type))
    public_type = event_type if event_type in _PUBLIC_STREAM_TYPES else "progress"
    raw_data = {
        **(event.data or {}),
        "event": event_type,
        "event_id": event.event_id,
        "task_id": event.task_id,
        "correlation_id": event.correlation_id,
        "replayed": True,
    }
    # Persisted diagnostic payloads may contain dataclasses/enums.  Recovery
    # must never fail because a debug value is not JSON-native.
    safe_data = json.loads(json.dumps(raw_data, ensure_ascii=False, default=str))
    frame = StreamEvent(
        type=public_type,  # type: ignore[arg-type]
        agent=event.source or "ORCHESTRATOR",
        content=event.content or None,
        data=safe_data,
        timestamp=(
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(event.timestamp))
        ),
    )
    return f"data: {frame.model_dump_json()}\n\n"


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
    if get_session(session_id) is None and session_id == "default":
        return {"messages": [], "count": 0}
    if get_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    messages = get_messages(session_id, limit=limit)
    return {"messages": messages, "count": len(messages)}


@router.get("/{session_id}/runs")
async def get_runs_endpoint(
    session_id: str,
    limit: int = 20,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Return durable run/checkpoint history for recovery and observability."""
    # ``default`` is an implicit frontend session and may not have a durable
    # row until its first message.  Recovery must be empty, not a misleading
    # 404, while arbitrary unknown session ids remain strict 404s.
    if get_session(session_id) is None and session_id == "default":
        return {"runs": []}
    if get_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return {"runs": list_session_runs(session_id, limit=limit)}


@router.get("/{session_id}/events")
async def session_events_endpoint(
    session_id: str,
    request: Request,
    since: float = 0.0,
    run_id: str | None = None,
    _user: dict = Depends(require_auth),
) -> StreamingResponse:
    """Replay persisted mission events and then follow the live EventBus.

    This endpoint is intentionally separate from ``POST /chat``: a refreshed
    browser can recover a running mission without resending the user's prompt.
    The stream ends when the selected durable run reaches a terminal state.
    """
    if get_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    event_bus = getattr(request.app.state, "event_bus", None)
    store = get_event_store()

    async def event_generator():
        live_stream = None
        next_live: asyncio.Task[Any] | None = None
        try:
            if event_bus is not None:
                live_stream = event_bus.stream_events(event_types=["*"], session_id=session_id)
                next_live = asyncio.create_task(anext(live_stream))

            replayed = [
                event
                for event in store.load_window(max(0.0, since), time.time())
                if event.session_id == session_id
                and (not run_id or event.task_id == run_id or event.data.get("run_id") == run_id)
            ]
            replayed.sort(key=lambda event: (event.timestamp, event.event_id))
            for event in replayed:
                yield _event_to_chat_frame(event)

            current_run = None
            if run_id:
                from backend.persistence.db import get_session_run

                current_run = get_session_run(run_id)
            else:
                current_run = next(
                    (run for run in list_session_runs(session_id, limit=20) if run.get("status") == "running"),
                    None,
                )

            if current_run is None:
                yield _event_to_chat_frame(
                    OrchestratorEvent(
                        event_type="done",  # type: ignore[arg-type]
                        source="ORCHESTRATOR",
                        session_id=session_id,
                        task_id=run_id or "",
                    )
                )
                return

            # A completed run is still recoverable: replay everything that is
            # persisted above, then close the stream instead of waiting for a
            # live EventBus subscription that can no longer produce events.
            if current_run.get("status") in {
                "completed",
                "failed",
                "cancelled",
                "interrupted",
                "blocked",
            }:
                yield _event_to_chat_frame(
                    OrchestratorEvent(
                        event_type="done",  # type: ignore[arg-type]
                        source="ORCHESTRATOR",
                        session_id=session_id,
                        task_id=current_run.get("id", ""),
                    )
                )
                return

            while True:
                if await request.is_disconnected():
                    break
                if next_live is None:
                    yield ": nexus-heartbeat\n\n"
                    await asyncio.sleep(10)
                    continue

                ready, _ = await asyncio.wait({next_live}, timeout=10.0)
                if not ready:
                    yield ": nexus-heartbeat\n\n"
                    if current_run:
                        from backend.persistence.db import get_session_run

                        current_run = get_session_run(current_run.get("id", ""))
                        if current_run and current_run.get("status") in {
                            "completed",
                            "failed",
                            "cancelled",
                            "interrupted",
                        }:
                            yield _event_to_chat_frame(
                                OrchestratorEvent(
                                    event_type="done",  # type: ignore[arg-type]
                                    source="ORCHESTRATOR",
                                    session_id=session_id,
                                    task_id=current_run.get("id", ""),
                                )
                            )
                            break
                    continue

                try:
                    event = next_live.result()
                except StopAsyncIteration:
                    break
                if not run_id or event.task_id == run_id or event.data.get("run_id") == run_id:
                    yield _event_to_chat_frame(event)
                next_live = asyncio.create_task(anext(live_stream))
                if event.event_type.value in {"done", "orchestrator_finished", "mission_completed"}:
                    break
        finally:
            if next_live is not None and not next_live.done():
                next_live.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await next_live
            if live_stream is not None:
                await live_stream.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


__all__ = ["router"]
