"""MetaOrchestrator REST + WebSocket routes.

Endpoints:
    POST /api/missions                — Create a new mission
    GET  /api/missions/{id}           — Get mission status
    POST /api/missions/{id}/pause     — Pause all agents in mission
    POST /api/missions/{id}/resume    — Resume mission
    POST /api/missions/{id}/abort     — Abort mission
    GET  /api/missions/{id}/agents    — List active agents
    WS   /ws/missions/{id}            — Real-time event stream

Ownership
---------
A mission belongs to the user who created it.  The owner is recorded in
``mission.metadata["user_id"]`` when the mission is created, and every route
that reads or mutates a mission — the WebSocket included — checks it.

The WebSocket used to authenticate the token and nothing else: any
registered user could complete the handshake on ``/ws/missions/<id>`` and
receive the mission's event stream, which carries the objective, the agent
tasks and the token counters of somebody else's work.  The ownership check
now happens *before* ``accept()``, so a handshake that is not allowed never
becomes a connection.
"""

# NOTE: `from __future__ import annotations` is intentionally NOT enabled
# in this file. Pydantic 2 + string annotations (PEP 563) breaks the
# OpenAPI generator for the response models below. See
# https://errors.pydantic.dev/2.13/u/class-not-fully-defined

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.core.disk_guard import DiskPressureError, require_disk_headroom
from backend.middleware.auth import require_auth
from backend.middleware.deny_by_default import (
    WS_FORBIDDEN_CODE,
    require_websocket_token,
)
from backend.orchestrator.meta import MetaOrchestrator, Mission
from backend.orchestrator.registry import get_registry
from backend.runtime.run_coordinator import RunState

logger = logging.getLogger(__name__)
router = APIRouter()

#: Key of the mission owner inside ``Mission.metadata``.
MISSION_OWNER_KEY = "user_id"


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
    #: Durable runs of this mission that were marked ``RECOVERING`` (Fase 1b).
    #: Optional with a default so existing clients of the pause/abort actions
    #: keep their exact response shape.
    resumed_runs: list[str] = Field(default_factory=list)


class ActiveAgentsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    agents: list[dict[str, Any]]


# ── Helpers ─────────────────────────────────────────────────────────────────
# ── Durable runs (Fase 1b — checkpoint/resume/idempotência) ──────────────────


class ResumableRunsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: list[dict[str, Any]]
    count: int


class ResumeRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    state: str
    goal: str
    session_id: str
    project_id: str
    checkpoint_id: str
    phase: str
    checkpoint: dict[str, Any]
    resumable: bool


def _get_run_coordinator(request: Request):
    """Return the process-wide run coordinator, or ``None``.

    The lifespan installs the singleton on ``app.state``; a client that never
    ran the startup path (an ad-hoc TestClient, for instance) falls back to the
    accessor, which is the same object anyway.
    """
    coordinator = getattr(request.app.state, "run_coordinator", None)
    if coordinator is not None:
        return coordinator
    from backend.runtime.primary import get_run_coordinator as _accessor

    return _accessor()


def _run_to_dict(record: Any) -> dict[str, Any]:
    """Serialise one ``RunRecord`` for an API client."""
    return {
        "run_id": str(getattr(record, "run_id", "")),
        "goal": str(getattr(record, "goal", "")),
        "state": str(getattr(getattr(record, "state", None), "value", record.state)),
        "session_id": str(getattr(record, "session_id", "")),
        "project_id": str(getattr(record, "project_id", "")),
        "user_id": str(getattr(record, "user_id", "")),
        "requirements": list(getattr(record, "requirements", []) or []),
        "constraints": list(getattr(record, "constraints", []) or []),
        "definition_of_done": list(getattr(record, "definition_of_done", []) or []),
        "current_task_id": getattr(record, "current_task_id", None),
        "changed_files": list(getattr(record, "changed_files", []) or []),
        "artifacts": list(getattr(record, "artifacts", []) or []),
        "created_at": str(getattr(record, "created_at", "")),
        "updated_at": str(getattr(record, "updated_at", "")),
        "heartbeat_at": str(getattr(record, "heartbeat_at", "")),
        "stop_reason": str(getattr(record, "stop_reason", "")),
        "plan": getattr(record, "plan", None),
        "budget": dict(getattr(record, "budget", {}) or {}),
    }


