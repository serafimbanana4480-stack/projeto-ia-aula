"""Ordered, per-run event stream for the NEXUS primary agent runtime.

Design constraints (derived from reproduced defects, see
``backend/tests/runtime/test_evidence_event_ordering.py``):

* **Total order.** Every event carries ``run_id`` and a strictly increasing
  per-run ``seq``. A consumer never has to sort by wall-clock time, which is
  not a total order on Windows (~15.6 ms timer granularity).
* **Order-preserving delivery.** ``emit`` assigns ``seq`` *and* enqueues to
  every subscriber with no ``await`` in between, so two concurrent emitters
  can never be resumed in the wrong order. The old bus persisted through
  ``asyncio.to_thread`` before notifying subscribers, which inverted order.
* **Persistence off the hot path.** Durable writes are drained by a single
  background writer from an ordered queue, so a slow disk delays durability,
  never the agent.
* **Replayable.** A client that refreshes or reconnects resumes with
  ``replay(after_seq=...)`` and receives exactly the events it missed, in
  order, with no duplicates.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RuntimeEventType(StrEnum):
    """The stable event vocabulary the UI renders.

    Operational transparency, not chain-of-thought: every member describes
    something the agent *did*, is waiting on, or observed.
    """

    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"

    MESSAGE_STARTED = "message_started"
    MESSAGE_DELTA = "message_delta"
    MESSAGE_COMPLETED = "message_completed"

    STATUS_UPDATE = "status_update"
    PLAN_UPDATED = "plan_updated"

    TOOL_STARTED = "tool_started"
    TOOL_PROGRESS = "tool_progress"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"

    FILE_READ = "file_read"
    FILE_CHANGED = "file_changed"

    COMMAND_STARTED = "command_started"
    COMMAND_OUTPUT = "command_output"
    COMMAND_COMPLETED = "command_completed"

    TEST_STARTED = "test_started"
    TEST_RESULT = "test_result"

    SUBAGENT_STARTED = "subagent_started"
    SUBAGENT_PROGRESS = "subagent_progress"
    SUBAGENT_COMPLETED = "subagent_completed"

    WAITING_DEPENDENCY = "waiting_dependency"
    HEARTBEAT = "heartbeat"
    RECOVERY = "recovery"
    USER_STEERING = "user_steering"


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """A single, totally-ordered fact about a run."""

    run_id: str
    seq: int
    type: RuntimeEventType
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    ts: float = field(default_factory=time.time)
    agent_id: str = "NEXUS"
    task_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def order_key(self) -> tuple[str, int]:
        """The only key a consumer should ever sort by."""
        return (self.run_id, self.seq)

    def to_sse(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "seq": self.seq,
            "event_id": self.event_id,
            "type": self.type.value,
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "ts": self.ts,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RuntimeEvent:
        return cls(
            run_id=str(raw["run_id"]),
            seq=int(raw["seq"]),
            type=RuntimeEventType(raw["type"]),
            event_id=str(raw.get("event_id") or uuid.uuid4().hex[:16]),
            ts=float(raw.get("ts", time.time())),
            agent_id=str(raw.get("agent_id", "NEXUS")),
            task_id=str(raw.get("task_id", "")),
            payload=dict(raw.get("payload") or {}),
        )


class RunEventStream:
    """Ordered event stream scoped to a single run.

    ``emit`` is synchronous on purpose. Assigning ``seq`` and fanning the
    event out to subscriber queues happens in one uninterrupted block, so
    the sequence a subscriber observes is exactly the sequence in which
    events were emitted — regardless of how many coroutines emit
    concurrently.
    """

    def __init__(
        self,
        run_id: str,
        *,
        buffer_size: int = 5_000,
        subscriber_queue_size: int = 2_000,
        journal_path: Path | None = None,
    ) -> None:
        self.run_id = run_id
        self._seq = 0
        self._buffer: deque[RuntimeEvent] = deque(maxlen=buffer_size)
        self._subscribers: list[asyncio.Queue[RuntimeEvent | None]] = []
        self._subscriber_queue_size = subscriber_queue_size
        self._closed = False
        self._journal_path = journal_path
        self._journal_queue: asyncio.Queue[RuntimeEvent | None] | None = None
        self._journal_task: asyncio.Task[None] | None = None

    # -- emission ------------------------------------------------------
    @property
    def last_seq(self) -> int:
        return self._seq

    def emit(
        self,
        event_type: RuntimeEventType,
        *,
        agent_id: str = "NEXUS",
        task_id: str = "",
        **payload: Any,
    ) -> RuntimeEvent:
        """Append one event to the run's timeline and fan it out."""
        if self._closed:
            raise RuntimeError(f"run {self.run_id} event stream is closed")

        self._seq += 1
        event = RuntimeEvent(
            run_id=self.run_id,
            seq=self._seq,
            type=event_type,
            agent_id=agent_id,
            task_id=task_id,
            payload=payload,
        )
        self._buffer.append(event)

        # No await between seq assignment and fan-out: order is preserved by
        # construction rather than by luck of scheduler resumption.
        for queue in self._subscribers:
            _offer(queue, event)
        if self._journal_queue is not None:
            _offer(self._journal_queue, event)
        return event

    # -- subscription --------------------------------------------------
    async def subscribe(self, *, after_seq: int = 0) -> AsyncIterator[RuntimeEvent]:
        """Yield buffered history after ``after_seq``, then live events.

        A browser that refreshes reconnects with the highest ``seq`` it has
        already rendered and receives the gap, in order, without duplicates.
        """
        queue: asyncio.Queue[RuntimeEvent | None] = asyncio.Queue(
            maxsize=self._subscriber_queue_size
        )
        backlog = [event for event in self._buffer if event.seq > after_seq]
        self._subscribers.append(queue)
        highest = after_seq
        try:
            for event in backlog:
                highest = event.seq
                yield event
            while True:
                event = await queue.get()
                if event is None:
                    break
                if event.seq <= highest:
                    continue  # already delivered from the backlog
                highest = event.seq
                yield event
        finally:
            with contextlib.suppress(ValueError):
                self._subscribers.remove(queue)

    def replay(self, *, after_seq: int = 0) -> list[RuntimeEvent]:
        """Return buffered events after ``after_seq`` in order."""
        return [event for event in self._buffer if event.seq > after_seq]

    def history(self) -> list[RuntimeEvent]:
        return list(self._buffer)

    # -- durability ----------------------------------------------------
    def start_journal(self) -> None:
        """Begin draining events to disk on a background writer."""
        if self._journal_path is None or self._journal_task is not None:
            return
        self._journal_queue = asyncio.Queue()
        for event in self._buffer:
            _offer(self._journal_queue, event)
        self._journal_task = asyncio.create_task(self._drain_journal())

    async def _drain_journal(self) -> None:
        assert self._journal_path is not None and self._journal_queue is not None
        path = self._journal_path
        try:
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        except OSError:
            logger.exception("Could not create journal directory for %s", path)
            return
        while True:
            event = await self._journal_queue.get()
            if event is None:
                return
            line = json.dumps(event.to_sse(), ensure_ascii=False, default=str)
            try:
                await asyncio.to_thread(_append_line, path, line)
            except OSError:
                logger.exception("Journal append failed for run %s", self.run_id)

    async def aclose(self) -> None:
        """Close the stream, flush the journal, and release subscribers."""
        if self._closed:
            return
        self._closed = True
        for queue in list(self._subscribers):
            _offer(queue, None)
        if self._journal_queue is not None:
            await self._journal_queue.put(None)
        if self._journal_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._journal_task
            self._journal_task = None

    @staticmethod
    def load_journal(path: Path) -> list[RuntimeEvent]:
        """Rebuild a run's timeline from disk after a backend restart."""
        if not path.is_file():
            return []
        events: list[RuntimeEvent] = []
        with path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    events.append(RuntimeEvent.from_dict(json.loads(raw)))
                except (ValueError, KeyError):
                    logger.warning("Skipping malformed journal line in %s", path)
        events.sort(key=lambda event: event.order_key)
        return events


def _append_line(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _offer(queue: asyncio.Queue[Any], item: Any) -> None:
    """Enqueue without ever applying backpressure to the agent.

    A disconnected browser must not be able to stop the run. When a
    subscriber queue is full the oldest unread event is discarded; the
    consumer notices the ``seq`` gap and can call :meth:`replay`.
    """
    try:
        queue.put_nowait(item)
        return
    except asyncio.QueueFull:
        with contextlib.suppress(asyncio.QueueEmpty):
            queue.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(item)


def dedupe_and_order(events: Iterable[RuntimeEvent]) -> list[RuntimeEvent]:
    """Reference implementation of the ordering the frontend must apply."""
    unique: dict[str, RuntimeEvent] = {}
    for event in events:
        unique.setdefault(event.event_id, event)
    return sorted(unique.values(), key=lambda event: event.order_key)


__all__ = [
    "RunEventStream",
    "RuntimeEvent",
    "RuntimeEventType",
    "dedupe_and_order",
]
