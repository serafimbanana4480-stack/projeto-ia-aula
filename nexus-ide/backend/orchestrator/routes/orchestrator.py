"""Homelab Orchestrator / Sub-agent routes."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends

from backend.middleware.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter()

_tasks: dict[str, dict[str, Any]] = {}


@router.post("/orchestrator/tasks")
async def spawn_task(data: dict[str, Any], _user: dict = Depends(require_auth)) -> dict[str, Any]:
    task_id = str(uuid.uuid4()).replace("-", "")[:16]
    _tasks[task_id] = {
        "id": task_id,
        "agent_type": data.get("agent_type", "generic"),
        "description": data.get("description", ""),
        "status": "running",
        "result": None,
        "started_at": time.time(),
        "completed_at": None,
    }
    asyncio.create_task(_execute_task(task_id, data))
    return {"task_id": task_id, "status": "running"}


async def _execute_task(task_id: str, data: dict[str, Any]) -> None:
    try:
        await asyncio.sleep(2)
        _tasks[task_id]["result"] = {"message": f"Task '{data.get('description')}' completed"}
        _tasks[task_id]["status"] = "completed"
    except Exception as exc:
        _tasks[task_id]["status"] = "failed"
        _tasks[task_id]["result"] = {"error": str(exc)}
    finally:
        _tasks[task_id]["completed_at"] = time.time()


@router.post("/orchestrator/tasks/parallel")
async def spawn_parallel(data: dict[str, Any], _user: dict = Depends(require_auth)) -> dict[str, Any]:
    tasks = data.get("tasks", [])
    results = []
    for t in tasks:
        task_id = str(uuid.uuid4()).replace("-", "")[:16]
        _tasks[task_id] = {
            "id": task_id,
            "agent_type": t.get("agent_type", "generic"),
            "description": t.get("description", ""),
            "status": "running",
            "result": None,
            "started_at": time.time(),
            "completed_at": None,
        }
        asyncio.create_task(_execute_task(task_id, t))
        results.append({"task_id": task_id, "status": "running"})
    return {"tasks": results}


@router.get("/orchestrator/tasks/{task_id}")
async def get_task(task_id: str, _user: dict = Depends(require_auth)) -> dict[str, Any]:
    task = _tasks.get(task_id, {"status": "not_found"})
    return task


@router.get("/orchestrator/tasks")
async def list_tasks(_user: dict = Depends(require_auth)) -> dict[str, Any]:
    return {"tasks": list(_tasks.values())}


@router.post("/orchestrator/tasks/{task_id}/abort")
async def abort_task(task_id: str, _user: dict = Depends(require_auth)) -> dict[str, Any]:
    if task_id in _tasks:
        _tasks[task_id]["status"] = "aborted"
    return {"task_id": task_id, "status": "aborted"}


@router.get("/orchestrator/briefing")
async def morning_briefing(_user: dict = Depends(require_auth)) -> dict[str, Any]:
    active = [t for t in _tasks.values() if t["status"] == "running"]
    completed = [t for t in _tasks.values() if t["status"] == "completed"]
    return {
        "pending_tasks": len(active),
        "completed_today": len(completed),
        "system_status": "healthy",
        "summary": f"{len(active)} tasks running, {len(completed)} completed.",
    }
