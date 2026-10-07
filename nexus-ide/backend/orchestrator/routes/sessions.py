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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.middleware.auth import require_auth
from backend.models.api import StreamEvent
from backend.orchestrator.events import OrchestratorEvent, get_event_store
from backend.persistence.db import (
    count_sessions,
    create_session,
    delete_session,
    get_messages_page,
    get_session_for_user,
    list_session_runs,
    list_sessions_with_counts,
    update_session,
)
from backend.persistence.db import (
    create_todo,
    delete_todo,
    get_session_todos_db,
    get_todo,
    search_sessions as search_session_rows,
    update_todo,
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
    _seq = event.seq or event.data.get("seq", 0)
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
        run_id=event.run_id,
        event_id=event.event_id,
        seq=_seq or None,
        task_id=event.task_id,
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


class TodoCreateBody(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")


class TodoUpdateBody(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    priority: str | None = Field(default=None, pattern="^(low|normal|high)$")
    status: str | None = Field(default=None, pattern="^(pending|in_progress|completed|cancelled)$")


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {s: 0 for s in ("pending", "in_progress", "completed", "cancelled")}
    for item in items:
        counts[item["status"]] += 1
    counts["total"] = len(items)
    return {"counts": counts}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def list_sessions_endpoint(
    project_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """List one page of chat sessions, with message counts.

    Sorted by ``last_active_at`` desc — most recent first.
    """
    sessions = list_sessions_with_counts(
        project_id=project_id,
        limit=limit,
        offset=offset,
        user_id=str(_user.get("user_id") or ""),
    )
    return {
        "sessions": sessions,
        "count": len(sessions),
        "total": count_sessions(
            project_id=project_id, user_id=str(_user.get("user_id") or "")
        ),
        "offset": offset,
        "limit": limit,
    }


@router.get("/search")
async def search_sessions_endpoint(
    q: str = Query(min_length=1, max_length=200),
    project_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Search all persisted conversations, including message text.

    ``match_type`` differentiates a title/mode hit from a hit inside a message;
    message hits include a bounded snippet and message id for navigation.
    """
    sessions, total = search_session_rows(
        q,
        project_id=project_id,
        limit=limit,
        offset=offset,
        user_id=str(_user.get("user_id") or ""),
    )
    return {
        "sessions": sessions,
        "count": len(sessions),
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/{session_id}")
async def get_session_endpoint(
    session_id: str,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    session = get_session_for_user(session_id, str(_user.get("user_id") or ""))
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
        user_id=str(_user.get("user_id") or ""),
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
    user_id = str(_user.get("user_id") or "")
    existing = get_session_for_user(session_id, user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    updated = update_session(session_id, title=body.title, mode=body.mode, user_id=user_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Failed to update session")
    return updated


@router.delete("/{session_id}")
async def delete_session_endpoint(
    session_id: str,
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    user_id = str(_user.get("user_id") or "")
    existing = get_session_for_user(session_id, user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    try:
        from backend.orchestrator.infinity.vibe_director import drop_director

        drop_director(session_id)
    except OSError as exc:
        logger.exception("Could not remove persisted Vibe state for session %s", session_id)
        raise HTTPException(
            status_code=500,
            detail="Could not remove Vibe state; the chat session was not deleted",
        ) from exc
    deleted = delete_session(session_id, user_id=user_id)
    context_store = getattr(request.app.state, "context", None)
    if context_store is not None:
        with contextlib.suppress(Exception):
            await context_store.clear_session(session_id)
    return {"id": session_id, "deleted": deleted}


@router.get("/{session_id}/todos")
async def session_todos(
    session_id: str,
    status: str = "",
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Read the durable checklist without executing an agent or modifying it."""
    if await asyncio.to_thread(
        get_session_for_user, session_id, str(_user.get("user_id") or "")
    ) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    result = await asyncio.to_thread(read_session_todo_snapshot, session_id, status)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error", "Checklist unavailable"))
    return {**result, "session_id": session_id}


@router.post("/{session_id}/todos")
async def create_session_todo(
    session_id: str,
    body: TodoCreateBody,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Create a new todo item for this session."""
    if await asyncio.to_thread(
        get_session_for_user, session_id, str(_user.get("user_id") or "")
    ) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    row = create_todo(session_id, body.content, body.priority)
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to create todo")
    todos = get_session_todos_db(session_id)
    return {"ok": True, "operation": "add", "session_id": session_id, "todos": todos, **_summary(todos)}


@router.put("/{session_id}/todos/{todo_id}")
async def update_session_todo(
    session_id: str,
    todo_id: str,
    body: TodoUpdateBody,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Update a todo item for this session."""
    if await asyncio.to_thread(
        get_session_for_user, session_id, str(_user.get("user_id") or "")
    ) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    existing = get_todo(todo_id)
    if existing is None or existing.get("session_id") != session_id:
        raise HTTPException(status_code=404, detail=f"Todo {todo_id} not found")
    updated = update_todo(
        todo_id,
        content=body.content,
        priority=body.priority,
        status=body.status,
    )
    if updated is None:
        raise HTTPException(status_code=500, detail="Failed to update todo")
    todos = get_session_todos_db(session_id)
    return {"ok": True, "operation": "update", "session_id": session_id, "todos": todos, **_summary(todos)}


@router.delete("/{session_id}/todos/{todo_id}")
async def delete_session_todo(
    session_id: str,
    todo_id: str,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Delete a todo item for this session."""
    if await asyncio.to_thread(
        get_session_for_user, session_id, str(_user.get("user_id") or "")
    ) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    existing = get_todo(todo_id)
    if existing is None or existing.get("session_id") != session_id:
        raise HTTPException(status_code=404, detail=f"Todo {todo_id} not found")
    deleted = delete_todo(todo_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete todo")
    todos = get_session_todos_db(session_id)
    return {"ok": True, "operation": "remove", "session_id": session_id, "todos": todos, **_summary(todos)}


@router.get("/{session_id}/messages")
async def get_messages_endpoint(
    session_id: str,
    limit: int = Query(default=500, ge=1, le=500),
    before_id: str | None = Query(default=None, min_length=1, max_length=128),
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Fetch the newest messages, or one older cursor page for the history UI."""
    user_id = str(_user.get("user_id") or "")
    if get_session_for_user(session_id, user_id) is None and session_id == "default":
        return {
            "messages": [],
            "count": 0,
            "has_more": False,
            "next_cursor": None,
        }
    if get_session_for_user(session_id, user_id) is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    try:
        messages, has_more, next_cursor = get_messages_page(
            session_id, limit=limit, before_id=before_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "messages": messages,
        "count": len(messages),
        "has_more": has_more,
        "next_cursor": next_cursor,
    }


@router.get("/{session_id}/runs")
async def get_runs_endpoint(
    session_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Return one bounded page of durable run/checkpoint history."""
    # ``default`` is an implicit frontend session and may not have a durable
    # row until its first message.  Recovery must be empty, not a misleading
    # 404, while arbitrary unknown session ids remain strict 404s.
    user_id = str(_user.get("user_id") or "")
    if get_session_for_user(session_id, user_id) is None and session_id == "default":
        return {"runs": [], "count": 0, "has_more": False, "next_offset": 0}
    if get_session_for_user(session_id, user_id) is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    rows = list_session_runs(session_id, limit=limit + 1, offset=offset)
    runs = rows[:limit]
    has_more = len(rows) > limit
    return {
        "runs": runs,
        "count": len(runs),
        "has_more": has_more,
        "next_offset": offset + len(runs),
    }


@router.get("/{session_id}/events")
async def session_events_endpoint(
    session_id: str,
    request: Request,
    since: float = 0.0,
    run_id: str | None = None,
    after_seq: int = 0,
    _user: dict = Depends(require_auth),
) -> StreamingResponse:
    """Replay persisted mission events and then follow the live EventBus.

    This endpoint is intentionally separate from ``POST /chat``: a refreshed
    browser can recover a running mission without resending the user's prompt.
    The stream ends when the selected durable run reaches a terminal state.
    """
    user_id = str(_user.get("user_id") or "")
    if get_session_for_user(session_id, user_id) is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    event_bus = getattr(request.app.state, "event_bus", None)
    store = get_event_store()

    async def event_generator():
        live_stream = None
        next_live: asyncio.Task[Any] | None = None
        try:
            from backend.persistence.db import get_session_run
            from backend.runtime.events import (
                RunEventStream,
                get_active_run_event_stream,
                run_event_journal_path,
            )

            if run_id:
                current_run = get_session_run(run_id)
                if current_run and current_run.get("session_id") != session_id:
                    current_run = None
            else:
                current_run = next(
                    (
                        run
                        for run in list_session_runs(session_id, limit=20)
                        if run.get("status") == "running"
                    ),
                    None,
                )

            target_run_id = str((current_run or {}).get("id") or run_id or "")
            owns_run = bool(
                current_run
                and str(current_run.get("session_id") or "") == session_id
            )
            runtime_stream = (
                get_active_run_event_stream(target_run_id)
                if owns_run and target_run_id
                else None
            )
            journal_path = (
                run_event_journal_path(target_run_id)
                if owns_run and target_run_id
                else None
            )

            # The primary runtime owns its own ordered event stream. Serve its
            # in-memory subscription while it is live; after process recovery,
            # replay the same (run_id, seq) journal. The legacy EventBus below
            # remains the source for the older orchestration lanes.
            if runtime_stream is not None or (
                journal_path is not None and journal_path.is_file()
            ):
                if runtime_stream is not None:
                    replay_through_seq = runtime_stream.last_seq
                    async for runtime_event in runtime_stream.subscribe(after_seq=after_seq):
                        yield _runtime_event_to_chat_frames(
                            runtime_event,
                            replayed=runtime_event.seq <= replay_through_seq,
                        )
                else:
                    for runtime_event in RunEventStream.load_journal(journal_path):
                        if runtime_event.seq > after_seq:
                            yield _runtime_event_to_chat_frames(
                                runtime_event, replayed=True
                            )
                yield _event_to_chat_frame(
                    OrchestratorEvent(
                        event_type="done",  # type: ignore[arg-type]
                        source="NEXUS",
                        session_id=session_id,
                        run_id=target_run_id,
                        task_id=target_run_id,
                    )
                )
                return

            if event_bus is not None:
                live_stream = event_bus.stream_events(event_types=["*"], session_id=session_id)
                next_live = asyncio.create_task(anext(live_stream))

            replayed = [
                event
                for event in store.load_window(max(0.0, since), time.time())
                if event.session_id == session_id
                and (not run_id or event.task_id == run_id or event.data.get("run_id") == run_id)
            ]
            # Gap replay: only events after after_seq.
            # Legacy rows with seq=0 fall back to data["seq"].
            if after_seq > 0:
                filtered: list[OrchestratorEvent] = []
                for event in replayed:
                    evt_seq = event.seq or event.data.get("seq", 0)
                    if evt_seq > after_seq:
                        filtered.append(event)
                replayed = filtered
            replayed.sort(key=lambda event: (event.timestamp, event.event_id))
            for event in replayed:
                yield _event_to_chat_frame(event)

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


def _runtime_event_to_chat_frames(event: Any, *, replayed: bool) -> str:
    """Map a primary runtime fact into the existing, ordered chat SSE contract."""
    from backend.orchestrator.routes.chat_primary import runtime_event_to_stream_events

    frames = runtime_event_to_stream_events(event)
    output: list[str] = []
    for frame in frames:
        data = dict(frame.data or {})
        data.update(
            {
                "run_id": event.run_id,
                "seq": event.seq,
                "event_id": event.event_id,
                "kind": event.type.value,
                "runtime_type": event.type.value,
            }
        )
        if replayed:
            data["replayed"] = True
        frame.data = data
        output.append(f"data: {frame.model_dump_json()}\n\n")
    return "".join(output)
