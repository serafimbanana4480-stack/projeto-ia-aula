"""Workflow tracking endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from backend.observability.workflow_tracker import WorkflowTracker

router = APIRouter()


class WorkflowInfo(BaseModel):
    """Workflow information."""
    workflow_id: str
    story_id: str
    goal: str
    status: str
    start_time: str
    steps: list[dict[str, Any]]

# Global tracker (initialized in lifespan)
_workflow_tracker: WorkflowTracker | None = None


def get_workflow_tracker() -> WorkflowTracker:
    if _workflow_tracker is None:
        raise RuntimeError("WorkflowTracker not initialized")
    return _workflow_tracker


def init_workflow_tracker() -> WorkflowTracker:
    global _workflow_tracker
    _workflow_tracker = WorkflowTracker()
    return _workflow_tracker


@router.get("/workflows")
async def list_workflows(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List workflows with optional status filter."""
    tracker = get_workflow_tracker()
    workflows = tracker.list_workflows(status=status, limit=limit)
    return [w.to_dict() for w in workflows]


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str) -> dict[str, Any]:
    """Get workflow details."""
    tracker = get_workflow_tracker()
    wf = tracker.get_workflow(workflow_id)
    if not wf:
        return {"error": "Workflow not found"}
    return wf.to_dict()


@router.get("/workflows/{workflow_id}/timeline")
async def get_workflow_timeline(workflow_id: str) -> list[dict[str, Any]]:
    """Get step-by-step timeline for replay."""
    tracker = get_workflow_tracker()
    return tracker.get_timeline(workflow_id)


@router.get("/workflows/{workflow_id}/conflicts")
async def get_workflow_conflicts(workflow_id: str) -> list[dict[str, Any]]:
    """Get detected conflicts in a workflow."""
    tracker = get_workflow_tracker()
    return tracker.detect_conflicts(workflow_id)


@router.post("/workflows")
async def create_workflow(story_id: str, goal: str) -> dict[str, Any]:
    """Create a new workflow."""
    tracker = get_workflow_tracker()
    wf = tracker.create_workflow(story_id=story_id, goal=goal)
    return wf.to_dict()


@router.get("/workflows/active", response_model=list[WorkflowInfo], tags=["workflows"])
async def list_active_workflows(limit: int = 50) -> list[dict[str, Any]]:
    """List active workflows with status 'active' or 'running'.

    Returns all currently active workflows from the WorkflowTracker.
    This is useful for dashboard displays showing ongoing operations.

    **Query Parameters:**
    - `limit`: Maximum number of workflows to return (default: 50)

    **Example Response:**
    ```json
    [
        {
            "workflow_id": "wf-123",
            "story_id": "story-456",
            "goal": "Analyze codebase",
            "status": "active",
            "start_time": "2026-05-09T10:30:00Z",
            "steps": [...]
        }
    ]
    ```

    **Returns:**
        List of active workflow objects
    """
    tracker = get_workflow_tracker()
    # Get workflows with active or running status
    active_workflows = []
    for status in ["active", "running"]:
        workflows = tracker.list_workflows(status=status, limit=limit)
        active_workflows.extend(workflows)
    return [w.to_dict() for w in active_workflows[:limit]]
