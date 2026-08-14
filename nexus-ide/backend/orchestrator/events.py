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
import contextlib
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
    TASK_WAITING_DEPENDENCY = "task_waiting_dependency"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_BLOCKED = "task_blocked"
    TASK_CANCELLED = "task_cancelled"
    ROUTING = "routing"
    EXECUTION_STATE = "execution_state"
    EXECUTION_ERROR = "execution_error"
    EXECUTION_COMPLETED = "execution_completed"

    # Streaming
    TOKEN = "token"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    TOOL_CONFIRMATION = "tool_confirmation"

    # Planning
    PLAN_CREATED = "plan_created"
    PLAN_UPDATED = "plan_updated"
    PLAN_APPROVED = "plan_approved"
    PLAN_REJECTED = "plan_rejected"
    PLAN_AWAITING_APPROVAL = "plan_awaiting_approval"
    PLAN_MODIFIED = "plan_modified"
    STEP_COMPLETED = "step_completed"

    # System
    ERROR = "error"
    WARNING = "warning"
    METRIC = "metric"
    HEARTBEAT = "heartbeat"
    DONE = "done"

    # Mission Control — the supervised planning layer above the raw engine.
    # These exist so the UI can show *why* work is happening, not only that it
    # is. See backend/orchestrator/mission_control.py.
    MISSION_BRIEF = "mission_brief"
    MISSION_PLAN = "mission_plan"
    MISSION_WAVES = "mission_waves"
    MISSION_WAVE_STARTED = "mission_wave_started"
    MISSION_WAVE_FINISHED = "mission_wave_finished"
    MISSION_AGENT = "mission_agent"
    MISSION_DECISION = "mission_decision"
    MISSION_VERIFICATION = "mission_verification"
    MISSION_TIMELINE = "mission_timeline"
    MISSION_COMPLETED = "mission_completed"

    # Autonomy / self-repair
    AUTONOMY_DECISION = "autonomy_decision"
    SELF_HEAL = "self_heal"
    REPLAY_COMPLETE = "replay_complete"

    # Session lifecycle / garbage collection
    SESSION_CLEANUP_COMPLETED = "session.cleanup_completed"


@dataclass
class OrchestratorEvent:
    """A typed event with metadata flowing through the event bus.

    ``run_id`` and ``seq`` exist because ``timestamp`` is not a total order:
    ``time.time()`` has ~15.6 ms granularity on Windows, so a burst of
    events emitted inside one scheduling slice shares a single value and any
    consumer sorting by time renders an arbitrary permutation. Consumers
    must order by ``(run_id, seq)`` and deduplicate by ``event_id``.

    ``seq`` is assigned by :meth:`EventBus.publish` when it is still 0, so
    callers never have to thread a counter through the call graph.
    """

    event_type: EventType
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    source: str = ""  # agent name or component
    session_id: str = ""
    run_id: str = ""  # scopes the event to one execution
    seq: int = 0  # strictly increasing within a run; 0 means "unassigned"
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
            "run_id": self.run_id,
            "seq": self.seq,
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
        }


Subscriber = Callable[[OrchestratorEvent], Any]


