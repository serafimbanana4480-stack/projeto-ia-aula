
"""Neural Command Center dashboard routes.

Provides SSE endpoints for the real-time dashboard visualization.
Uses real AgentPool and EventBus data when available.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()

AGENT_TYPES = ["ROUTER", "ARCHITECT", "RESEARCHER", "CODER", "ANALYZER", "DEBUGGER", "DOCUMENTER", "OPTIMIZER"]
MODELS = ["qwen2.5:7b", "llama3:8b", "mistral:7b", "qwen3:14b", "deepseek-r1:8b"]
REASONING_TEMPLATES = [
    "Analyzing the current task requirements...",
    "Evaluating potential implementation strategies...",
    "Considering edge cases and error handling...",
    "Reviewing code structure and dependencies...",
    "Planning the next development step...",
    "Debating the best approach with other agents...",
    "Reflecting on previous implementation decisions...",
    "Criticing the current code quality...",
    "Architecting the solution components...",
    "Implementing core functionality...",
    "Running tests to validate implementation...",
    "Optimizing performance bottlenecks...",
]


def get_agent_pool(request: Request) -> Optional[Any]:
    """Get AgentPool from app state."""
    return getattr(request.app.state, "agent_pool", None)


def get_event_bus(request: Request) -> Optional[Any]:
    """Get EventBus from app state."""
    return getattr(request.app.state, "event_bus", None)


def build_agent_from_pool(agent_id: str, instance_data: dict) -> dict:
    """Build agent topology data from pool instance.

    Only real values present in ``instance_data`` are emitted. Any field that
    is not available falls back to ``None`` so the dashboard never displays
    fabricated data.
    """
    return {
        "id": agent_id,
        "agentId": f"AGENT-{instance_data.get('instance_id', agent_id[:4].upper())}",
        "agentType": agent_id.upper(),
        "status": instance_data.get("status", "idle"),
        "model": instance_data.get("model"),
        "task": instance_data.get("task"),
        "cpu": instance_data.get("cpu"),
        "memory": instance_data.get("memory"),
        "tokensPerSecond": instance_data.get("tokens_per_second"),
        "reasoningDepth": instance_data.get("reasoning_depth"),
        "confidence": instance_data.get("confidence"),
        "retries": instance_data.get("retries", 0),
        "workflow": instance_data.get("workflow"),
        "x": instance_data.get("x"),
        "y": instance_data.get("y"),
    }


@router.get("/agents/topology/stream")
async def agents_topology_stream(request: Request) -> StreamingResponse:
    """Stream real agent topology data for AI Swarm Core visualization.

    Uses real AgentPool data when available, falls back to enhanced simulation.
    """
    agent_pool = get_agent_pool(request)

    async def event_generator() -> AsyncIterator[str]:
        tick_count = 0
        while True:
            try:
                if agent_pool and hasattr(agent_pool, "agent_instances"):
                    agents = []
                    instances_by_type: dict = agent_pool.agent_instances or {}

                    for agent_id, instances in instances_by_type.items():
                        if isinstance(instances, dict):
                            for instance_id, instance in instances.items():
                                status = "idle"
                                if hasattr(instance, "state"):
                                    state_map = {
                                        "spawning": "busy",
                                        "active": "active",
                                        "busy": "busy",
                                        "idle": "idle",
                                        "terminating": "busy",
                                        "terminated": "idle",
                                        "failed": "error",
                                    }
                                    status = state_map.get(instance.state.value, "idle")

                                agent_data = build_agent_from_pool(agent_id, {
                                    "instance_id": instance_id,
                                    "status": status,
                                    "task": getattr(instance, "task_id", None),
                                    "model": getattr(instance, "model", None)
                                    or getattr(instance, "model_key", None),
                                    "cpu": getattr(instance, "cpu", None),
                                    "memory": getattr(instance, "memory", None),
                                    "tokens_per_second": getattr(instance, "tokens_per_second", None),
                                    "reasoning_depth": getattr(instance, "reasoning_depth", None),
                                    "confidence": getattr(instance, "confidence", None),
                                    "workflow": getattr(instance, "workflow", None),
                                    "x": getattr(instance, "x", None),
                                    "y": getattr(instance, "y", None),
                                })
                                agents.append(agent_data)

                    if agents:
                        yield f"data: {json.dumps(agents)}\n\n"
                else:
                    # No real agent pool available: emit an empty topology
                    # payload instead of fabricated agents.
                    yield f"data: []\n\n"

                tick_count += 1
                await asyncio.sleep(2)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in topology stream: {e}")
                await asyncio.sleep(5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/agents/connections/stream")
async def agents_connections_stream(request: Request) -> StreamingResponse:
    """Stream agent connection data for AI Swarm Core visualization.

    Uses agent instance data to build real connections.
    """
    agent_pool = get_agent_pool(request)
    event_bus = get_event_bus(request)

    async def event_generator() -> AsyncIterator[str]:
        while True:
            try:
                connections = []

                if agent_pool and hasattr(agent_pool, "agent_instances"):
                    instances_by_type = agent_pool.agent_instances or {}

                    # Derive real edges from agents that collaborate on the
                    # same task.  Source/target/type come from real data; the
                    # line width ("frequency") uses the real number of
                    # collaborators.  "messageRate" is only included when a
                    # real measurement is available, otherwise it is omitted.
                    task_to_agents: dict = {}
                    for agent_id, instances in instances_by_type.items():
                        if isinstance(instances, dict) and instances:
                            for instance in instances.values():
                                task_id = getattr(instance, "task_id", None)
                                if task_id:
                                    task_to_agents.setdefault(task_id, []).append(agent_id)

                    seen_pairs = set()
                    for task_id, agents in task_to_agents.items():
                        for i in range(len(agents)):
                            for j in range(i + 1, len(agents)):
                                pair = tuple(sorted((agents[i].upper(), agents[j].upper())))
                                if pair in seen_pairs:
                                    continue
                                seen_pairs.add(pair)
                                connections.append({
                                    "source": pair[0],
                                    "target": pair[1],
                                    "type": "coordination",
                                    "frequency": max(len(agents) - 1, 1),
                                    "messageRate": None,
                                })
                else:
                    # No real agent pool: emit an empty connections payload
                    # instead of fabricated edges.
                    yield f"data: []\n\n"
                    continue

                yield f"data: {json.dumps(connections)}\n\n"
                await asyncio.sleep(2.5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in connections stream: {e}")
                await asyncio.sleep(5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/reasoning/stream")
async def reasoning_stream(request: Request) -> StreamingResponse:
    """Stream AI reasoning messages for Live Reasoning Stream.

    Uses real EventBus events when available, with enhanced simulation fallback.
    """
    event_bus = get_event_bus(request)

    async def event_generator() -> AsyncIterator[str]:
        message_counter = 0
        recent_messages: list = []

        while True:
            try:
                messages = []

                if event_bus and hasattr(event_bus, "get_recent_events"):
                    recent_events = await event_bus.get_recent_events(limit=50)
                    for event in recent_events[-5:]:
                        if hasattr(event, "type") and hasattr(event, "agent"):
                            msg_type = "reasoning"
                            if "tool" in event.type.lower():
                                msg_type = "tool_use"
                            elif "plan" in event.type.lower():
                                msg_type = "planning"
                            elif "think" in event.type.lower():
                                msg_type = "thought"

                                message = {
                                    "id": f"evt-{message_counter}",
                                    "type": msg_type,
                                    "agentId": event.agent or "SYSTEM",
                                    "agentType": (event.agent or "SYSTEM").upper(),
                                    "timestamp": event.timestamp if hasattr(event, "timestamp") else time.time(),
                                    "content": event.payload.get("content", str(event.payload)) if hasattr(event, "payload") else str(event),
                                }

                                # Only include metadata fields that are really
                                # present on the event; never fabricate values.
                                metadata = {
                                    key: getattr(event, key, None)
                                    for key in ("confidence", "priority", "severity", "decision")
                                    if getattr(event, key, None) is not None
                                }
                                if metadata:
                                    message["metadata"] = metadata

                                messages.append(message)
                                message_counter += 1

                if not messages:
                    # No real EventBus data available: emit an empty reasoning
                    # payload instead of fabricated messages.
                    messages = []

                yield f"data: {json.dumps(messages)}\n\n"
                await asyncio.sleep(1.5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in reasoning stream: {e}")
                await asyncio.sleep(3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/memory/visualization/stream")
async def memory_visualization_stream(request: Request) -> StreamingResponse:
    """Stream memory visualization data for Memory System Visualization.

    Returns realistic memory data based on knowledge system when available.
    """
    async def event_generator() -> AsyncIterator[str]:
        while True:
            try:
                # No real memory source wired into this stream: emit an empty
                # memory payload instead of fabricated records.
                memories: list = []

                yield f"data: {json.dumps(memories)}\n\n"
                await asyncio.sleep(3)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in memory stream: {e}")
                await asyncio.sleep(5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/system/metrics/stream")
async def system_metrics_stream(request: Request) -> StreamingResponse:
    """Stream system metrics for the dashboard.

    Provides real-time system health and performance metrics.
    """
    async def event_generator() -> AsyncIterator[str]:
        while True:
            try:
                metrics = {
                    "timestamp": datetime.now(timezone.utc).timestamp(),
                    "cpu_usage": None,
                    "memory_usage": None,
                    "gpu_usage": None,
                    "disk_usage": None,
                    "network_in": None,
                    "network_out": None,
                    "active_connections": None,
                    "queue_size": None,
                    "requests_per_second": None,
                    "avg_response_time_ms": None,
                    "tokens_per_second": None,
                    "cache_hit_rate": None,
                    "error_rate": None,
                    "available": False,
                }

                yield f"data: {json.dumps(metrics)}\n\n"
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in metrics stream: {e}")
                await asyncio.sleep(5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