def _run_belongs_to(record: Any | None, user_id: str) -> bool:
    """Return whether an authenticated user owns a durable run.

    Legacy rows without an owner are deliberately inaccessible. A durable run
    contains the user's objective, project path, checkpoint, and changed-file
    list, so authentication alone is not enough to expose it.
    """
    owner = str(getattr(record, "user_id", "") or "").strip()
    return bool(record is not None and user_id and owner and owner == user_id)


def _resume_mission_runs(request: Request, mission_id: str) -> list[str]:
    """Mark the runs a mission left behind as ``RECOVERING`` and list them.

    A mission's runs are the engine runs whose ``session_id`` is the mission id
    (that is how ``MetaOrchestrator._run_phase`` drives the engine) plus any run
    carrying the explicit mission marker. This deliberately does NOT re-execute
    anything: it flips the durable state so the runs are listed as resumable and
    leaves the decision of what to do next to the caller and the client.
    """
    coordinator = _get_run_coordinator(request)
    if coordinator is None:
        return []
    marker = f"mission:{mission_id}"
    try:
        candidates = coordinator.find_resumable_runs()
    except Exception:
        logger.warning(
            "Could not list resumable runs for mission %s", mission_id, exc_info=True
        )
        return []
    resumed: list[str] = []
    for record in candidates:
        belongs = str(getattr(record, "session_id", "")) == mission_id or marker in [
            str(item) for item in (getattr(record, "memory_refs", []) or [])
        ]
        if not belongs:
            continue
        run_id = str(record.run_id)
        resumed.append(run_id)
        try:
            coordinator.transition(
                run_id,
                RunState.RECOVERING,
                reason=f"mission {mission_id} resumed",
            )
            logger.info(
                "[RUN] mission %s marked run %s as recovering (state=%s)",
                mission_id,
                run_id,
                getattr(record, "state", None),
            )
        except Exception:
            # An illegal move (``CREATED`` cannot reach ``RECOVERING``) or a
            # coordinator problem must not fail the mission resume itself.
            logger.warning(
                "Could not mark run %s of mission %s as recovering",
                run_id,
                mission_id,
                exc_info=True,
            )
    return resumed



def _get_meta(request: Request) -> MetaOrchestrator:
    """Retrieve or lazily initialise the MetaOrchestrator from app state."""
    meta = _meta_orchestrator(request.app)
    if meta is None:  # pragma: no cover - the app always has these
        raise HTTPException(status_code=503, detail="MetaOrchestrator is unavailable")
    return meta


def _meta_orchestrator(app: Any) -> MetaOrchestrator | None:
    """The MetaOrchestrator of *app*, or ``None`` when it cannot be built.

    Split out of :func:`_get_meta` because the WebSocket has to answer
    *before* it accepts the handshake: it needs the mission (and therefore
    the orchestrator that holds it) while the connection is still pending.
    """
    existing = getattr(app.state, "meta_orchestrator", None)
    if existing is not None:
        return existing
    try:
        from backend.orchestrator.engine import OrchestrationEngine

        registry = get_registry(app)
        engine = OrchestrationEngine(
            llm_client=app.state.llm_client,
            registry=registry,
            event_bus=app.state.event_bus,
        )
        orchestrator = MetaOrchestrator(
            engine=engine,
            event_bus=app.state.event_bus,
            llm_client=app.state.llm_client,
            registry=registry,
        )
        app.state.meta_orchestrator = orchestrator
        return orchestrator
    except Exception:
        logger.warning("Could not build the MetaOrchestrator", exc_info=True)
        return None


