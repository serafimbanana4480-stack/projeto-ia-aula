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
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
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

    # Autonomy / self-repair
    AUTONOMY_DECISION = "autonomy_decision"
    SELF_HEAL = "self_heal"
    REPLAY_COMPLETE = "replay_complete"


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
        self._event_log: deque[OrchestratorEvent] = deque(maxlen=10_000)
        self._max_queue_size = max_queue_size
        self._store: EventStore | None = None

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
        # Get matching subscribers and log event under the same lock
        async with self._lock:
            self._event_log.append(event)

            subscribers: list[Subscriber] = []
            subscribers.extend(self._subscribers.get(event.event_type.value, []))
            subscribers.extend(self._subscribers.get("*", []))

        # Persist (offloaded to thread pool so synchronous file I/O doesn't block the event loop)
        if self._store is not None:
            await asyncio.to_thread(self._store.persist, event)

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

    async def get_recent_events(self, limit: int = 100) -> list[OrchestratorEvent]:
        """Return recent events for replay/debugging."""
        async with self._lock:
            return list(self._event_log)[-limit:]

    async def clear(self) -> None:
        """Clear all subscribers and event log."""
        async with self._lock:
            self._subscribers.clear()
            self._event_log.clear()

    def attach_store(self, store: EventStore) -> None:
        """Attach an :class:`EventStore` so events are persisted on publish."""
        self._store = store

    async def replay(self, since: float, until: float | None = None) -> int:
        """Replay events from the attached store within ``[since, until]``.

        Re-publishes each persisted event through the bus (which will
        also be persisted again, but the storage format is append-only and
        idempotent readers handle duplicates via ``event_id``).
        Emits a final :attr:`EventType.REPLAY_COMPLETE` event with the
        replayed count.
        Returns the number of events replayed.
        """
        if self._store is None:
            logger.warning("replay() called but no EventStore is attached")
            count = 0
        else:
            events = self._store.load_window(since, until)
            for event in events:
                await self.publish(event)
            count = len(events)

        await self.publish(
            OrchestratorEvent(
                event_type=EventType.REPLAY_COMPLETE,
                source="EventBus",
                data={"count": count, "since": since, "until": until},
            )
        )
        return count


class EventStore:
    """Append-only persistent event store backed by daily NDJSON files.

    Events are written one-per-line to ``events-YYYYMMDD.ndjson`` files
    inside ``store_dir``. The store is best-effort: any I/O failure is
    logged but never raised, so a disk problem won't crash the bus.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        if store_dir is None:
            # <repo>/nexus-ide/data/events/
            store_dir = Path(__file__).resolve().parents[2] / "data" / "events"
        self.store_dir: Path = store_dir

    def _file_for(self, ts: float) -> Path:
        day = datetime.fromtimestamp(ts, tz=UTC).strftime("%Y%m%d")
        return self.store_dir / f"events-{day}.ndjson"

    @staticmethod
    def _event_to_dict(event: OrchestratorEvent) -> dict[str, Any]:
        return {
            "event_type": event.event_type.value,
            "event_id": event.event_id,
            "source": event.source,
            "session_id": event.session_id,
            "task_id": event.task_id,
            "data": event.data,
            "content": event.content,
            "timestamp": event.timestamp,
            "correlation_id": event.correlation_id,
        }

    @staticmethod
    def _dict_to_event(payload: dict[str, Any]) -> OrchestratorEvent:
        return OrchestratorEvent(
            event_type=EventType(payload.get("event_type", EventType.DONE.value)),
            event_id=payload.get("event_id", uuid.uuid4().hex[:12]),
            source=payload.get("source", ""),
            session_id=payload.get("session_id", ""),
            task_id=payload.get("task_id", ""),
            data=payload.get("data", {}) or {},
            content=payload.get("content", ""),
            timestamp=float(payload.get("timestamp", time.time())),
            correlation_id=payload.get("correlation_id", ""),
        )

    def persist(self, event: OrchestratorEvent) -> None:
        """Synchronously append ``event`` as a single JSON line.

        Best-effort: any I/O error is logged and swallowed.
        """
        path = self._file_for(event.timestamp)
        line = json.dumps(self._event_to_dict(event), ensure_ascii=False, default=str)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            logger.exception("EventStore.persist failed for %s", path)

    def load_window(self, since: float, until: float | None = None) -> list[OrchestratorEvent]:
        """Return persisted events with ``timestamp`` in ``[since, until]``.

        Reads every ``events-*.ndjson`` file in ``store_dir`` in name
        order. Malformed lines and unreadable files are skipped with a
        warning so one bad file can't poison the window.
        Returns ``[]`` if the directory does not exist.
        """
        if not self.store_dir.exists():
            return []

        upper = until if until is not None else float("inf")
        events: list[OrchestratorEvent] = []
        for path in sorted(self.store_dir.glob("events-*.ndjson")):
            try:
                with path.open("r", encoding="utf-8") as fh:
                    for raw in fh:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError:
                            logger.warning("Skipping malformed line in %s", path)
                            continue
                        ts = float(payload.get("timestamp", 0.0))
                        if ts < since or ts > upper:
                            continue
                        events.append(self._dict_to_event(payload))
            except OSError:
                logger.exception("EventStore.load_window failed for %s", path)
        return events

    def clear(self) -> int:
        """Delete every ``events-*.ndjson`` file in ``store_dir``.

        Returns the number of files removed.
        """
        if not self.store_dir.exists():
            return 0
        removed = 0
        for path in self.store_dir.glob("events-*.ndjson"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                logger.exception("EventStore.clear failed for %s", path)
        return removed


_event_store_singleton: EventStore | None = None


def get_event_store() -> EventStore:
    """Return a process-wide cached :class:`EventStore` instance."""
    global _event_store_singleton
    if _event_store_singleton is None:
        _event_store_singleton = EventStore()
    return _event_store_singleton


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
