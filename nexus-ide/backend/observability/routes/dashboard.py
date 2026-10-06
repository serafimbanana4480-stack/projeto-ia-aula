"""DEPRECATED — duplicate dashboard backend, kept only for test fixtures.

This module is the second of the two historical dashboard backends. It is
**not mounted** in ``backend/orchestrator/main.py`` and must not be mounted:
the canonical dashboard surfaces are

- metrics stream/state: ``backend/observability/routes/metrics.py``
  (``/api/metrics/current``, ``/api/dashboard/stream``) — what the frontend
  actually consumes;
- agent status/alerts/ask: ``backend/orchestrator/routes/dashboard.py``
  (``/api/dashboard/status|alerts|metrics|ask|diagnose``).

Both read from the same source of truth (``get_metrics_collector()``), so
there is exactly one metrics pipeline. ``DashboardState`` remains importable
because ``backend/tests/api/conftest.py`` wires it into test fixtures; new
code must not add endpoints here. See ARCHITECTURE.md §Dashboard.

Why mounting it is a defect, measured rather than assumed (2026-09-26)
---------------------------------------------------------------------
``include_router`` of this module does **not** fail and does not duplicate an
operation id, so the mistake is easy to make and invisible afterwards. What it
does produce is a tenth duplicate ``(path, method)`` registration:
``GET /api/dashboard/stream`` is declared both here and by
``observability/routes/metrics.py``, which is the SSE
``frontend/stores/metricsStore.ts`` subscribes to. Registration order decides
which of two different payload shapes answers.

The two unique paths below are the reason the tests were wrong, not the router:
``/api/dashboard/state`` has no consumer in ``backend/`` or ``frontend/`` (the
state the dashboard needs is served by ``/api/dashboard/status``), and
``/api/dashboard/publish`` exists only to inject demo events, reaching into
``DashboardState._bus`` to do it.

``backend/tests/api/test_backend_hardening_dashboard_wiring.py`` enforces all of
the above; ``backend/tests/api/test_dashboard_api.py`` asserts the real contract.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from backend.middleware.auth import require_auth
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
async def get_dashboard(_user: dict = Depends(require_auth)) -> dict[str, Any]:
    """Get current dashboard state."""
    state = get_dashboard_state()
    return await state.get_state()


@router.get("/dashboard/stream")
async def dashboard_events_stream(_user: dict = Depends(require_auth)) -> StreamingResponse:
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
async def publish_event(
    event_type: str,
    agent: str | None = None,
    payload: dict[str, Any] | None = None,
    _user: dict = Depends(require_auth),
) -> dict[str, str]:
    """Publish an event to the dashboard event bus (for testing/demo)."""
    state = get_dashboard_state()
    event = Event(type=event_type, agent=agent, payload=payload or {})
    await state._bus.publish(event)
    return {"status": "published"}