def _mission_owner(mission: Mission | None) -> str:
    """The user id that owns *mission* (``""`` when it has no owner)."""
    if mission is None:
        return ""
    metadata = getattr(mission, "metadata", None) or {}
    return str(metadata.get(MISSION_OWNER_KEY) or "").strip()


def _mission_belongs_to(mission: Mission | None, user_id: str) -> bool:
    """Whether *user_id* owns *mission*.

    A mission with no recorded owner is owned by nobody, so it is not
    reachable by anybody: the fail-closed answer is the only safe one for a
    resource that streams a user's objective and token counters.
    """
    owner = _mission_owner(mission)
    if not owner or not user_id:
        return False
    return owner == user_id


def _caller_id(user: dict[str, Any] | None) -> str:
    """The authenticated caller's user id."""
    return str((user or {}).get("user_id") or "").strip()


async def _refuse_websocket(websocket: WebSocket, code: int) -> None:
    """Close a WebSocket handshake with *code*, without accepting it.

    The handshake is accepted first and closed immediately afterwards, so a
    real client reads the close code instead of an opaque HTTP 403 (see
    ``backend/middleware/deny_by_default.py``).  No application data is
    exchanged either way.
    """
    try:
        await websocket.accept()
    except Exception:  # pragma: no cover - already accepted/closed
        logger.debug("Could not accept the WebSocket before refusing it", exc_info=True)
        return
    try:
        await websocket.close(code=code)
    except Exception:  # pragma: no cover - the socket is already gone
        logger.debug("Could not close the refused WebSocket", exc_info=True)


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
        "active_agents": [a.model_dump(mode="json") for a in mission.active_agents.values()],
        "metadata": mission.metadata,
    }


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/missions")
async def list_missions(request: Request, _auth: dict = Depends(require_auth)) -> dict[str, Any]:
    """List the caller's own active missions.

    Scoped: the mission store is process-wide, so listing *all* missions
    handed every tenant the objective and the token counters of everybody
    else's work.
    """
    user_id = _caller_id(_auth)
    meta = _get_meta(request)
    missions = [m for m in meta.list_all_missions() if _mission_belongs_to(m, user_id)]
    return {
        "missions": [_mission_to_status_dict(m) for m in missions],
        "count": len(missions),
    }


@router.post("/missions")
async def create_mission(
    req: CreateMissionRequest, request: Request, _auth: dict = Depends(require_auth)
) -> CreateMissionResponse:
    """Create a new dynamic mission."""
    try:
        require_disk_headroom(req.project_path)
    except DiskPressureError as exc:
        raise HTTPException(status_code=507, detail={"error": "disk_pressure", **exc.to_dict()}) from exc
    meta = _get_meta(request)
    mission = await meta.create_mission(
        objective=req.objective,
        token_budget=req.token_budget,
        time_budget_seconds=req.time_budget_seconds,
        project_path=req.project_path,
    )
    # The owner is recorded with the mission: it is what every later read of
    # this mission (REST and WebSocket) is checked against.  It is persisted
    # as well, so a mission restored after a restart keeps its owner.
    mission.metadata[MISSION_OWNER_KEY] = _caller_id(_auth)
    try:
        await meta._persist_mission(mission)
    except Exception:  # pragma: no cover - persistence is best effort
        logger.warning("Could not persist the owner of mission %s", mission.id, exc_info=True)
    # Launch mission asynchronously so the endpoint returns immediately
    asyncio.create_task(meta.run_mission(mission.id))
    return CreateMissionResponse(
        mission_id=mission.id,
        status=mission.status.value,
        objective=mission.objective,
        phases=[p.name for p in mission.phases],
    )


