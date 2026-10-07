
"""Dashboard task views over the live workflow tracker.

The workflow tracker is the runtime source used by the orchestrator and by
``GET /api/workflows``. These dashboard summaries describe this process's
in-memory workflows; they are not a persisted history.
"""

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.middleware.auth import require_auth
from backend.observability.workflow_tracker import Workflow
from backend.orchestrator.dependency_graph import ExecutionPlan
from backend.orchestrator.types import OrchestrationState

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_auth)])


class TaskInfo(BaseModel):
    """Task information."""
    id: str
    title: str
    agent: str = ""
    status: str
    progress: float | None = None
    created_at: str | None = None
    kind: str = "workflow"


def _task_from_workflow(workflow: Workflow) -> dict:
    """Map the live workflow tracker record to the dashboard task contract."""
    agent = next(
        (step.agent for step in reversed(workflow.steps) if step.agent.strip()),
        "Agente não identificado",
    )
    return {
        "id": workflow.workflow_id,
        "title": workflow.goal or "Workflow sem objetivo",
        "agent": agent,
        "status": workflow.status,
        # WorkflowTracker does not record an overall progress measurement.
        "progress": None,
        "created_at": datetime.fromtimestamp(workflow.created_at, UTC).isoformat(),
        "error": next(
            (step.error for step in reversed(workflow.steps) if step.status == "failed" and step.error),
            None,
        ),
    }


def _get_workflows(limit: int = 1000) -> list[Workflow]:
    """Read the same in-process source used by ``GET /api/workflows``."""
    from backend.observability.routes.workflows import get_workflow_tracker

    try:
        return get_workflow_tracker().list_workflows(limit=limit)
    except RuntimeError as exc:
        logger.warning("Workflow tracker is unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Workflow data is temporarily unavailable.",
        ) from exc


def _list_plan_tasks(request: Request) -> tuple[list[dict], str | None, bool]:
    """Read actual plan and step status from the orchestration engine, if live."""
    engine = getattr(request.app.state, "orchestration_engine", None)
    if engine is None:
        # No plan route has initialized the engine in this process yet. This is
        # an empty source, not a failed source.
        return [], None, False

    try:
        plans = engine.list_plans()
        return [_task_from_plan(engine, plan) for plan in plans], None, True
    except Exception:
        logger.exception("Could not read plans for the task dashboard")
        return [], "Os planos não estão disponíveis neste momento.", True


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _task_from_plan(engine: object, plan: ExecutionPlan) -> dict:
    """Serialize a plan from its authoritative state and step records."""
    steps = list(plan.steps)
    step_statuses = [_enum_value(step.status) for step in steps]
    try:
        run_state = _enum_value(engine.get_state(plan.session_id))  # type: ignore[attr-defined]
    except Exception:
        run_state = "unknown"
    get_plan_by_session = getattr(engine, "get_plan_by_session", None)
    if callable(get_plan_by_session):
        try:
            current_plan = get_plan_by_session(plan.session_id)
        except Exception:
            current_plan = None
        if current_plan is not None and current_plan.plan_id != plan.plan_id:
            # Engine lifecycle state is session-scoped. An older plan from the
            # same session must be read from its own steps, not from a later run.
            run_state = "idle"

    try:
        has_approval_request = engine.request_approval(plan.plan_id) is not None  # type: ignore[attr-defined]
    except Exception:
        has_approval_request = False

    if any(status in {"failed", "blocked"} for status in step_statuses) or run_state == "failed":
        status = "failed"
    elif run_state == "cancelled" or "cancelled" in step_statuses:
        status = "cancelled"
    elif run_state == "completed" or (
        bool(step_statuses)
        and all(value in {"completed", "skipped"} for value in step_statuses)
    ):
        status = "completed"
    elif run_state == "paused":
        status = "paused"
    elif (
        run_state == "executing"
        or any(value in {"running", "retrying"} for value in step_statuses)
    ):
        status = "running"
    elif not plan.approved and (
        has_approval_request or run_state == OrchestrationState.AWAITING_APPROVAL.value
    ):
        status = "awaiting_approval"
    elif plan.approved:
        status = "approved"
    else:
        status = "pending"

    approval_status = (
        "not_required"
        if not plan.requires_approval
        else "approved"
        if plan.approved
        else "awaiting_approval"
        if status == "awaiting_approval"
        else "not_approved"
    )
    created_at = None
    if isinstance(plan.created_at, (int, float)) and plan.created_at > 0:
        created_at = datetime.fromtimestamp(plan.created_at, UTC).isoformat()

    return {
        "id": plan.plan_id,
        "title": plan.title or plan.description or "Plano sem título",
        # A plan's assigned agents are represented per step. Do not assign one
        # arbitrary agent to the complete plan.
        "agent": "",
        "status": status,
        "progress": None,
        "created_at": created_at,
        "kind": "plan",
        "requires_approval": plan.requires_approval,
        "approved": plan.approved,
        "approval_status": approval_status,
        "completed_steps": sum(value == "completed" for value in step_statuses),
        "total_steps": len(steps),
        "steps": [
            {
                "id": step.task_id,
                "title": step.name,
                "description": step.description,
                "agent": step.agent,
                "status": _enum_value(step.status),
                "error": step.error_message or None,
                "depends_on": list(step.depends_on),
            }
            for step in steps
        ],
    }


