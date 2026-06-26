"""Dashboard endpoints for real-time system observability."""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from backend.observability.dashboard_state import DashboardState
from backend.observability.event_bus import EventBus
from backend.observability.events import Event

router = APIRouter()

# Global state (initialized in lifespan)
_dashboard_state: DashboardState | None = None


def get_dashboard_state() -> DashboardState:
    if _dashboard_state is None:
        raise RuntimeError("DashboardState not initialized")
    return _dashboard_state


async def init_dashboard_state(event_bus: EventBus | None = None) -> DashboardState:
    global _dashboard_state
    _dashboard_state = DashboardState(event_bus=event_bus or EventBus())
    await _dashboard_state.start()
    return _dashboard_state


@router.get("/dashboard/state")
async def get_dashboard() -> dict[str, Any]:
    """Get current dashboard state."""
    state = get_dashboard_state()
    return await state.get_state()


@router.get("/dashboard/stream")
async def dashboard_events_stream() -> StreamingResponse:
    """Stream real-time dashboard events via SSE."""
    state = get_dashboard_state()

    async def generator() -> AsyncIterator[str]:
        async for chunk in state.sse_stream():
            yield chunk

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/dashboard/publish")
async def publish_event(event_type: str, agent: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, str]:
    """Publish an event to the dashboard event bus (for testing/demo)."""
    state = get_dashboard_state()
    event = Event(type=event_type, agent=agent, payload=payload or {})
    await state._bus.publish(event)
    return {"status": "published"}
