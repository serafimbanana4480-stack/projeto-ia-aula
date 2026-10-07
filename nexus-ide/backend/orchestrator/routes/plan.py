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

import hashlib
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.middleware.auth import require_auth
from backend.models.api import StreamEvent
from backend.orchestrator.dependency_graph import ExecutionPlan
from backend.orchestrator.engine import OrchestrationEngine, OrchestrationState
from backend.orchestrator.events import EventBus
from backend.orchestrator.registry import get_registry
from backend.persistence.db import add_message, create_session, get_session_for_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class PlanCreateRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=10_000)
    session_id: str = Field(default="default", min_length=1, max_length=128)
    context: str = Field(default="", max_length=10_000)
    auto_approve: bool = False
    persist_conversation: bool = False


class PlanApproveRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(default="default", min_length=1, max_length=128)


class PlanContinueRequest(BaseModel):
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


def _authenticated_user_id(user: dict) -> str:
    user_id = str(user.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Authenticated user is missing an id")
    return user_id


def _resolve_owned_session(
    session_id: str,
    user_id: str,
    *,
    create_default: bool = False,
) -> str:
    """Resolve the implicit default session and enforce durable ownership."""
    is_default = session_id == "default"
    if is_default:
        user_suffix = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]
        session_id = f"default-{user_suffix}"

    if get_session_for_user(session_id, user_id) is not None:
        return session_id

    if create_default and is_default:
        try:
            create_session(
                title="Plano",
                mode="auto",
                session_id=session_id,
                user_id=user_id,
            )
        except Exception:
            # The first request can race with chat's creation of the same
            # user-scoped default session. Accept only that user's row.
            if get_session_for_user(session_id, user_id) is None:
                raise HTTPException(status_code=404, detail="Session not found") from None
        if get_session_for_user(session_id, user_id) is not None:
            return session_id

    raise HTTPException(status_code=404, detail="Session not found")


def _get_owned_plan(engine: OrchestrationEngine, plan_id: str, user_id: str) -> ExecutionPlan:
    plan = engine.get_plan(plan_id)
    if plan is None or get_session_for_user(plan.session_id, user_id) is None:
        # Use one response for absent and foreign plans to avoid disclosing IDs.
        raise HTTPException(status_code=404, detail="Plano não encontrado")
    return plan


def _require_current_pending_plan(
    engine: OrchestrationEngine,
    plan: ExecutionPlan,
) -> None:
    current_plan = engine.get_plan_by_session(plan.session_id)
    approval_request = engine.request_approval(plan.plan_id)
    if (
        current_plan is None
        or current_plan.plan_id != plan.plan_id
        or approval_request is None
        or getattr(approval_request, "session_id", plan.session_id) != plan.session_id
        or plan.approved
        or not plan.requires_approval
    ):
        raise HTTPException(
            status_code=409,
            detail="O plano já não tem um pedido de aprovação pendente nesta sessão.",
        )


