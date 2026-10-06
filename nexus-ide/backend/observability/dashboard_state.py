"""DashboardState — real-time system state aggregator.

Subscribes to EventBus and maintains a live view of:
- Active agents and their status
- Tasks in queue and in progress
- System health and recent events
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from .event_bus import EventBus
from .events import Event

logger = logging.getLogger(__name__)


@dataclass
class AgentStatus:
    """Status of a single agent."""

    name: str
    state: str = "idle"  # idle, busy, error, offline
    current_task: str = ""
    last_seen: float = field(default_factory=time.time)
    tasks_completed: int = 0
    tasks_failed: int = 0


@dataclass
class SystemHealth:
    """Overall system health summary."""

    status: str = "healthy"  # healthy, degraded, critical
    active_agents: int = 0
    busy_agents: int = 0
    queue_depth: int = 0
    error_count: int = 0
    last_event_time: float = field(default_factory=time.time)


class DashboardState:
    """Aggregates real-time system state from EventBus."""

    def __init__(self, event_bus: EventBus | None = None, max_events: int = 100) -> None:
        self._bus = event_bus or EventBus()
        self._agents: dict[str, AgentStatus] = {}
        self._tasks: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._events: deque[Event] = deque(maxlen=max_events)
        self._health = SystemHealth()
        self._lock = asyncio.Lock()
        self._running = False
        self._task: asyncio.Task[Any] | None = None

    async def start(self) -> None:
        """Start the background event consumer."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._consume_events())
        logger.info("DashboardState started")

    async def stop(self) -> None:
        """Stop the background event consumer."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("DashboardState stopped")

    async def _consume_events(self) -> None:
        """Background task consuming events from the bus."""
        try:
            async for event in self._bus.subscribe("*"):
                if not self._running:
                    break
                await self._process_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Event consumer error: %s", exc)

    async def _process_event(self, event: Event) -> None:
        """Process a single event and update state."""
        async with self._lock:
            self._events.append(event)
            self._health.last_event_time = time.time()

            if event.type.startswith("agent."):
                await self._update_agent_state(event)
            elif event.type.startswith("task."):
                await self._update_task_state(event)
            elif event.type.startswith("system."):
                await self._update_system_state(event)

    async def _update_agent_state(self, event: Event) -> None:
        """Update agent status from event."""
        agent_name = event.agent or "unknown"
        if agent_name not in self._agents:
            self._agents[agent_name] = AgentStatus(name=agent_name)

        agent = self._agents[agent_name]
        agent.last_seen = time.time()

        if event.type == "agent.started":
            agent.state = "busy"
            agent.current_task = event.payload.get("task", "")
        elif event.type == "agent.completed":
            agent.state = "idle"
            agent.tasks_completed += 1
            agent.current_task = ""
        elif event.type == "agent.failed":
            agent.state = "error"
            agent.tasks_failed += 1
            agent.current_task = ""
        elif event.type == "agent.heartbeat":
            agent.state = event.payload.get("state", agent.state)

        self._recompute_health()

    async def _update_task_state(self, event: Event) -> None:
        """Update task tracking from event."""
        self._tasks.append({
            "type": event.type,
            "agent": event.agent,
            "payload": event.payload,
            "timestamp": event.timestamp.isoformat(),
        })

        if event.type == "task.queued":
            self._health.queue_depth += 1
        elif event.type == "task.started":
            self._health.queue_depth = max(0, self._health.queue_depth - 1)
        elif event.type == "task.completed":
            pass
        elif event.type == "task.failed":
            self._health.error_count += 1

        self._recompute_health()

    async def _update_system_state(self, event: Event) -> None:
        """Update system health from event."""
        if event.type == "system.error":
            self._health.error_count += 1
            self._health.status = "degraded" if self._health.error_count < 5 else "critical"
        elif event.type == "system.recovered":
            self._health.error_count = max(0, self._health.error_count - 1)
            if self._health.error_count == 0:
                self._health.status = "healthy"

        self._recompute_health()

    def _recompute_health(self) -> None:
        """Recompute overall health from current state."""
        self._health.active_agents = len(self._agents)
        self._health.busy_agents = sum(1 for a in self._agents.values() if a.state == "busy")

        # Auto-recover agents that haven't sent heartbeat in 60s
        now = time.time()
        for agent in self._agents.values():
            if now - agent.last_seen > 60 and agent.state != "offline":
                agent.state = "offline"

    async def get_state(self) -> dict[str, Any]:
        """Get current dashboard state."""
        async with self._lock:
            return {
                "health": {
                    "status": self._health.status,
                    "active_agents": self._health.active_agents,
                    "busy_agents": self._health.busy_agents,
                    "queue_depth": self._health.queue_depth,
                    "error_count": self._health.error_count,
                    "last_event_time": self._health.last_event_time,
                },
                "agents": {
                    name: {
                        "name": a.name,
                        "state": a.state,
                        "current_task": a.current_task,
                        "last_seen": a.last_seen,
                        "tasks_completed": a.tasks_completed,
                        "tasks_failed": a.tasks_failed,
                    }
                    for name, a in self._agents.items()
                },
                "recent_tasks": list(self._tasks)[-20:],
                "recent_events": [
                    {
                        "type": e.type,
                        "agent": e.agent,
                        "timestamp": e.timestamp.isoformat(),
                    }
                    for e in list(self._events)[-20:]
                ],
            }

    async def sse_stream(self) -> AsyncIterator[str]:
        """Generate SSE events for dashboard streaming."""
        import json

        # Send initial state
        state = await self.get_state()
        yield f"data: {json.dumps({'type': 'state', 'data': state})}\n\n"

        # Subscribe to events and forward
        event_count = 0
        async for event in self._bus.subscribe("*"):
            payload = {
                "type": event.type,
                "agent": event.agent,
                "data": event.payload,
                "timestamp": event.timestamp.isoformat(),
            }
            yield f"data: {json.dumps(payload)}\n\n"
            event_count += 1

            # Send full state every 10 events
            if event_count % 10 == 0:
                state = await self.get_state()
                yield f"data: {json.dumps({'type': 'state', 'data': state})}\n\n"
