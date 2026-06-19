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

import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.middleware.auth import require_auth
from backend.models.api import StreamEvent
from backend.orchestrator.engine import OrchestrationEngine, OrchestrationState
from backend.orchestrator.events import EventBus
from backend.orchestrator.registry import get_registry

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
            llm_client=request.app.state.llm_client,
            registry=get_registry(request.app),
            event_bus=request.app.state.event_bus,
        )
    return request.app.state.orchestration_engine


def _get_event_bus(request: Request) -> EventBus:
    if not hasattr(request.app.state, "event_bus"):
        request.app.state.event_bus = EventBus()
    return request.app.state.event_bus


@router.post("/plan/create")
async def create_plan(
    req: PlanCreateRequest,
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict:
    """Generate a structured execution plan for an objective."""
    engine = _get_engine(request)
    plan = await engine.create_plan(
        objective=req.objective,
        session_id=req.session_id,
        context=req.context,
    )
    return plan.to_dict()


@router.post("/plan/approve")
async def approve_plan(
    req: PlanApproveRequest,
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict:
    """Approve a plan for execution."""
    engine = _get_engine(request)
    state = engine.get_state(req.session_id)
    if state != OrchestrationState.AWAITING_APPROVAL:
        return {"error": f"Cannot approve plan in state: {state.value}"}

    # Mark the plan as approved
    plan = engine.get_plan(req.plan_id)
    if plan is None:
        plan = engine.get_plan_by_session(req.session_id)
    if plan is not None:
        plan.approved = True

    return {"status": "approved", "plan_id": req.plan_id}


@router.post("/plan/execute")
async def execute_plan(
    req: PlanExecuteRequest,
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict:
    """Execute an approved plan."""
    engine = _get_engine(request)

    # Fetch plan from engine's in-memory store
    plan = engine.get_plan(req.plan_id)
    if plan is None:
        # Fallback: try to find plan by session
        plan = engine.get_plan_by_session(req.session_id)
    if plan is None:
        return {"error": f"Plan {req.plan_id} not found. Create a plan first via /api/plan/create"}

    plan.approved = True  # Mark as approved for execution

    result = await engine.execute_plan(
        plan=plan,
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
async def get_plan_status(
    plan_id: str,
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict:
    """Get the current status of a plan execution."""
    engine = _get_engine(request)
    plan = engine.get_plan(plan_id)
    if plan is None:
        return {"plan_id": plan_id, "status": "not_found"}

    state = engine.get_state(plan.session_id)
    steps_info = []
    for step in plan.steps:
        steps_info.append(
            {
                "task_id": step.task_id,
                "name": step.name,
                "agent": step.agent,
                "status": step.status.value,
                "error_message": step.error_message,
            }
        )

    return {
        "plan_id": plan_id,
        "status": state.value,
        "title": plan.title,
        "total_steps": len(plan.steps),
        "steps": steps_info,
        "requires_approval": plan.requires_approval,
        "approved": plan.approved,
    }


@router.post("/plan/cancel")
async def cancel_plan(
    req: PlanCancelRequest,
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict:
    """Cancel an active plan execution."""
    engine = _get_engine(request)
    await engine.cancel(req.session_id)
    return {"status": "cancelled", "session_id": req.session_id}


@router.get("/plan/stream")
async def stream_plan_events(
    request: Request,
    session_id: str = "default",
    _user: dict = Depends(require_auth),
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
