"""POST /api/plan — Plan creation, approval, and execution endpoints.

Endpoints:
- POST /api/plan/create — Generate a structured execution plan
- POST /api/plan/approve — Approve a plan for execution
- POST /api/plan/execute — Execute an approved plan
- GET /api/plan/{plan_id}/status — Get plan execution status
- POST /api/plan/cancel — Cancel an active execution
- GET /api/plan/stream — SSE stream of orchestration events
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.models.api import StreamEvent
from backend.orchestrator.engine import OrchestrationEngine, OrchestrationState
from backend.orchestrator.events import EventBus, EventType

logger = logging.getLogger(__name__)
router = APIRouter()


class PlanCreateRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=10_000)
    session_id: str = Field(default="default", min_length=1, max_length=128)
    context: str = Field(default="", max_length=10_000)
    auto_approve: bool = False


class PlanApproveRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(default="default", min_length=1, max_length=128)


class PlanExecuteRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(default="default", min_length=1, max_length=128)
    project_path: str = Field(default=".", max_length=2000)


class PlanCancelRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1, max_length=128)


def _sse(event: StreamEvent) -> str:
    return f"data: {event.model_dump_json()}\n\n"


def _get_engine(request: Request) -> OrchestrationEngine:
    """Get or create the orchestration engine from app state."""
    if not hasattr(request.app.state, "orchestration_engine"):
        from backend.orchestrator.engine import OrchestrationEngine
        request.app.state.orchestration_engine = OrchestrationEngine(
            ollama=request.app.state.ollama,
            registry=request.app.state.registry,
            event_bus=request.app.state.event_bus,
        )
    return request.app.state.orchestration_engine


def _get_event_bus(request: Request) -> EventBus:
    if not hasattr(request.app.state, "event_bus"):
        request.app.state.event_bus = EventBus()
    return request.app.state.event_bus


@router.post("/plan/create")
async def create_plan(req: PlanCreateRequest, request: Request) -> dict:
    """Generate a structured execution plan for an objective."""
    engine = _get_engine(request)
    plan = await engine.create_plan(
        objective=req.objective,
        session_id=req.session_id,
        context=req.context,
    )
    return plan.to_dict()


@router.post("/plan/approve")
async def approve_plan(req: PlanApproveRequest, request: Request) -> dict:
    """Approve a plan for execution."""
    engine = _get_engine(request)
    state = engine.get_state(req.session_id)
    if state != OrchestrationState.AWAITING_APPROVAL:
        return {"error": f"Cannot approve plan in state: {state.value}"}
    return {"status": "approved", "plan_id": req.plan_id}


@router.post("/plan/execute")
async def execute_plan(req: PlanExecuteRequest, request: Request) -> dict:
    """Execute an approved plan."""
    engine = _get_engine(request)
    # Reconstruct plan from stored state (in production, fetch from DB)
    result = await engine.execute_plan(
        plan=None,  # type: ignore — will be fetched from stored state
        session_id=req.session_id,
        auto_approve=True,
        project_path=req.project_path,
    )
    return {
        "run_id": result.run_id,
        "state": result.state.value,
        "completed_tasks": result.completed_tasks,
        "failed_tasks": result.failed_tasks,
        "total_duration_ms": result.total_duration_ms,
        "tokens_used": result.tokens_used,
        "errors": result.errors,
    }


@router.get("/plan/{plan_id}/status")
async def get_plan_status(plan_id: str, request: Request) -> dict:
    """Get the current status of a plan execution."""
    engine = _get_engine(request)
    # In production, fetch plan from DB
    return {"plan_id": plan_id, "status": "unknown"}


@router.post("/plan/cancel")
async def cancel_plan(req: PlanCancelRequest, request: Request) -> dict:
    """Cancel an active plan execution."""
    engine = _get_engine(request)
    await engine.cancel(req.session_id)
    return {"status": "cancelled", "session_id": req.session_id}


@router.get("/plan/stream")
async def stream_plan_events(
    request: Request,
    session_id: str = "default",
) -> StreamingResponse:
    """Stream orchestration events as SSE."""
    event_bus = _get_event_bus(request)

    async def event_stream() -> AsyncIterator[str]:
        async for event in event_bus.stream_events(session_id=session_id):
            sse_event = StreamEvent(
                type=event.event_type.value,  # type: ignore
                agent=event.source,  # type: ignore
                content=event.content,
                timestamp=str(event.timestamp),
            )
            yield _sse(sse_event)
        yield _sse(StreamEvent(type="done"))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