def _task_source_rows(request: Request) -> tuple[list[dict], list[str], bool, dict[str, dict[str, bool]]]:
    """Merge the two real in-process task sources without hiding partial failures."""
    errors: list[str] = []
    rows: list[dict] = []
    source_count = 0
    workflow_available = False

    try:
        workflows = _get_workflows()
        rows.extend(_task_from_workflow(workflow) | {"kind": "workflow"} for workflow in workflows)
        source_count += 1
        workflow_available = True
    except HTTPException:
        logger.exception("Workflow tracker could not be read for the task dashboard")
        errors.append("Os workflows não estão disponíveis neste momento.")

    plans, plan_error, plans_initialized = _list_plan_tasks(request)
    if plan_error:
        errors.append(plan_error)
    else:
        rows.extend(plans)
        source_count += 1

    return rows, errors, source_count > 0, {
        "workflows": {"available": workflow_available, "initialized": True},
        "plans": {"available": plan_error is None, "initialized": plans_initialized},
    }


def _group_tasks(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {
        "active": [],
        "queued": [],
        "completed": [],
        "failed": [],
        "cancelled": [],
    }
    for row in rows:
        status = str(row.get("status", "unknown")).lower()
        if status in {"running", "active", "retrying", "paused"}:
            groups["active"].append(row)
        elif status in {"pending", "ready", "queued", "approved", "awaiting_approval"}:
            groups["queued"].append(row)
        elif status in {"failed", "blocked"}:
            groups["failed"].append(row)
        elif status == "completed":
            groups["completed"].append(row)
        elif status == "cancelled":
            groups["cancelled"].append(row)
        else:
            row["status"] = "unknown"
            groups["queued"].append(row)

    def created_timestamp(row: dict) -> float:
        value = row.get("created_at")
        if not isinstance(value, str):
            return 0.0
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0

    for group in groups.values():
        group.sort(key=created_timestamp, reverse=True)
    return groups


@router.get("/tasks/pipeline")
async def get_task_pipeline(request: Request) -> dict:
    """Return current task pipeline counts from available live sources."""
    rows, errors, available, sources = _task_source_rows(request)
    if not available:
        raise HTTPException(status_code=503, detail="; ".join(errors) or "Task data unavailable")
    groups = _group_tasks(rows)
    return {
        "phases": [
            {"name": "Planning", "status": "active" if groups["queued"] else "idle", "count": len(groups["queued"])},
            {"name": "Execution", "status": "active" if groups["active"] else "idle", "count": len(groups["active"])},
            {"name": "Completed", "status": "idle", "count": len(groups["completed"])},
            {"name": "Failed", "status": "active" if groups["failed"] else "idle", "count": len(groups["failed"])},
        ],
        "active_runs": len(groups["active"]),
        "warnings": errors,
        "sources": sources,
    }


@router.get("/tasks/list")
async def get_tasks_list(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Return a page from each task state, with totals and source health."""
    rows, errors, available, sources = _task_source_rows(request)
    if not available:
        raise HTTPException(status_code=503, detail="; ".join(errors) or "Task data unavailable")
    groups = _group_tasks(rows)
    pagination = {
        name: {
            "offset": offset,
            "limit": limit,
            "total": len(group),
            "has_more": offset + limit < len(group),
        }
        for name, group in groups.items()
    }
    return {
        **{name: group[offset : offset + limit] for name, group in groups.items()},
        "pagination": pagination,
        "warnings": errors,
        "sources": sources,
    }


@router.get("/tasks/active", tags=["tasks"])
async def get_active_tasks(request: Request) -> dict:
    """Return live and queued workflow/plan items from available sources."""
    rows, errors, available, sources = _task_source_rows(request)
    if not available:
        raise HTTPException(status_code=503, detail="; ".join(errors) or "Task data unavailable")
    active = [
        row for row in rows
        if str(row.get("status", "")).lower()
        in {"running", "active", "retrying", "paused", "pending", "ready", "queued", "approved", "awaiting_approval"}
    ][:50]
    return {"tasks": active, "warnings": errors, "sources": sources}


@router.get("/tasks/stream")
async def tasks_stream() -> StreamingResponse:
    """Stream real-time task updates via SSE."""
    async def event_generator() -> AsyncIterator[str]:
        import asyncio

        while True:
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