@router.get("/missions/{mission_id}")
async def get_mission(
    request: Request, mission_id: str, _auth: dict = Depends(require_auth)
) -> MissionStatusResponse:
    """Retrieve current mission status."""
    user_id = _caller_id(_auth)
    meta = _get_meta(request)
    mission = meta.get_mission(mission_id)
    if mission is None or not _mission_belongs_to(mission, user_id):
        # "Not found" for a mission that exists but belongs to somebody else:
        # the answer must not disclose that it exists.
        return JSONResponse(
            status_code=404,
            content={"detail": f"Mission {mission_id} not found"},
        )
    data = _mission_to_status_dict(mission)
    return MissionStatusResponse(**data)


@router.post("/missions/{mission_id}/pause")
async def pause_mission(
    request: Request, mission_id: str, _auth: dict = Depends(require_auth)
) -> MissionActionResponse:
    """Pause all agents in the mission."""
    user_id = _caller_id(_auth)
    meta = _get_meta(request)
    mission = meta.get_mission(mission_id)
    if mission is None or not _mission_belongs_to(mission, user_id):
        return JSONResponse(
            status_code=404,
            content={"detail": f"Mission {mission_id} not found"},
        )
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
async def resume_mission(
    request: Request,
    mission_id: str,
    _auth: dict = Depends(require_auth),
) -> MissionActionResponse:
    """Resume a paused or failed mission.

    Also flips the mission's durable runs to ``RECOVERING`` so a client (or the
    next agent turn) can continue them from their last checkpoint instead of
    redoing the work. Runs that cannot be associated with the mission are
    logged and left untouched.
    """
    user_id = _caller_id(_auth)
    meta = _get_meta(request)
    mission = meta.get_mission(mission_id)
    if mission is None or not _mission_belongs_to(mission, user_id):
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
    resumed_runs = _resume_mission_runs(request, mission_id)
    mission = meta.resume(mission_id)
    return MissionActionResponse(
        mission_id=mission_id,
        status=mission.status,
        resumed_runs=resumed_runs,
    )


@router.get("/runs/resumable")
async def list_resumable_runs(
    request: Request,
    _auth: dict = Depends(require_auth),
) -> ResumableRunsResponse:
    """List the durable runs that still own work (i.e. can be resumed).

    This is the recovery surface a restart populates: every run that was not
    terminal when its process stopped is here, newest first.
    """
    coordinator = _get_run_coordinator(request)
    if coordinator is None:
        return ResumableRunsResponse(runs=[], count=0)
    user_id = _caller_id(_auth)
    if not user_id:
        return ResumableRunsResponse(runs=[], count=0)
    runs = [
        record
        for record in coordinator.find_resumable_runs(user_id=user_id)
        if _run_belongs_to(record, user_id)
    ]
    return ResumableRunsResponse(
        runs=[_run_to_dict(record) for record in runs], count=len(runs)
    )


@router.post("/runs/{run_id}/resume")
async def resume_run(
    request: Request,
    run_id: str,
    _auth: dict = Depends(require_auth),
) -> ResumeRunResponse:
    """Restore one durable run from its last checkpoint.

    The run is moved to ``RECOVERING`` and its restored state — goal, plan,
    changed files, current task, and the checkpoint the run stopped at — is
    returned so the client can present it and the agent can continue from there.
    Nothing is re-executed here: resuming is a state transition, not a re-run.
    """
    coordinator = _get_run_coordinator(request)
    if coordinator is None:
        raise HTTPException(
            status_code=503, detail="Durable run coordinator is unavailable."
        )
    user_id = _caller_id(_auth)
    try:
        owned_record = coordinator.get_run(run_id) if user_id else None
    except Exception:
        logger.warning("Could not check owner for run %s", run_id, exc_info=True)
        raise HTTPException(
            status_code=503, detail="Durable run coordinator failed to load the run."
        ) from None
    if not _run_belongs_to(owned_record, user_id):
        # Keep unknown and cross-tenant run ids indistinguishable.
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        checkpoint = coordinator.restore(run_id)
    except ValueError as exc:
        # ``restore`` refuses an unknown run and a run with nothing to restore
        # from; both are the client's problem, not a server fault.
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except Exception:
        logger.warning("Could not restore run %s", run_id, exc_info=True)
        raise HTTPException(
            status_code=503, detail="Durable run coordinator failed to restore the run."
        ) from None
    try:
        record = coordinator.get_run(run_id)
    except Exception:
        logger.warning("Restored run %s but could not re-read it", run_id, exc_info=True)
        record = None
    checkpoint_payload: dict[str, Any] = dict(getattr(checkpoint, "payload", {}) or {})
    checkpoint_payload.setdefault("checkpoint_id", str(getattr(checkpoint, "checkpoint_id", "")))
    checkpoint_payload.setdefault("phase", str(getattr(checkpoint, "phase", "")))
    checkpoint_payload.setdefault("created_at", str(getattr(checkpoint, "created_at", "")))
    logger.info(
        "[RUN] resumed run %s from checkpoint phase=%s", run_id, checkpoint_payload.get("phase")
    )
    return ResumeRunResponse(
        run_id=str(run_id),
        state=str(getattr(getattr(record, "state", None), "value", "") or ""),
        goal=str(getattr(record, "goal", "") or ""),
        session_id=str(getattr(record, "session_id", "") or ""),
        project_id=str(getattr(record, "project_id", "") or ""),
        checkpoint_id=str(checkpoint_payload.get("checkpoint_id") or ""),
        phase=str(checkpoint_payload.get("phase") or ""),
        checkpoint=checkpoint_payload,
        resumable=True,
    )