def _plan_state_for_status(engine: OrchestrationEngine, plan: ExecutionPlan) -> str:
    """Return a plan's state without borrowing a later plan's session state.

    The engine's execution state is keyed by session, while plan records live
    by plan ID. If the session has since started another plan, derive the old
    plan's lifecycle from its own step records and approval request instead.
    """
    state = engine.get_state(plan.session_id)
    current_plan = engine.get_plan_by_session(plan.session_id)
    if current_plan is None or current_plan.plan_id == plan.plan_id:
        return state.value

    steps = list(plan.steps)
    step_statuses = [step.status.value for step in steps]
    if any(status in {"failed", "blocked"} for status in step_statuses):
        return OrchestrationState.FAILED.value
    if "cancelled" in step_statuses:
        return OrchestrationState.CANCELLED.value
    if steps and all(status in {"completed", "skipped"} for status in step_statuses):
        return OrchestrationState.COMPLETED.value
    if any(status in {"running", "retrying"} for status in step_statuses):
        return OrchestrationState.EXECUTING.value
    if not plan.approved and engine.request_approval(plan.plan_id) is not None:
        return OrchestrationState.AWAITING_APPROVAL.value
    if plan.approved:
        return "approved"
    return "pending"


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

    Plans require an explicit approval by default. Callers may opt into
    unattended approval deliberately; chat clients can also persist the
    objective and generated plan in the session transcript.
    """
    user_id = _authenticated_user_id(_user)
    req.session_id = _resolve_owned_session(req.session_id, user_id, create_default=True)

    engine = _get_engine(request)
    current_plan = engine.get_plan_by_session(req.session_id)
    if (
        current_plan is not None
        and engine.get_state(req.session_id) == OrchestrationState.AWAITING_APPROVAL
        and engine.request_approval(current_plan.plan_id) is not None
    ):
        raise HTTPException(
            status_code=409,
            detail="Esta sessão já tem um plano à espera de aprovação.",
        )
    planning = await engine.create_plan(
        objective=req.objective,
        session_id=req.session_id,
        context=req.context,
        auto_approve=req.auto_approve,
    )

    result = planning.to_dict()
    if req.persist_conversation:
        add_message(req.session_id, "user", req.objective)
    # Add approval-request metadata when the plan is blocked
    if planning.plan is not None and not req.auto_approve:
        approval_req = engine.request_approval(planning.plan.plan_id)
        if approval_req:
            result["approval"] = approval_req.to_dict()

    if req.persist_conversation:
        plan = planning.plan or planning.deterministic_proposal
        if plan is not None:
            lines = ["# Plano de execução", f"**Objetivo:** {req.objective}", ""]
            if planning.status == "blocked":
                lines.append(
                    "> O planeamento automático foi bloqueado; esta proposta segura precisa de revisão.\n"
                )
            for index, step in enumerate(plan.steps, 1):
                lines.extend(
                    [
                        f"## Passo {index}: {step.name}",
                        f"- **Agente:** {step.agent}",
                        f"- **Descrição:** {step.description}",
                    ]
                )
                if step.depends_on:
                    lines.append(f"- **Depende de:** {', '.join(step.depends_on)}")
                lines.append("")
            add_message(req.session_id, "assistant", "\n".join(lines))
        elif planning.error:
            add_message(req.session_id, "assistant", f"O planeamento foi bloqueado: {planning.error}")

    return result


@router.post("/plan/continue")
async def continue_plan(
    req: PlanContinueRequest,
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict:
    """Expose a validated fallback only after an explicit user decision.

    Malformed provider formatting therefore does not strand the workflow, but
    it also cannot silently become an auto-approved multi-agent execution.
    """
    user_id = _authenticated_user_id(_user)
    req.session_id = _resolve_owned_session(req.session_id, user_id)
    engine = _get_engine(request)
    planning = await engine.continue_planning(req.session_id)
    if planning is None or planning.plan is None:
        raise HTTPException(
            status_code=409,
            detail="Não existe uma proposta segura bloqueada para continuar nesta sessão.",
        )
    result = planning.to_dict()
    approval = engine.request_approval(planning.plan.plan_id)
    if approval is not None:
        result["approval"] = approval.to_dict()
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
    user_id = _authenticated_user_id(_user)
    req.session_id = _resolve_owned_session(req.session_id, user_id)
    plan = _get_owned_plan(engine, req.plan_id, user_id)
    if plan.session_id != req.session_id:
        raise HTTPException(
            status_code=404,
            detail="O plano não pertence à sessão ativa. Atualiza a conversa e tenta novamente.",
        )
    _require_current_pending_plan(engine, plan)
    state = engine.get_state(plan.session_id)
    if state != OrchestrationState.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Não é possível aprovar o plano no estado '{state.value}'. "
                "É necessária aprovação pendente."
            ),
        )

    result = await engine.approve_plan(req.plan_id, user_id)
    if result is None:
        raise HTTPException(
            status_code=409,
            detail=f"O plano {req.plan_id} deixou de estar disponível para aprovação.",
        )

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
    user_id = _authenticated_user_id(_user)
    req.session_id = _resolve_owned_session(req.session_id, user_id)
    engine = _get_engine(request)

    # Fetch plan from engine's in-memory store
    plan = engine.get_plan(req.plan_id)
    if plan is None:
        raise HTTPException(
            status_code=404,
            detail=f"O plano {req.plan_id} não foi encontrado. Cria novamente o plano nesta conversa.",
        )
    if get_session_for_user(plan.session_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Plano não encontrado")
    if plan.session_id != req.session_id:
        raise HTTPException(
            status_code=404,
            detail="O plano não pertence à sessão ativa. Atualiza a conversa e tenta novamente.",
        )

    if plan.requires_approval and not plan.approved:
        raise HTTPException(
            status_code=409,
            detail="O plano requer aprovação explícita antes da execução.",
        )

    result = await engine.execute_plan(
        plan=plan,
        session_id=req.session_id,
        auto_approve=False,
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
    user_id = _authenticated_user_id(_user)
    engine = _get_engine(request)
    plan = engine.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"O plano {plan_id} não foi encontrado.")
    if get_session_for_user(plan.session_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Plano não encontrado")

    status = _plan_state_for_status(engine, plan)
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
        "status": status,
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
    user_id = _authenticated_user_id(_user)
    req.session_id = _resolve_owned_session(req.session_id, user_id)
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
    user_id = _authenticated_user_id(_user)
    session_id = _resolve_owned_session(session_id, user_id)
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
    user_id = _authenticated_user_id(_user)
    engine = _get_engine(request)
    plan = _get_owned_plan(engine, plan_id, user_id)

    state = _plan_state_for_status(engine, plan)
    approval_req = engine.request_approval(plan_id)

    return {
        "plan_id": plan.plan_id,
        "title": plan.title,
        "description": plan.description,
        "session_id": plan.session_id,
        "status": state,
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
    user_id = _authenticated_user_id(_user)
    engine = _get_engine(request)

    # Check plan exists and is in correct state
    plan = _get_owned_plan(engine, plan_id, user_id)
    _require_current_pending_plan(engine, plan)

    session_id = plan.session_id
    state = engine.get_state(session_id)
    if state != OrchestrationState.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail=f"Não é possível aprovar o plano no estado '{state.value}'. É necessária aprovação pendente.",
        )

    result = await engine.approve_plan(plan_id, user_id)
    if result is None:
        raise HTTPException(
            status_code=409,
            detail=f"O plano {plan_id} deixou de estar disponível para aprovação.",
        )

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
    user_id = _authenticated_user_id(_user)
    engine = _get_engine(request)

    plan = _get_owned_plan(engine, plan_id, user_id)
    _require_current_pending_plan(engine, plan)

    session_id = plan.session_id
    state = engine.get_state(session_id)
    if state != OrchestrationState.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail=f"Não é possível rejeitar o plano no estado '{state.value}'. É necessária aprovação pendente.",
        )

    success = await engine.reject_plan(plan_id, reason=req.reason)
    if not success:
        raise HTTPException(
            status_code=409,
            detail=f"O plano {plan_id} deixou de estar disponível para rejeição.",
        )

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
    user_id = _authenticated_user_id(_user)
    engine = _get_engine(request)

    plan = _get_owned_plan(engine, plan_id, user_id)
    _require_current_pending_plan(engine, plan)

    session_id = plan.session_id
    state = engine.get_state(session_id)
    if state != OrchestrationState.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail=f"Não é possível alterar o plano no estado '{state.value}'. É necessária aprovação pendente.",
        )

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
        raise HTTPException(
            status_code=409,
            detail=f"O plano {plan_id} deixou de estar disponível para alteração.",
        )

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
