from __future__ import annotations

"""Autonomous Tasks Routes - API endpoints for autonomous task management."""


import logging
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse


from backend.observability.event_system import get_event_bus
from backend.tasks.autonomous_tasks import get_autonomous_task_manager, TaskType, TaskPriority

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/tasks")
async def get_tasks() -> Dict[str, List[Dict]]:
    """Get all autonomous tasks."""
    try:
        event_bus = await get_event_bus()
        task_manager = await get_autonomous_task_manager(event_bus)
        
        # Get all tasks
        tasks = await task_manager.get_tasks()
        
        return {
            "tasks": [task.to_dict() for task in tasks],
            "stats": await task_manager.get_task_manager_stats()
        }
        
    except Exception as e:
        logger.error(f"Failed to get tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/running")
async def get_running_tasks() -> Dict[str, List[Dict]]:
    """Get currently running tasks."""
    try:
        event_bus = await get_event_bus()
        task_manager = await get_autonomous_task_manager(event_bus)
        
        # Get running tasks
        tasks = await task_manager.get_tasks(status="running")
        
        return {
            "tasks": [task.to_dict() for task in tasks],
            "count": len(tasks)
        }
        
    except Exception as e:
        logger.error(f"Failed to get running tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/completed")
async def get_completed_tasks() -> Dict[str, List[Dict]]:
    """Get completed tasks."""
    try:
        event_bus = await get_event_bus()
        task_manager = await get_autonomous_task_manager(event_bus)
        
        # Get completed tasks
        tasks = await task_manager.get_tasks(status="completed")
        
        return {
            "tasks": [task.to_dict() for task in tasks],
            "count": len(tasks)
        }
        
    except Exception as e:
        logger.error(f"Failed to get completed tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/failed")
async def get_failed_tasks() -> Dict[str, List[Dict]]:
    """Get failed tasks."""
    try:
        event_bus = await get_event_bus()
        task_manager = await get_autonomous_task_manager(event_bus)
        
        # Get failed tasks
        tasks = await task_manager.get_tasks(status="failed")
        
        return {
            "tasks": [task.to_dict() for task in tasks],
            "count": len(tasks)
        }
        
    except Exception as e:
        logger.error(f"Failed to get failed tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> Dict[str, Any]:
    """Get specific task by ID."""
    try:
        event_bus = await get_event_bus()
        task_manager = await get_autonomous_task_manager(event_bus)
        
        task = await task_manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        return task.to_dict()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks")
async def create_task(
    name: str,
    task_type: str,
    priority: str = "normal",
    handler_name: str = "",
    parameters: Optional[Dict] = None,
    interval: Optional[int] = None,
    max_retries: int = 3,
    timeout: int = 300,
    request: Request = None,
) -> Dict[str, str]:
    """Create a new autonomous task."""
    try:
        event_bus = await get_event_bus()
        task_manager = await get_autonomous_task_manager(event_bus)
        
        # Convert string enums to enum values
        task_type_enum = TaskType(task_type)
        priority_enum = TaskPriority(priority)
        
        # Get handler function
        task_handlers = task_manager.task_handlers
        if handler_name not in task_handlers:
            available_handlers = list(task_handlers.keys())
            raise HTTPException(
                status_code=400,
                detail=f"Invalid handler. Available: {available_handlers}"
            )
        
        handler = task_handlers[handler_name]
        
        # Create task
        task_id = await task_manager.create_custom_task(
            name=name,
            task_type=task_type_enum,
            handler=handler,
            parameters=parameters or {},
            priority=priority_enum,
            interval=interval,
            max_retries=max_retries,
            timeout=timeout
        )
        
        return {"task_id": task_id, "status": "scheduled"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request) -> Dict[str, str]:
    """Cancel a task."""
    try:
        event_bus = await get_event_bus()
        task_manager = await get_autonomous_task_manager(event_bus)
        
        success = await task_manager.cancel_task(task_id)
        if not success:
            raise HTTPException(status_code=404, detail="Task not found or cannot be cancelled")
        
        return {"task_id": task_id, "status": "cancelled"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/types")
async def get_task_types() -> Dict[str, List[str]]:
    """Get available task types."""
    return {
        "task_types": [t.value for t in TaskType],
        "descriptions": {
            "monitoring": "System monitoring and health checks",
            "optimization": "Performance optimization",
            "maintenance": "System maintenance and cleanup",
            "analysis": "Data analysis and reporting",
            "learning": "Model training and updates",
            "cleanup": "Resource cleanup and maintenance",
            "health_check": "System health verification",
            "performance_tuning": "Performance optimization",
            "error_recovery": "Error detection and recovery"
        }
    }


@router.get("/tasks/priorities")
async def get_task_priorities() -> Dict[str, List[str]]:
    """Get available task priorities."""
    return {
        "priorities": [p.value for p in TaskPriority],
        "descriptions": {
            "low": "Low priority - background tasks",
            "normal": "Normal priority - regular tasks",
            "high": "High priority - important tasks",
            "critical": "Critical priority - urgent tasks",
            "urgent": "Urgent priority - immediate tasks"
        }
    }


@router.get("/tasks/stats")
async def get_task_stats() -> Dict[str, Any]:
    """Get task manager statistics."""
    try:
        event_bus = await get_event_bus()
        task_manager = await get_autonomous_task_manager(event_bus)
        
        return await task_manager.get_task_manager_stats()
        
    except Exception as e:
        logger.error(f"Failed to get task stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
