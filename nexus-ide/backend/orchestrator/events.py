"""Event bus for inter-agent communication and streaming.

Provides a pub/sub system where agents can emit events and subscribers
(orchestrator, dashboard, frontend) can consume them in real-time.

Architecture:
- ``OrchestratorEvent``: typed events flowing through the system
- ``EventBus``: async pub/sub with topic-based filtering
- ``EventEmitter``: context manager for scoped event emission
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class EventType(StrEnum):
    """Canonical event types flowing through the orchestrator."""

    # Lifecycle
    ORCHESTRATOR_STARTED = "orchestrator_started"
    ORCHESTRATOR_FINISHED = "orchestrator_finished"
    AGENT_STARTED = "agent_started"
    AGENT_FINISHED = "agent_finished"
    AGENT_FAILED = "agent_failed"
    AGENT_RETRY = "agent_retry"

    # Execution
    TASK_SCHEDULED = "task_scheduled"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"

    # Streaming
    TOKEN = "token"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"

    # Planning
    PLAN_CREATED = "plan_created"
    PLAN_UPDATED = "plan_updated"
    PLAN_APPROVED = "plan_approved"
    PLAN_REJECTED = "plan_rejected"
    STEP_COMPLETED = "step_completed"

    # System
    ERROR = "error"
    WARNING = "warning"
    METRIC = "metric"
    HEARTBEAT = "heartbeat"
    DONE = "done"


@dataclass
class OrchestratorEvent:
    """A typed event with metadata flowing through the event bus."""

    event_type: EventType
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    source: str = ""  # agent name or component
    session_id: str = ""
    task_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    content: str = ""
    timestamp: float = field(default_factory=time.time)
    correlation_id: str = ""  # links related events

    def to_sse(self) -> dict[str, Any]:
        """Convert to SSE-compatible dict for frontend streaming."""
        return {
            "type": self.event_type.value,
            "agent": self.source,
            "content": self.content,
            "data": self.data,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
            "task_id": self.task_id,
        }


Subscriber = Callable[[OrchestratorEvent], Any]


class EventBus:
    """Async pub/sub event bus with topic-based filtering.

    Supports:
    - Multiple subscribers per event type
    - Wildcard subscription ("*" matches all events)
    - Async subscriber callbacks
    - Backpressure via bounded queues
    """

    def __init__(self, max_queue_size: int = 1000) -> None:
        self._subscribers: dict[str, list[Subscriber]] = {}
        self._lock = asyncio.Lock()
        self._event_log: list[OrchestratorEvent] = []
        self._max_log_size = 10_000
        self._max_queue_size = max_queue_size

    async def subscribe(self, event_type: str, callback: Subscriber) -> None:
        """Register a subscriber for a specific event type or '*' for all."""
        async with self._lock:
            self._subscribers.setdefault(event_type, []).append(callback)
            logger.debug("Subscriber added for event_type=%s", event_type)

    async def unsubscribe(self, event_type: str, callback: Subscriber) -> None:
        """Remove a subscriber."""
        async with self._lock:
            subs = self._subscribers.get(event_type, [])
            if callback in subs:
                subs.remove(callback)

    async def publish(self, event: OrchestratorEvent) -> None:
        """Publish an event to all matching subscribers."""
        # Log event
        self._event_log.append(event)
        if len(self._event_log) > self._max_log_size:
            self._event_log = self._event_log[-self._max_log_size :]

        # Get matching subscribers
        async with self._lock:
            subscribers: list[Subscriber] = []
            subscribers.extend(self._subscribers.get(event.event_type.value, []))
            subscribers.extend(self._subscribers.get("*", []))

        # Notify subscribers concurrently
        if subscribers:
            tasks = []
            for sub in subscribers:
                tasks.append(self._notify_subscriber(sub, event))
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _notify_subscriber(self, subscriber: Subscriber, event: OrchestratorEvent) -> None:
        """Notify a single subscriber, catching exceptions."""
        try:
            result = subscriber(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.exception("Subscriber failed for event %s", event.event_type)

    async def stream_events(
        self,
        event_types: list[str] | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[OrchestratorEvent]:
        """Stream events matching filters as they arrive.

        Creates a temporary queue and subscribes to matching event types.
        Yields events until the queue is closed.
        """
        queue: asyncio.Queue[OrchestratorEvent | None] = asyncio.Queue(maxsize=self._max_queue_size)

        async def on_event(event: OrchestratorEvent) -> None:
            if session_id and event.session_id != session_id:
                return
            await queue.put(event)

        types = event_types or ["*"]
        for et in types:
            await self.subscribe(et, on_event)

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            for et in types:
                await self.unsubscribe(et, on_event)

    def get_recent_events(self, limit: int = 100) -> list[OrchestratorEvent]:
        """Return recent events for replay/debugging."""
        return self._event_log[-limit:]

    async def clear(self) -> None:
        """Clear all subscribers and event log."""
        async with self._lock:
            self._subscribers.clear()
            self._event_log.clear()


class EventEmitter:
    """Context manager that emits start/finish events around an operation.

    Usage::

        async with EventEmitter(bus, "CODER", session_id) as emit:
            await emit("token", content="hello")
            # ... do work ...
        # Automatically emits agent_started / agent_finished
    """

    def __init__(
        self,
        bus: EventBus,
        source: str,
        session_id: str = "",
        task_id: str = "",
    ) -> None:
        self.bus = bus
        self.source = source
        self.session_id = session_id
        self.task_id = task_id
        self._correlation_id = uuid.uuid4().hex[:12]

    async def __aenter__(self) -> EventEmitter:
        await self.bus.publish(
            OrchestratorEvent(
                event_type=EventType.AGENT_STARTED,
                source=self.source,
                session_id=self.session_id,
                task_id=self.task_id,
                correlation_id=self._correlation_id,
            )
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.bus.publish(
            OrchestratorEvent(
                event_type=EventType.AGENT_FINISHED,
                source=self.source,
                session_id=self.session_id,
                task_id=self.task_id,
                correlation_id=self._correlation_id,
            )
        )

    async def emit(
        self,
        event_type: EventType | str,
        *,
        content: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        """Emit an event scoped to this emitter's context."""
        et = event_type if isinstance(event_type, EventType) else EventType(event_type)
        await self.bus.publish(
            OrchestratorEvent(
                event_type=et,
                source=self.source,
                session_id=self.session_id,
                task_id=self.task_id,
                content=content,
                data=data or {},
                correlation_id=self._correlation_id,
            )
        )
