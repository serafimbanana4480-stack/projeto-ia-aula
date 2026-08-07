
"""Advanced dashboard routes for NEXUS OMEGA features.

Provides endpoints for thinking, tools execution, self-improvement, etc.
Now uses real data from EventBus, WorkflowTracker, and AgentPool.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/thinking/stream")
async def thinking_stream(request: Request) -> StreamingResponse:
    """Stream AI thinking process via SSE from real EventBus events."""
    event_bus = request.app.state.event_bus
    
    async def event_generator() -> AsyncIterator[str]:
        """Stream real thinking events from EventBus."""
        async for event in event_bus.subscribe("thinking.*"):
            thought = {
                "eventType": "thought",
                "id": f"thought-{event.timestamp.timestamp()}",
                "type": event.type.split(".")[1] if "." in event.type else event.type,
                "content": event.payload.get("content", ""),
                "timestamp": event.timestamp.timestamp(),
                "status": event.payload.get("status", "active"),
                "confidence": event.payload.get("confidence", 0.0),
                "agent": event.agent,
            }
            yield f"data: {json.dumps(thought)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/tools/execution/stream")
async def tools_execution_stream(request: Request) -> StreamingResponse:
    """Stream tool execution updates via SSE from real EventBus events."""
    event_bus = request.app.state.event_bus
    
    async def event_generator() -> AsyncIterator[str]:
        """Stream real tool execution events from EventBus."""
        async for event in event_bus.subscribe("tool.*"):
            tool_event = {
                "eventType": event.type,
                "execution_id": event.payload.get("execution_id", ""),
                "tool_name": event.payload.get("tool_name", ""),
                "input": event.payload.get("input", {}),
                "output": event.payload.get("output", {}),
                "error": event.payload.get("error", ""),
                "timestamp": event.timestamp.timestamp(),
                "agent": event.agent,
            }
            yield f"data: {json.dumps(tool_event)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/timeline/stream")
async def timeline_stream(request: Request) -> StreamingResponse:
    """Stream execution timeline updates via SSE from real WorkflowTracker."""
    workflow_tracker = getattr(request.app.state, "workflow_tracker", None)
    event_bus = request.app.state.event_bus
    
    async def event_generator() -> AsyncIterator[str]:
        """Stream real workflow events from WorkflowTracker and EventBus."""
        yield "data: {\"type\": \"heartbeat\"}\n\n"
        # Stream existing workflows first
        workflows = workflow_tracker.list_workflows(limit=50) if workflow_tracker else []
        for workflow in workflows:
            event = {
                "type": "event",
                "event": {
                    "id": workflow.workflow_id,
                    "type": workflow.status,
                    "timestamp": workflow.created_at,
                    "agent": workflow.metadata.get("agent", ""),
                    "goal": workflow.goal,
                    "step_count": len(workflow.steps),
                }
            }
            yield f"data: {json.dumps(event)}\n\n"
        
        # Stream new events from EventBus
        async for event in event_bus.stream_events():
            if "workflow" not in event.event_type.value:
                continue
            timeline_event = {
                "type": "event",
                "event": {
                    "id": event.data.get("workflow_id", ""),
                    "type": event.event_type.value,
                    "timestamp": event.timestamp,
                    "agent": event.source,
                    "step": event.data.get("step", ""),
                    "status": event.data.get("status", ""),
                }
            }
            yield f"data: {json.dumps(timeline_event)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/observability/logs/stream")
async def logs_stream(request: Request) -> StreamingResponse:
    """Stream log updates via SSE from real EventBus events."""
    event_bus = request.app.state.event_bus
    
    async def event_generator() -> AsyncIterator[str]:
        """Stream real log events from EventBus."""
        async for event in event_bus.subscribe("log.*"):
            log = {
                "type": "log",
                "log": {
                    "id": f"log-{event.timestamp.timestamp()}",
                    "level": event.payload.get("level", "info"),
                    "source": event.payload.get("source", "backend"),
                    "message": event.payload.get("message", ""),
                    "timestamp": event.timestamp.timestamp(),
                    "context": event.payload.get("context", {}),
                }
            }
            yield f"data: {json.dumps(log)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/model-intelligence/stream")
async def model_intelligence_stream(request: Request) -> StreamingResponse:
    """Stream model intelligence updates via SSE from real EventBus events."""
    event_bus = request.app.state.event_bus
    
    async def event_generator() -> AsyncIterator[str]:
        """Stream real model selection events from EventBus."""
        async for event in event_bus.subscribe("model.*"):
            selection = {
                "type": "selection",
                "selection": {
                    "id": f"sel-{event.timestamp.timestamp()}",
                    "model": event.payload.get("model", ""),
                    "reason": event.payload.get("reason", ""),
                    "cost": event.payload.get("cost", 0.0),
                    "benchmark": event.payload.get("benchmark", 0.0),
                    "latency": event.payload.get("latency", 0),
                    "reasoning_score": event.payload.get("reasoning_score", 0.0),
                    "timestamp": event.timestamp.timestamp(),
                    "alternatives": event.payload.get("alternatives", []),
                }
            }
            yield f"data: {json.dumps(selection)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/autonomous-tasks/stream")
async def autonomous_tasks_stream(request: Request) -> StreamingResponse:
    """Stream autonomous task updates via SSE from real AgentPool and EventBus.

    Emits events in the standard SSE format recognised by the frontend
    (``StreamEvent`` in types.ts).  Both legacy ``agent_instance``/``task``
    formats and the canonical ``agent_started``/``task_scheduled`` etc.
    types are emitted so that older frontend code continues to work.
    """
    agent_pool = getattr(request.app.state, "agent_pool", None)
    event_bus = request.app.state.event_bus

    async def event_generator() -> AsyncIterator[str]:
        """Stream real agent task events from AgentPool and EventBus."""

        yield "data: {\"type\": \"heartbeat\"}\n\n"

        # ── 1. Stream current agent instances ────────
        for agent_type, instances in getattr(agent_pool, "agent_instances", {}).items():
            for instance in instances.values():
                # Canonical format (frontend StreamEvent)
                canonical = {
                    "type": "agent_started" if str(instance.state) == "active" else "agent_finished",
                    "agent": instance.agent_id,
                    "content": f"Agent {instance.agent_id} is {instance.state}",
                    "data": {
                        "agent_type": agent_type,
                        "instance_id": instance.instance_id,
                        "state": str(instance.state),
                        "health_status": str(instance.health_status),
                        "task_id": instance.task_id,
                    },
                    "timestamp": instance.last_activity,
                    "event_id": f"agent-{instance.instance_id}",
                    "task_id": instance.task_id or "",
                }
                yield f"data: {json.dumps(canonical)}\n\n"

                # Legacy format (backward compat)
                legacy = {
                    "type": "agent_instance",
                    "agent": instance.agent_id,
                    "agent_instance": {
                        "agent_id": instance.agent_id,
                        "instance_id": instance.instance_id,
                        "state": str(instance.state),
                        "health_status": str(instance.health_status),
                        "task_id": instance.task_id,
                        "last_activity": instance.last_activity,
                    }
                }
                yield f"data: {json.dumps(legacy)}\n\n"

        # ── 2. Stream task + goal events from EventBus ──────
        # Use stream_events which yields OrchestratorEvent objects as they arrive.
        # We subscribe to all relevant event types in one stream.
        ALL_EVENT_TYPES = [
            "task_scheduled",
            "task_started",
            "task_completed",
            "task_failed",
            "task_cancelled",
            "plan_created",
            "plan_updated",
            "step_completed",
        ]
        async for event in event_bus.stream_events(event_types=ALL_EVENT_TYPES):
            # Canonical: use OrchestratorEvent.to_sse() which produces
            # {type, agent, content, data, timestamp, event_id, task_id}
            canonical = event.to_sse()
            yield f"data: {json.dumps(canonical)}\n\n"

            et = event.event_type.value

            # Legacy task format (backward compat)
            if et.startswith("task_"):
                task_status = "completed"
                if "started" in et:
                    task_status = "running"
                elif "scheduled" in et:
                    task_status = "scheduled"
                elif "failed" in et:
                    task_status = "failed"
                elif "cancelled" in et:
                    task_status = "cancelled"

                legacy = {
                    "type": "task",
                    "agent": event.source,
                    "task": {
                        "id": event.task_id,
                        "agent": event.source,
                        "status": task_status,
                        "goal": event.data.get("goal", ""),
                        "timestamp": event.timestamp,
                    }
                }
                yield f"data: {json.dumps(legacy)}\n\n"

            # Legacy goal / subtask format (backward compat)
            if et in ("plan_created", "plan_updated", "step_completed"):
                goal_legacy = {
                    "type": "goal",
                    "agent": event.source,
                    "goal": {
                        "id": event.event_id,
                        "subtask_id": event.task_id,
                        "agent": event.source,
                        "status": et,
                        "content": event.content,
                        "data": event.data,
                        "timestamp": event.timestamp,
                    }
                }
                yield f"data: {json.dumps(goal_legacy)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/code-execution/stream")
async def code_execution_stream(request: Request) -> StreamingResponse:
    """Stream code execution updates via SSE from real EventBus events."""
    event_bus = request.app.state.event_bus
    
    async def event_generator() -> AsyncIterator[str]:
        """Stream real code execution events from EventBus."""
        async for event in event_bus.subscribe("execution.*"):
            execution_event = {
                "type": event.payload.get("type", "process"),
                "sandbox": event.payload.get("sandbox", {}) if "sandbox" in event.payload else None,
                "process": event.payload.get("process", {}) if "process" in event.payload else None,
                "timestamp": event.timestamp.timestamp(),
            }
            yield f"data: {json.dumps(execution_event)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/security/stream")
async def security_stream(request: Request) -> StreamingResponse:
    """Stream security updates via SSE from real EventBus events."""
    event_bus = request.app.state.event_bus
    
    async def event_generator() -> AsyncIterator[str]:
        """Stream real security events from EventBus."""
        async for event in event_bus.subscribe("security.*"):
            security_event = {
                "type": "issue" if event.type == "security.issue" else "heartbeat",
                "issue": {
                    "id": event.payload.get("issue_id", ""),
                    "type": event.payload.get("type", ""),
                    "severity": event.payload.get("severity", ""),
                    "title": event.payload.get("title", ""),
                    "description": event.payload.get("description", ""),
                    "affected_component": event.payload.get("affected_component", ""),
                    "timestamp": event.timestamp.timestamp(),
                    "resolved": event.payload.get("resolved", False),
                } if event.type == "security.issue" else None,
            }
            yield f"data: {json.dumps(security_event)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/performance/stream")
async def performance_stream() -> StreamingResponse:
    """Stream performance metrics via SSE."""
    async def event_generator() -> AsyncIterator[str]:
        from backend.observability.metrics_collector import get_metrics_collector
        
        collector = get_metrics_collector()
        
        while True:
            active_sessions = 0
            snapshot = await collector.get_snapshot(active_sessions=active_sessions, queue_depth=0)
            
            metric = {
                "type": "metric",
                "metric": {
                    "cpu_usage": snapshot.cpu_percent,
                    "ram_usage": snapshot.ram_percent,
                    "gpu_usage": 0.0,
                    "db_latency": snapshot.avg_latency_ms,
                    "queue_latency": snapshot.avg_latency_ms * 0.5,
                    "bottleneck": None,
                    "timestamp": datetime.now(timezone.utc).timestamp(),
                },
            }
            yield f"data: {json.dumps(metric)}\n\n"
            await asyncio.sleep(2)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/multi-user/stream")
async def multi_user_stream(request: Request) -> StreamingResponse:
    """Stream multi-user updates via SSE from real ContextStore and EventBus."""
    context_store = request.app.state.context
    event_bus = request.app.state.event_bus
    
    async def event_generator() -> AsyncIterator[str]:
        """Stream real session events from ContextStore and EventBus."""
        # Stream current active sessions
        # Note: ContextStore doesn't expose all sessions directly, so we rely on EventBus
        # for real-time session events
        
        # Stream session events from EventBus
        async for event in event_bus.subscribe("session.*"):
            session_event = {
                "type": "session",
                "session": {
                    "id": event.payload.get("session_id", ""),
                    "user_id": event.payload.get("user_id", ""),
                    "username": event.payload.get("username", ""),
                    "workspace": event.payload.get("workspace", ""),
                    "project": event.payload.get("project", ""),
                    "status": event.payload.get("status", "active"),
                    "last_activity": event.timestamp.timestamp(),
                    "permissions": event.payload.get("permissions", []),
                }
            }
            yield f"data: {json.dumps(session_event)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
