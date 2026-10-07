"""API routes for the autonomous execution engine."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.orchestrator.autonomous_execution_engine import (
    AutonomousExecutionEngine,
    TaskStatus,
)

router = APIRouter(prefix="/api/execution", tags=["execution"])

# Module-level singleton (injected at app startup in production)
_engine: AutonomousExecutionEngine | None = None


def set_engine(engine: AutonomousExecutionEngine) -> None:
    global _engine
    _engine = engine


class SubmitTaskRequest(BaseModel):
    name: str
    max_retries: int = 3
    timeout_seconds: float = 300.0


class TaskResponse(BaseModel):
    task_id: str
    name: str
    status: str
    retry_count: int
    result: Any = None
    error: str | None = None


@router.post("/tasks", response_model=TaskResponse)
async def submit_task(request: SubmitTaskRequest, http_request: Request) -> TaskResponse:
    if _engine is None:
        raise HTTPException(status_code=503, detail="Execution engine not available")
    # Note: handler is not serializable via HTTP; this endpoint is for orchestrator-internal use
    task = _engine.submit_task(request.name, lambda: None, max_retries=request.max_retries,
                                timeout_seconds=request.timeout_seconds)
    return TaskResponse(
        task_id=task.task_id,
        name=task.name,
        status=task.status.value,
        retry_count=task.retry_count,
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str) -> TaskResponse:
    if _engine is None:
        raise HTTPException(status_code=503, detail="Execution engine not available")
    task = _engine.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse(
        task_id=task.task_id,
        name=task.name,
        status=task.status.value,
        retry_count=task.retry_count,
        result=task.result,
        error=task.error,
    )


@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(status: str | None = None) -> list[TaskResponse]:
    if _engine is None:
        raise HTTPException(status_code=503, detail="Execution engine not available")
    try:
        tasks = _engine.list_tasks(TaskStatus(status) if status else None)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}") from None
    return [
        TaskResponse(
            task_id=t.task_id,
            name=t.name,
            status=t.status.value,
            retry_count=t.retry_count,
            result=t.result,
            error=t.error,
        )
        for t in tasks
    ]


@router.get("/stats")
async def get_stats() -> dict:
    if _engine is None:
        raise HTTPException(status_code=503, detail="Execution engine not available")
    return _engine.stats()
