
"""Tasks routes for dashboard.

Provides endpoints for task pipeline and management backed by the real database.
"""

import json
import logging
import sqlite3
from typing import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.persistence.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


class TaskInfo(BaseModel):
    """Task information."""
    id: str
    title: str
    agent: str
    status: str
    progress: float | None = None
    created_at: str | None = None


def _task_from_row(row) -> dict:
    """Map a workflow_steps or workflows row to a task dict."""
    row = dict(row)
    return {
        "id": row["id"],
        "title": row.get("goal") or row.get("name") or "Untitled",
        "agent": row.get("agent") or row.get("stack") or "system",
        "status": row.get("status") or "pending",
        "progress": row.get("progress") or 0.0,
        "created_at": row.get("created_at") or row.get("started_at"),
    }


@router.get("/tasks/pipeline")
async def get_task_pipeline() -> dict:
    """Return current task pipeline status from real database."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as count FROM workflows GROUP BY status"
            ).fetchall()
    except sqlite3.OperationalError as exc:
        logger.warning("Task pipeline table is unavailable: %s", exc)
        rows = []
        status_counts = {r["status"]: r["count"] for r in rows}

    return {
        "phases": [
            {"name": "Planning", "status": "complete" if status_counts.get("pending", 0) == 0 else "active", "count": status_counts.get("pending", 0)},
            {"name": "Execution", "status": "active" if status_counts.get("running", 0) > 0 else "idle", "count": status_counts.get("running", 0)},
            {"name": "Validation", "status": "active" if status_counts.get("completed", 0) > 0 else "idle", "count": status_counts.get("completed", 0)},
            {"name": "Failed", "status": "active" if status_counts.get("failed", 0) > 0 else "idle", "count": status_counts.get("failed", 0)},
        ],
        "active_runs": status_counts.get("running", 0),
    }


@router.get("/tasks/list")
async def get_tasks_list() -> dict:
    """Return list of all tasks from the database."""
    try:
        with get_db() as conn:
            active = conn.execute(
                "SELECT id, goal as name, status, stack, created_at FROM workflows WHERE status = 'running' ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            queued = conn.execute(
                "SELECT id, goal as name, status, stack, created_at FROM workflows WHERE status = 'pending' ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            completed = conn.execute(
                "SELECT id, goal as name, status, stack, created_at FROM workflows WHERE status = 'completed' ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
    except sqlite3.OperationalError as exc:
        logger.warning("Task list table is unavailable: %s", exc)
        active, queued, completed = [], [], []

    return {
        "active": [_task_from_row(r) for r in active],
        "queued": [_task_from_row(r) for r in queued],
        "completed": [_task_from_row(r) for r in completed],
    }


@router.get("/tasks/active", tags=["tasks"])
async def get_active_tasks() -> dict:
    """Return list of currently active tasks from the real database."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, goal as name, status, stack, created_at FROM workflows WHERE status IN ('running', 'pending') ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
    except sqlite3.OperationalError as exc:
        logger.warning("Active task table is unavailable: %s", exc)
        rows = []

    return {
        "tasks": [_task_from_row(r) for r in rows],
    }


@router.get("/tasks/stream")
async def tasks_stream() -> StreamingResponse:
    """Stream real-time task updates via SSE."""
    async def event_generator() -> AsyncIterator[str]:
        import json
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