@router.post("/missions/{mission_id}/abort")
async def abort_mission(
    request: Request, mission_id: str, _auth: dict = Depends(require_auth)
) -> MissionActionResponse:
    """Abort the mission and cancel all its agents."""
    user_id = _caller_id(_auth)
    meta = _get_meta(request)
    mission = meta.get_mission(mission_id)
    if mission is None or not _mission_belongs_to(mission, user_id):
        return JSONResponse(
            status_code=404,
            content={"detail": f"Mission {mission_id} not found"},
        )
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
async def list_active_agents(
    request: Request, mission_id: str, _auth: dict = Depends(require_auth)
) -> ActiveAgentsResponse:
    """List all active (non-terminal) agents in the mission."""
    user_id = _caller_id(_auth)
    meta = _get_meta(request)
    mission = meta.get_mission(mission_id)
    if mission is None or not _mission_belongs_to(mission, user_id):
        return JSONResponse(
            status_code=404,
            content={"detail": f"Mission {mission_id} not found"},
        )
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


async def mission_websocket(
    websocket: WebSocket, mission_id: str, user: dict = Depends(require_websocket_token)
) -> None:
    """WebSocket endpoint for real-time mission updates.

    Authenticated at the route level as well as at the middleware, because this
    route is mounted directly on the app (``/ws/missions/{mission_id}`` has no
    ``/api`` prefix) and streams mission events: the token may arrive in
    ``?token=`` or in ``Sec-WebSocket-Protocol``, and a missing or invalid one
    raises ``WebSocketException(4401)`` -- a close before ``accept()``, so no
    event is ever sent to an anonymous subscriber.

    **Ownership is checked before the handshake is accepted.**  The token says
    *who* is asking; it does not say *what* they may watch.  A mission
    belongs to the user who created it, and its event stream carries that
    user's objective, agent tasks and token counters, so a handshake for
    somebody else's mission is refused with ``4403`` (forbidden) instead of
    being turned into a live connection.
    """
    caller_id = _caller_id(user)
    if not caller_id:
        await _refuse_websocket(websocket, WS_FORBIDDEN_CODE)
        return

    app = websocket.app
    meta = _meta_orchestrator(app)
    mission = meta.get_mission(mission_id) if meta is not None else None
    if meta is None or mission is None or not _mission_belongs_to(mission, caller_id):
        logger.info(
            "Refused a mission WebSocket for %s: the mission is not owned by the caller",
            mission_id,
        )
        await _refuse_websocket(websocket, WS_FORBIDDEN_CODE)
        return

    await websocket.accept()
    try:
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