class EventBus:
    """Async pub/sub event bus with topic-based filtering.

    Supports:
    - Multiple subscribers per event type
    - Wildcard subscription ("*" matches all events)
    - Async subscriber callbacks
    - Bounded stream queues with an explicit ``drop_oldest`` overflow policy

    ``publish`` is on the critical execution path.  A disconnected or slow
    SSE consumer must never be able to stop an agent by filling its personal
    event queue, so stream subscribers retain the newest events and discard
    their oldest unread event when full.
    """

    STREAM_OVERFLOW_POLICY = "drop_oldest"

    def __init__(self, max_queue_size: int = 1000) -> None:
        self._subscribers: dict[str, list[Subscriber]] = {}
        self._lock = asyncio.Lock()
        self._event_log: deque[OrchestratorEvent] = deque(maxlen=10_000)
        self._max_queue_size = max_queue_size
        self._store: EventStore | None = None
        # Per-run sequence counters. Events without a run_id share the ""
        # bucket, which still yields a total order for that stream.
        self._seq: dict[str, int] = {}
        # Durable writes are drained off the critical path: persisting used
        # to happen *before* subscriber notification via ``asyncio.to_thread``,
        # which let two concurrent publishers be resumed in the wrong order.
        self._persist_queue: asyncio.Queue[OrchestratorEvent | None] | None = None
        self._persist_task: asyncio.Task[None] | None = None

    def _assign_seq(self, event: OrchestratorEvent) -> None:
        """Stamp a strictly increasing per-run sequence number."""
        if event.seq:
            self._seq[event.run_id] = max(self._seq.get(event.run_id, 0), event.seq)
            return
        nxt = self._seq.get(event.run_id, 0) + 1
        self._seq[event.run_id] = nxt
        event.seq = nxt

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
        """Publish an event to all matching subscribers, in publish order.

        Ordering rules enforced here:

        * ``seq`` is assigned, the event is logged, and every *synchronous*
          subscriber is notified without a single ``await`` in between, so
          concurrent publishers cannot be interleaved;
        * persistence is queued for a background writer instead of being
          awaited inline, which is what used to invert delivery order;
        * asynchronous subscribers still run afterwards, and can restore the
          exact order from ``(run_id, seq)``.
        """
        # ``asyncio.Lock.acquire`` on an uncontended lock does not suspend,
        # so the block below is atomic with respect to other publishers in
        # the common case, and serialised by the lock otherwise.
        async with self._lock:
            self._assign_seq(event)
            self._event_log.append(event)

            subscribers: list[Subscriber] = []
            subscribers.extend(self._subscribers.get(event.event_type.value, []))
            subscribers.extend(self._subscribers.get("*", []))

            self._enqueue_persist(event)

            pending: list[Any] = []
            for sub in subscribers:
                if asyncio.iscoroutinefunction(sub):
                    pending.append(sub(event))
                    continue
                try:
                    result = sub(event)
                except Exception:
                    logger.exception("Subscriber failed for event %s", event.event_type)
                    continue
                if asyncio.iscoroutine(result):
                    pending.append(result)

        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def _enqueue_persist(self, event: OrchestratorEvent) -> None:
        """Hand the event to the background writer; never block the caller."""
        if self._store is None:
            return
        if self._persist_task is None or self._persist_task.done():
            try:
                self._persist_queue = asyncio.Queue()
                self._persist_task = asyncio.get_running_loop().create_task(
                    self._drain_persist_queue()
                )
            except RuntimeError:
                # No running loop (synchronous test context): persist inline.
                self._store.persist(event)
                return
        assert self._persist_queue is not None
        with contextlib.suppress(Exception):
            self._persist_queue.put_nowait(event)

    async def _drain_persist_queue(self) -> None:
        queue = self._persist_queue
        assert queue is not None
        while True:
            event = await queue.get()
            try:
                if event is None or self._store is None:
                    return
                await asyncio.to_thread(self._store.persist, event)
            except Exception:
                logger.exception("EventStore.persist failed")
            finally:
                queue.task_done()

    async def flush(self) -> None:
        """Wait until every queued event has been persisted."""
        queue = self._persist_queue
        if queue is not None:
            await queue.join()

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
        dropped_events = 0

        def on_event(event: OrchestratorEvent) -> None:
            """Enqueue without ever applying subscriber backpressure upstream.

            Deliberately synchronous: :meth:`publish` calls sync subscribers
            inline, so the queue receives events in exactly publish order
            even when several coroutines publish concurrently.

            The event bus awaits subscriber callbacks in :meth:`publish`.
            Using ``await queue.put`` here therefore made a full client queue
            block every publisher (and, transitively, the orchestration run).
            We intentionally use a lossy, latest-state-wins policy instead:
            remove one oldest unread event and enqueue the newest one.
            """
            nonlocal dropped_events
            if session_id and event.session_id != session_id:
                return
            try:
                queue.put_nowait(event)
                return
            except asyncio.QueueFull:
                # ``put_nowait`` and ``get_nowait`` do not yield, so there is
                # no race with another callback running on this event loop.
                # Keep the newest progress/error events visible to the client.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()

                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(event)
                dropped_events += 1
                if dropped_events == 1 or dropped_events % 100 == 0:
                    logger.warning(
                        "Dropped %d event(s) for a slow stream subscriber "
                        "(overflow policy=%s)",
                        dropped_events,
                        self.STREAM_OVERFLOW_POLICY,
                    )

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
