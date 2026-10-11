"""Routes for autonomous tasks management.

The task manager is a lifespan-owned singleton exposed as
``app.state.task_manager``. The lifespan starts the scheduler (subject to
``NEXUS_TASKS_RESUME_PENDING`` and the background-services toggle); these routes
only read/act on that instance. The previous per-handler event-bus construction
and the duplicate ``get_autonomous_task_manager`` wiring are gone.

Status/type filtering uses the task manager as the single source of truth: an
unrecognised status string is a 400, and only real task states are returned.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.middleware.auth import require_auth
from backend.tasks.autonomous_tasks import TaskPriority, TaskType

router = APIRouter(dependencies=[Depends(require_auth)])


class TaskCreateRequest(BaseModel):
    """Request body for POST /api/tasks."""

    name: str
    task_type: str = "monitoring"
    priority: str = "normal"
    handler_name: str
    parameters: dict[str, Any] | None = None
    interval: int | None = None
    max_retries: int = Field(default=3, ge=0, le=100)
    timeout: int = Field(default=300, gt=0, le=86400)
    auto_retry: bool = True
    scheduled_at: str | None = None


async def _get_task_manager(request: Request) -> Any:
    """Resolve the lifespan-owned task manager from application state.

    Falls back to the process-wide singleton only when the lifespan has not
    installed one (e.g. the scheduler is disabled or this runs outside it).
    """
    manager = getattr(request.app.state, "task_manager", None)
    if manager is not None:
        return manager

    from backend.observability.event_system import get_event_bus
    from backend.tasks.autonomous_tasks import get_autonomous_task_manager

    manager = await get_autonomous_task_manager(await get_event_bus())
    request.app.state.task_manager = manager
    return manager


def _coerce_task_type(value: str) -> TaskType:
    try:
        return TaskType(str(value).strip().lower())
    except ValueError as exc:
        available = [t.value for t in TaskType]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid task_type '{value}'. Available: {available}",
        ) from exc


def _coerce_priority(value: str) -> TaskPriority:
    try:
        return TaskPriority(str(value).strip().lower())
    except ValueError as exc:
        available = [p.value for p in TaskPriority]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid priority '{value}'. Available: {available}",
        ) from exc


@router.get("/tasks")
async def list_tasks(
    task_manager: Any = Depends(_get_task_manager),
) -> dict[str, Any]:
    """Get all autonomous tasks."""
    tasks = await task_manager.get_tasks()
    return {
        "tasks": [t.to_dict() for t in tasks],
        "count": len(tasks),
    }


@router.get("/tasks/running")
async def get_running_tasks(
    task_manager: Any = Depends(_get_task_manager),
) -> dict[str, Any]:
    """Get currently running autonomous tasks."""
    tasks = await task_manager.get_tasks(status="running")
    return {
        "tasks": [t.to_dict() for t in tasks],
        "count": len(tasks),
    }


@router.get("/tasks/completed")
async def get_completed_tasks(
    task_manager: Any = Depends(_get_task_manager),
) -> dict[str, Any]:
    """Get completed autonomous tasks."""
    tasks = await task_manager.get_tasks(status="completed")
    return {
        "tasks": [t.to_dict() for t in tasks],
        "count": len(tasks),
    }


@router.get("/tasks/failed")
async def get_failed_tasks(
    task_manager: Any = Depends(_get_task_manager),
) -> dict[str, Any]:
    """Get failed autonomous tasks."""
    tasks = await task_manager.get_tasks(status="failed")
    return {
        "tasks": [t.to_dict() for t in tasks],
        "count": len(tasks),
    }


@router.get("/tasks/handlers")
async def get_handlers(
    task_manager: Any = Depends(_get_task_manager),
) -> dict[str, Any]:
    """List the real handler names available in this build."""
    handlers = task_manager.handlers
    return {
        "handlers": handlers.names(),
        "primary": handlers.primary_names(),
    }


@router.get("/tasks/types")
async def get_task_types(
    task_manager: Any = Depends(_get_task_manager),
) -> dict[str, Any]:
    """Get available task types."""
    return {
        "task_types": [t.value for t in TaskType],
    }


@router.get("/tasks/priorities")
async def get_priorities(
    task_manager: Any = Depends(_get_task_manager),
) -> dict[str, Any]:
    """Get available task priorities."""
    return {
        "priorities": [p.value for p in TaskPriority],
    }


@router.get("/tasks/stats")
async def get_task_stats(
    task_manager: Any = Depends(_get_task_manager),
) -> dict[str, Any]:
    """Get task statistics."""
    return await task_manager.get_task_manager_stats()


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    task_manager: Any = Depends(_get_task_manager),
) -> dict[str, Any]:
    """Get a specific autonomous task by ID."""
    task = await task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {"task": task.to_dict()}


@router.post("/tasks")
async def create_task(
    payload: TaskCreateRequest,
    task_manager: Any = Depends(_get_task_manager),
) -> dict[str, Any]:
    """Create a new autonomous task.

    The handler must resolve to a real implementation in this build, otherwise
    the handler list is returned as the 400 detail so the caller can retry.
    """
    handlers = task_manager.handlers
    if not handlers.is_registered(payload.handler_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid handler '{payload.handler_name}'. "
                f"Available: {handlers.names()}"
            ),
        )

    task_type = _coerce_task_type(payload.task_type)
    priority = _coerce_priority(payload.priority)

    scheduled_at = None
    if payload.scheduled_at:
        try:
            scheduled_at = datetime.fromisoformat(str(payload.scheduled_at).replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid scheduled_at (expected ISO 8601 timestamp)",
            ) from exc

    try:
        task_id = await task_manager.create_custom_task(
            name=payload.name,
            task_type=task_type,
            handler_name=payload.handler_name,
            parameters=payload.parameters or {},
            priority=priority,
            interval=payload.interval,
            max_retries=payload.max_retries,
            timeout=payload.timeout,
            auto_retry=payload.auto_retry,
            scheduled_at=scheduled_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {
        "task_id": task_id,
        "status": "scheduled",
        "scheduled_for": scheduled_at.isoformat() if scheduled_at else None,
    }


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    task_manager: Any = Depends(_get_task_manager),
) -> dict[str, Any]:
    """Cancel an autonomous task (running or queued)."""
    cancelled = await task_manager.cancel_task(task_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Task not found")

    return {"task_id": task_id, "status": "cancelled"}


@router.post("/tasks/{task_id}/requeue")
async def requeue_task(
    task_id: str,
    task_manager: Any = Depends(_get_task_manager),
) -> dict[str, Any]:
    """Approve a quarantined/dormant/failed task for execution (operator gate)."""
    result = await task_manager.requeue_task(task_id)
    if result == "requeued":
        return {"task_id": task_id, "status": "requeued"}
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Task not found")
    if result == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task is running; cancel it first")
    if result == "unregistered":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="handler not registered in this build",
        )
    raise HTTPException(status_code=500, detail="Unexpected requeue result")
