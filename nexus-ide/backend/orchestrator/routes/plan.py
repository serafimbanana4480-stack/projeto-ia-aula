"""POST /api/plan — Plan creation, approval, and execution endpoints.

Endpoints:
- POST /api/plan/create             — Generate a structured execution plan
- POST /api/plan/approve             — Approve a plan for execution (legacy)
- POST /api/plan/execute             — Execute an approved plan
- GET  /api/plan/{plan_id}/status    — Get plan execution status
- POST /api/plan/{plan_id}/approve   — Approve a specific plan
- POST /api/plan/{plan_id}/reject    — Reject a specific plan
- POST /api/plan/{plan_id}/modify    — Modify a plan awaiting approval
- POST /api/plan/cancel              — Cancel an active execution
- GET  /api/plan/stream              — SSE stream of orchestration events
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


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class PlanCreateRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=10_000)
    session_id: str = Field(default="default", min_length=1, max_length=128)
    context: str = Field(default="", max_length=10_000)
    # The product default is unattended execution. Callers that need a review
    # gate can still send ``auto_approve=false`` explicitly.
    auto_approve: bool = True


class PlanApproveRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(default="default", min_length=1, max_length=128)


class PlanExecuteRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(default="default", min_length=1, max_length=128)
    project_path: str = Field(default=".", max_length=2000)


class PlanCancelRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1, max_length=128)


class PlanRejectRequest(BaseModel):
    reason: str = Field(default="", max_length=2000)


class PlanModificationSchema(BaseModel):
    """Describes a single new step to add to a plan via ``modify``."""

    name: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=2000)
    agent: str = Field(default="CODER", max_length=50)
    priority: str = Field(default="medium", max_length=20)
    sandboxed: bool = False
    depends_on: list[int] = Field(default_factory=list)


class PlanModifyRequest(BaseModel):
    """Modifications to apply to a plan that is awaiting approval."""

    steps_to_remove: list[int] = Field(
        default_factory=list, description="0-based step indices to remove"
    )
    steps_to_add: list[PlanModificationSchema] = Field(
        default_factory=list, description="New steps to append"
    )
    steps_to_reorder: list[int] = Field(
        default_factory=list, description="All step indices in desired order"
    )
    title: str | None = Field(default=None, max_length=500)
    risk_level: str | None = Field(default=None, max_length=20)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Endpoints — Plan CRUD & Approval
# ---------------------------------------------------------------------------


@router.post("/plan/create")
async def create_plan(
    req: PlanCreateRequest,
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict:
    """Generate a structured execution plan for an objective.

    By default the plan is auto-approved for unattended execution. Send
    ``auto_approve=false`` explicitly when a human review gate is required.
    """
    engine = _get_engine(request)
    plan = await engine.create_plan(
        objective=req.objective,
        session_id=req.session_id,
        context=req.context,
        auto_approve=req.auto_approve,
    )

    result = plan.to_dict()
    # Add approval-request metadata when the plan is blocked
    if not req.auto_approve:
        approval_req = engine.request_approval(plan.plan_id)
        if approval_req:
            result["approval"] = approval_req.to_dict()

    return result


@router.post("/plan/approve")
async def approve_plan_legacy(
    req: PlanApproveRequest,
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict:
    """Approve a plan for execution (legacy endpoint).

    Delegates to ``POST /api/plan/{plan_id}/approve`` internally.
    """
    engine = _get_engine(request)
    user_id = _user.get("user_id", "anonymous")

    result = await engine.approve_plan(req.plan_id, user_id)
    if result is None:
        return {
            "error": (
                f"Plan {req.plan_id} not found or not in AWAITING_APPROVAL state. "
                "Create a plan first via POST /api/plan/create"
            )
        }

    return {
        "status": "approved",
        "plan_id": req.plan_id,
        "run_id": result.run_id,
        "state": result.state.value,
        "completed_tasks": result.completed_tasks,
        "failed_tasks": result.failed_tasks,
        "total_duration_ms": result.total_duration_ms,
        "tokens_used": result.tokens_used,
        "errors": result.errors,
    }


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
    """Stream orchestration events as SSE.

    The stream emits ``plan_awaiting_approval`` events when a plan is
    ready for user review. The frontend should show a modal/banner.
    """
    event_bus = _get_event_bus(request)

    async def event_stream() -> AsyncIterator[str]:
        async for event in event_bus.stream_events(session_id=session_id):
            sse_event = StreamEvent(
                type=event.event_type.value,  # type: ignore
                agent=event.source,  # type: ignore
                content=event.content,
                timestamp=str(event.timestamp),
                data=event.data if event.data else {},
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


# ---------------------------------------------------------------------------
# New per-plan approval endpoints
# ---------------------------------------------------------------------------


@router.get("/plans/{plan_id}")
async def get_plan_by_id(
    plan_id: str,
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict:
    """Return a plan with all its tasks and approval metadata.

    The frontend can use this to render the plan review UI.
    """
    engine = _get_engine(request)
    plan = engine.get_plan(plan_id)
    if plan is None:
        return {"error": f"Plan {plan_id} not found"}

    state = engine.get_state(plan.session_id)
    approval_req = engine.request_approval(plan_id)

    return {
        "plan_id": plan.plan_id,
        "title": plan.title,
        "description": plan.description,
        "session_id": plan.session_id,
        "status": state.value,
        "requires_approval": plan.requires_approval,
        "approved": plan.approved,
        "approved_by": plan.approved_by,
        "risk_level": plan.risk_level,
        "estimated_duration_seconds": plan.estimated_duration_seconds,
        "total_steps": len(plan.steps),
        "parallel_layers": len(plan.dependency_graph.topological_layers()),
        "approval": approval_req.to_dict() if approval_req else None,
        "tasks": [
            {
                "task_id": s.task_id,
                "name": s.name,
                "description": s.description,
                "agent": s.agent,
                "priority": s.priority.name,
                "status": s.status.value,
                "depends_on": s.depends_on,
                "timeout_seconds": s.timeout_seconds,
                "sandboxed": s.sandboxed,
            }
            for s in plan.steps
        ],
    }


@router.post("/plans/{plan_id}/approve")
async def approve_plan_by_id(
    plan_id: str,
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict:
    """Approve a plan that is awaiting approval.

    The engine will immediately execute the approved plan and return the
    orchestration result.
    """
    engine = _get_engine(request)
    user_id = _user.get("user_id", "anonymous")

    # Check plan exists and is in correct state
    plan = engine.get_plan(plan_id)
    if plan is None:
        return {"error": f"Plan {plan_id} not found"}

    session_id = plan.session_id
    state = engine.get_state(session_id)
    if state != OrchestrationState.AWAITING_APPROVAL:
        return {
            "error": f"Cannot approve plan in state '{state.value}'. Expected 'awaiting_approval'."
        }

    result = await engine.approve_plan(plan_id, user_id)
    if result is None:
        return {"error": f"Failed to approve plan {plan_id}"}

    logger.info(
        "Plan %s approved by user %s — execution result: state=%s",
        plan_id,
        user_id,
        result.state.value,
    )

    return {
        "status": "approved",
        "plan_id": plan_id,
        "approved_by": user_id,
        "run_id": result.run_id,
        "state": result.state.value,
        "completed_tasks": result.completed_tasks,
        "failed_tasks": result.failed_tasks,
        "total_duration_ms": result.total_duration_ms,
        "tokens_used": result.tokens_used,
        "errors": result.errors,
    }


@router.post("/plans/{plan_id}/reject")
async def reject_plan_by_id(
    plan_id: str,
    req: PlanRejectRequest,
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict:
    """Reject a plan that is awaiting approval.

    The plan transitions to ``CANCELLED`` and no execution occurs.
    """
    engine = _get_engine(request)

    plan = engine.get_plan(plan_id)
    if plan is None:
        return {"error": f"Plan {plan_id} not found"}

    session_id = plan.session_id
    state = engine.get_state(session_id)
    if state != OrchestrationState.AWAITING_APPROVAL:
        return {
            "error": f"Cannot reject plan in state '{state.value}'. Expected 'awaiting_approval'."
        }

    success = await engine.reject_plan(plan_id, reason=req.reason)
    if not success:
        return {"error": f"Failed to reject plan {plan_id}"}

    logger.info("Plan %s rejected (reason: %s)", plan_id, req.reason or "none")

    return {
        "status": "rejected",
        "plan_id": plan_id,
        "reason": req.reason,
    }


@router.post("/plans/{plan_id}/modify")
async def modify_plan_by_id(
    plan_id: str,
    req: PlanModifyRequest,
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict:
    """Modify a plan that is awaiting approval.

    Supports removing steps, adding new steps, reordering, and changing
    title/risk level. Returns the updated plan.
    """
    engine = _get_engine(request)

    plan = engine.get_plan(plan_id)
    if plan is None:
        return {"error": f"Plan {plan_id} not found"}

    session_id = plan.session_id
    state = engine.get_state(session_id)
    if state != OrchestrationState.AWAITING_APPROVAL:
        return {
            "error": f"Cannot modify plan in state '{state.value}'. Expected 'awaiting_approval'."
        }

    # Convert Pydantic models to dicts for the engine
    modifications: dict = {}
    if req.steps_to_remove:
        modifications["steps_to_remove"] = req.steps_to_remove
    if req.steps_to_add:
        modifications["steps_to_add"] = [s.model_dump() for s in req.steps_to_add]
    if req.steps_to_reorder:
        modifications["steps_to_reorder"] = req.steps_to_reorder
    if req.title is not None:
        modifications["title"] = req.title
    if req.risk_level is not None:
        modifications["risk_level"] = req.risk_level

    updated = await engine.modify_plan(plan_id, modifications)
    if updated is None:
        return {"error": f"Failed to modify plan {plan_id}"}

    logger.info(
        "Plan %s modified by user — steps: %d, title: %s",
        plan_id,
        len(updated.steps),
        updated.title[:80],
    )

    return {
        "status": "modified",
        "plan_id": plan_id,
        "plan": {
            "title": updated.title,
            "description": updated.description,
            "risk_level": updated.risk_level,
            "total_steps": len(updated.steps),
            "estimated_duration_seconds": updated.estimated_duration_seconds,
            "tasks": [
                {
                    "task_id": s.task_id,
                    "name": s.name,
                    "description": s.description,
                    "agent": s.agent,
                    "priority": s.priority.name,
                    "depends_on": s.depends_on,
                }
                for s in updated.steps
            ],
        },
    }
