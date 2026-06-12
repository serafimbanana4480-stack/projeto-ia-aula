"""MetaOrchestrator REST + WebSocket routes.

Endpoints:
    POST /api/missions                — Create a new mission
    GET  /api/missions/{id}           — Get mission status
    POST /api/missions/{id}/pause     — Pause all agents in mission
    POST /api/missions/{id}/resume    — Resume mission
    POST /api/missions/{id}/abort     — Abort mission
    GET  /api/missions/{id}/agents    — List active agents
    WS   /ws/missions/{id}            — Real-time event stream
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.middleware.rate_limit import limiter
from backend.orchestrator.meta import MetaOrchestrator, Mission, MissionStatus
from backend.orchestrator.registry import get_registry

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request/response models ─────────────────────────────────────────────────


class CreateMissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, max_length=10_000)
    token_budget: int = Field(default=50_000, ge=1000)
    time_budget_seconds: int = Field(default=3_600, ge=60)
    project_path: str = Field(default=".", max_length=2000)


class CreateMissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    status: str
    objective: str
    phases: list[str]


class MissionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    status: str
    objective: str
    current_phase: str
    phases: list[dict[str, Any]]
    tokens_used: int
    token_budget: int
    time_elapsed_seconds: int
    active_agents: list[dict[str, Any]]
    metadata: dict[str, Any]


class MissionActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    status: str
    action: str


class ActiveAgentsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    agents: list[dict[str, Any]]


# ── Helpers ─────────────────────────────────────────────────────────────────


def _get_meta(request: Request) -> MetaOrchestrator:
    """Retrieve or lazily initialise the MetaOrchestrator from app state."""
    app = request.app
    if not hasattr(app.state, "meta_orchestrator"):
        from backend.orchestrator.engine import OrchestrationEngine

        registry = get_registry(app)
        engine = OrchestrationEngine(
            llm_client=app.state.llm_client,
            registry=registry,
            event_bus=app.state.event_bus,
        )
        app.state.meta_orchestrator = MetaOrchestrator(
            engine=engine,
            event_bus=app.state.event_bus,
            llm_client=app.state.llm_client,
            registry=registry,
        )
    return app.state.meta_orchestrator


def _mission_to_status_dict(mission: Mission) -> dict[str, Any]:
    return {
        "mission_id": mission.id,
        "status": mission.status.value,
        "objective": mission.objective,
        "current_phase": (
            mission.phases[mission.current_phase_index].name
            if 0 <= mission.current_phase_index < len(mission.phases)
            else ""
        ),
        "phases": [
            {
                "name": p.name,
                "status": p.status.value,
                "tasks": p.tasks,
                "tokens_used": p.tokens_used,
                "auto_correction_count": p.auto_correction_count,
            }
            for p in mission.phases
        ],
        "tokens_used": mission.tokens_used,
        "token_budget": mission.token_budget,
        "time_elapsed_seconds": int(time.time() - mission.started_at) if mission.started_at else 0,
        "active_agents": [
            a.model_dump(mode="json") for a in mission.active_agents.values()
        ],
        "metadata": mission.metadata,
    }


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/missions")
@limiter.limit("120/minute")
async def list_missions(request: Request) -> dict[str, Any]:
    """List all active missions."""
    meta = _get_meta(request)
    missions = meta.list_all_missions()
    return {
        "missions": [_mission_to_status_dict(m) for m in missions],
        "count": len(missions),
    }


@router.post("/missions")
@limiter.limit("30/minute")
async def create_mission(req: CreateMissionRequest, request: Request) -> CreateMissionResponse:
    """Create a new dynamic mission."""
    meta = _get_meta(request)
    mission = await meta.create_mission(
        objective=req.objective,
        token_budget=req.token_budget,
        time_budget_seconds=req.time_budget_seconds,
        project_path=req.project_path,
    )
    # Launch mission asynchronously so the endpoint returns immediately
    asyncio.create_task(meta.run_mission(mission.id))
    return CreateMissionResponse(
        mission_id=mission.id,
        status=mission.status.value,
        objective=mission.objective,
        phases=[p.name for p in mission.phases],
    )


@router.get("/missions/{mission_id}")
@limiter.limit("120/minute")
async def get_mission(request: Request, mission_id: str) -> MissionStatusResponse:
    """Retrieve current mission status."""
    meta = _get_meta(request)
    mission = meta.get_mission(mission_id)
    if mission is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Mission {mission_id} not found"},
        )
    data = _mission_to_status_dict(mission)
    return MissionStatusResponse(**data)


@router.post("/missions/{mission_id}/pause")
@limiter.limit("60/minute")
async def pause_mission(request: Request, mission_id: str) -> MissionActionResponse:
    """Pause all agents in the mission."""
    meta = _get_meta(request)
    mission = await meta.pause(mission_id)
    if mission is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Mission {mission_id} not found"},
        )
    return MissionActionResponse(
        mission_id=mission_id,
        status=mission.status.value,
        action="pause",
    )


@router.post("/missions/{mission_id}/resume")
@limiter.limit("60/minute")
async def resume_mission(request: Request, mission_id: str) -> MissionActionResponse:
    """Resume a paused mission."""
    meta = _get_meta(request)
    mission = await meta.resume(mission_id)
    if mission is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Mission {mission_id} not found"},
        )
    return MissionActionResponse(
        mission_id=mission_id,
        status=mission.status.value,
        action="resume",
    )


@router.post("/missions/{mission_id}/abort")
@limiter.limit("60/minute")
async def abort_mission(request: Request, mission_id: str) -> MissionActionResponse:
    """Abort the mission and cancel all its agents."""
    meta = _get_meta(request)
    mission = await meta.abort(mission_id)
    if mission is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Mission {mission_id} not found"},
        )
    return MissionActionResponse(
        mission_id=mission_id,
        status=mission.status.value,
        action="abort",
    )


@router.get("/missions/{mission_id}/agents")
@limiter.limit("120/minute")
async def list_active_agents(request: Request, mission_id: str) -> ActiveAgentsResponse:
    """List all active (non-terminal) agents in the mission."""
    meta = _get_meta(request)
    agents = meta.list_active_agents(mission_id)
    return ActiveAgentsResponse(
        mission_id=mission_id,
        agents=[a.model_dump(mode="json") for a in agents],
    )


# NOTE: The WebSocket endpoint lives directly on the FastAPI app so that
# the path is exactly ``/ws/missions/{mission_id}`` without the ``/api`` prefix.
# See ``backend/orchestrator/main.py`` where it is mounted with
# ``app.add_api_websocket_route(...)``.

# ── WebSocket handler (mounted directly on app for ``/ws/missions/{id}``) ──


async def mission_websocket(websocket: WebSocket, mission_id: str) -> None:
    """WebSocket endpoint for real-time mission updates."""
    await websocket.accept()
    meta: MetaOrchestrator | None = None
    try:
        app = websocket.app
        if not hasattr(app.state, "meta_orchestrator"):
            from backend.orchestrator.engine import OrchestrationEngine

            registry = get_registry(app)
            engine = OrchestrationEngine(
                llm_client=app.state.llm_client,
                registry=registry,
                event_bus=app.state.event_bus,
            )
            app.state.meta_orchestrator = MetaOrchestrator(
                engine=engine,
                event_bus=app.state.event_bus,
                llm_client=app.state.llm_client,
                registry=registry,
            )
        meta = app.state.meta_orchestrator

        async def _stream() -> AsyncIterator[str]:
            async for event in meta.stream_events(mission_id):
                payload = {
                    "type": event.event_type.value,
                    "source": event.source,
                    "task_id": event.task_id,
                    "data": event.data,
                    "timestamp": event.timestamp,
                }
                yield json.dumps(payload, default=str)

        async for payload in _stream():
            if websocket.client_state.DISCONNECTED:
                break
            await websocket.send_text(payload)
    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for mission %s", mission_id)
    except Exception as exc:
        logger.exception("WebSocket error for mission %s: %s", mission_id, exc)
        try:
            await websocket.close(code=1011)
        except Exception:
            logger.debug("Failed to close WebSocket for mission %s", mission_id, exc_info=True)
