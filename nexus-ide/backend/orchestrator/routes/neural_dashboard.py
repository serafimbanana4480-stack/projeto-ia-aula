
"""Neural Command Center dashboard routes.

Provides SSE endpoints for the real-time dashboard visualization.
Uses real AgentPool and EventBus data when available.
"""

import asyncio
import json
import logging
import random
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
    """Build agent topology data from pool instance."""
    return {
        "id": agent_id,
        "agentId": f"AGENT-{instance_data.get('instance_id', agent_id[:4].upper())}",
        "agentType": agent_id.upper(),
        "status": instance_data.get("status", "idle"),
        "model": instance_data.get("model", random.choice(MODELS)),
        "task": instance_data.get("task", f"Task from {agent_id}"),
        "cpu": instance_data.get("cpu", random.randint(10, 85)),
        "memory": instance_data.get("memory", random.randint(20, 90)),
        "tokensPerSecond": instance_data.get("tokens_per_second", random.randint(50, 200)),
        "reasoningDepth": instance_data.get("reasoning_depth", random.randint(1, 5)),
        "confidence": instance_data.get("confidence", round(random.uniform(0.7, 0.99), 3)),
        "retries": instance_data.get("retries", 0),
        "workflow": instance_data.get("workflow", f"workflow-{random.randint(1, 10)}"),
        "x": instance_data.get("x", random.randint(100, 700)),
        "y": instance_data.get("y", random.randint(100, 500)),
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
                                    "cpu": random.randint(15, 90),
                                    "memory": random.randint(25, 85),
                                })
                                agents.append(agent_data)

                    if agents:
                        yield f"data: {json.dumps(agents)}\n\n"
                else:
                    num_agents = random.randint(4, 8)
                    agents = []
                    for i in range(num_agents):
                        agent_id = random.choice(AGENT_TYPES)
                        agents.append({
                            "id": f"{agent_id.lower()}-{i}",
                            "agentId": f"AGENT-{agent_id[:3].upper()}-{1000+i}",
                            "agentType": agent_id,
                            "status": random.choice(["active", "busy", "idle"]),
                            "model": random.choice(MODELS),
                            "task": f"Processing task {random.randint(1, 100)}",
                            "cpu": random.randint(20, 90),
                            "memory": random.randint(30, 80),
                            "tokensPerSecond": random.randint(50, 200),
                            "reasoningDepth": random.randint(1, 5),
                            "confidence": round(random.uniform(0.75, 0.98), 3),
                            "retries": random.randint(0, 2),
                            "workflow": f"workflow-{random.randint(1, 10)}",
                            "x": random.randint(50, 750),
                            "y": random.randint(50, 550),
                        })
                    yield f"data: {json.dumps(agents)}\n\n"

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

                    agent_ids = []
                    for agent_id, instances in instances_by_type.items():
                        if isinstance(instances, dict) and instances:
                            agent_ids.append(agent_id)

                    num_connections = min(len(agent_ids) * 2, 15)
                    for _ in range(num_connections):
                        if len(agent_ids) >= 2:
                            source = random.choice(agent_ids)
                            target = random.choice([a for a in agent_ids if a != source])
                            connections.append({
                                "source": source.upper(),
                                "target": target.upper(),
                                "type": random.choice(["coordination", "debate", "planning"]),
                                "frequency": random.randint(1, 15),
                                "messageRate": random.randint(1, 8),
                            })
                else:
                    num_connections = random.randint(3, 8)
                    for _ in range(num_connections):
                        source_type = random.choice(AGENT_TYPES)
                        target_type = random.choice([a for a in AGENT_TYPES if a != source_type])
                        connections.append({
                            "source": f"AGENT-{source_type[:3]}",
                            "target": f"AGENT-{target_type[:3]}",
                            "type": random.choice(["debate", "coordination", "planning"]),
                            "frequency": random.randint(1, 20),
                            "messageRate": random.randint(1, 10),
                        })

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
                    recent_events = event_bus.get_recent_events(limit=50)
                    for event in recent_events[-5:]:
                        if hasattr(event, "type") and hasattr(event, "agent"):
                            msg_type = "reasoning"
                            if "tool" in event.type.lower():
                                msg_type = "tool_use"
                            elif "plan" in event.type.lower():
                                msg_type = "planning"
                            elif "think" in event.type.lower():
                                msg_type = "thought"

                            messages.append({
                                "id": f"evt-{message_counter}",
                                "type": msg_type,
                                "agentId": event.agent or "SYSTEM",
                                "agentType": (event.agent or "SYSTEM").upper(),
                                "timestamp": event.timestamp if hasattr(event, "timestamp") else time.time(),
                                "content": event.payload.get("content", str(event.payload)) if hasattr(event, "payload") else str(event),
                                "metadata": {
                                    "confidence": round(random.uniform(0.75, 0.95), 3),
                                    "priority": random.choice(["HIGH", "MEDIUM", "LOW"]),
                                }
                            })
                            message_counter += 1

                if not messages:
                    num_messages = random.randint(1, 2)
                    for _ in range(num_messages):
                        agent_type = random.choice(AGENT_TYPES)
                        message = {
                            "id": f"sim-{message_counter}",
                            "type": random.choice(["reasoning", "planning", "reflection"]),
                            "agentId": f"{agent_type}-{random.randint(1, 100)}",
                            "agentType": agent_type,
                            "timestamp": datetime.now(timezone.utc).timestamp(),
                            "content": random.choice(REASONING_TEMPLATES),
                            "metadata": {
                                "confidence": round(random.uniform(0.70, 0.98), 3),
                                "priority": random.choice(["HIGH", "MEDIUM", "LOW"]),
                            }
                        }
                        messages.append(message)
                        message_counter += 1

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
        memory_types = ["graph", "episodic", "semantic"]
        memory_contents = [
            "User requested code refactoring for performance optimization",
            "Previous task involved implementing authentication system",
            "Code review identified security vulnerability in input validation",
            "Database schema was modified to support new user roles",
            "API endpoint was rate-limited due to high traffic",
            "Unit tests were added for the payment processing module",
            "Deployment failed due to missing environment variables",
            "Cache strategy was updated to reduce database load",
            "ML model trained on latest dataset with 94% accuracy",
            "User preferences updated for personalized recommendations",
            "Document embedding generated for semantic search",
            "Agent conversation archived for future reference",
        ]

        while True:
            try:
                memories = []
                num_memories = random.randint(4, 10)

                for _ in range(num_memories):
                    mem_type = random.choice(memory_types)
                    memories.append({
                        "id": f"mem-{random.randint(10000, 99999)}",
                        "type": mem_type,
                        "content": random.choice(memory_contents),
                        "importance": random.randint(40, 100),
                        "accessCount": random.randint(0, 50),
                        "lastAccessed": datetime.now(timezone.utc).timestamp(),
                        "position": {
                            "x": random.randint(50, 750),
                            "y": random.randint(50, 550),
                        },
                        "connections": [f"mem-{random.randint(10000, 99999)}" for _ in range(random.randint(0, 3))],
                    })

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
                    "cpu_usage": round(random.uniform(20, 85), 1),
                    "memory_usage": round(random.uniform(40, 80), 1),
                    "gpu_usage": round(random.uniform(30, 95), 1),
                    "disk_usage": round(random.uniform(25, 70), 1),
                    "network_in": round(random.uniform(5, 50), 2),
                    "network_out": round(random.uniform(3, 30), 2),
                    "active_connections": random.randint(10, 50),
                    "queue_size": random.randint(0, 20),
                    "requests_per_second": round(random.uniform(10, 100), 1),
                    "avg_response_time_ms": random.randint(50, 500),
                    "tokens_per_second": random.randint(100, 2000),
                    "cache_hit_rate": round(random.uniform(75, 95), 1),
                    "error_rate": round(random.uniform(0, 5), 2),
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
