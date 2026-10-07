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
import re
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_active_run_streams: dict[str, RunEventStream] = {}


def run_event_journal_path(run_id: str) -> Path | None:
    """Return the repository-local journal path for a safe run id.

    Run ids can arrive from authenticated replay URLs, so they must never be
    used as path components before validation.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(run_id or "")):
        return None
    try:
        root = Path(__file__).resolve().parents[3]
        return root / "data" / "runs" / f"{run_id}.jsonl"
    except (IndexError, OSError, ValueError):
        return None


def get_active_run_event_stream(run_id: str) -> RunEventStream | None:
    """Return the live event stream for *run_id*, if this process owns it."""
    stream = _active_run_streams.get(run_id)
    return stream if stream is not None and not stream._closed else None


class RuntimeEventType(StrEnum):
    """The stable event vocabulary the UI renders.

    Operational transparency, not chain-of-thought: every member describes
    something the agent *did*, is waiting on, or observed.

    :attr:`THINKING` is the one member that carries model-authored text. Its
    payload is the *operational approach* the agent is declaring — a bounded
    label (see :mod:`backend.runtime.reasoning`), never a private transcript —
    and it lives in the payload key ``text`` so the meaning of the payload is
    unambiguous to every consumer.
    """

    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"
    RUN_INTERRUPTED = "run_interrupted"

    MESSAGE_STARTED = "message_started"
    MESSAGE_DELTA = "message_delta"
    MESSAGE_COMPLETED = "message_completed"

    STATUS_UPDATE = "status_update"
    PLAN_UPDATED = "plan_updated"

    #: Bounded, public approach text for the on-screen reasoning panel.
    #: Payload key: ``text``. See the class docstring for the privacy contract.
    THINKING = "thinking"

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
    PROVIDER_RESULT = "provider_result"

    SUBAGENT_STARTED = "subagent_started"
    SUBAGENT_PROGRESS = "subagent_progress"
    SUBAGENT_COMPLETED = "subagent_completed"

    WAITING_DEPENDENCY = "waiting_dependency"
    HEARTBEAT = "heartbeat"
    RECOVERY = "recovery"
    USER_STEERING = "user_steering"
    ADVISOR_NOTE = "advisor_note"

    # Infinity v3 (port do advisor/vibe do omp). Emitidos por observadores
    # externos ao loop principal; o loop nunca os produz.
    WORKER_UPDATE = "worker_update"


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
        """Rebuild an event from its journal / SSE dictionary.

        ``RuntimeEventType(raw["type"])`` raises ``ValueError`` for a value this
        build does not know — which is exactly what happens when a journal
        written by a newer (or older) build is replayed. Replay paths must use
        :meth:`try_from_dict`, which skips instead of crashing.
        """
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

    @classmethod
    def try_from_dict(cls, raw: Any) -> RuntimeEvent | None:
        """Tolerant :meth:`from_dict` for every replay path.

        Returns ``None`` for a line this build cannot interpret — an unknown
        event type written by another build, a truncated JSON object, a missing
        ordering key — and logs it. A single bad line must never be able to
        abort a replay of an otherwise complete run.
        """
        if not isinstance(raw, dict):
            logger.warning("Skipping non-object journal entry")
            return None
        try:
            return cls.from_dict(raw)
        except ValueError as exc:
            # Unknown RuntimeEventType from a foreign build, or a non-numeric seq.
            logger.warning("Skipping journal entry with unknown type: %s", exc)
            return None
        except (KeyError, TypeError) as exc:
            logger.warning("Skipping malformed journal entry: %s", exc)
            return None


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
        _active_run_streams[run_id] = self

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
        self._subscribers.append(queue)
        # Subscribe before reading disk so events emitted after the snapshot
        # are queued while older journal entries are being replayed. Disk is
        # read synchronously on this event loop, so no emit can interleave in
        # the short section below.
        backlog_by_seq: dict[int, RuntimeEvent] = {}
        if self._journal_path is not None and self._journal_path.is_file():
            try:
                backlog_by_seq.update(
                    {
                        event.seq: event
                        for event in self.load_journal(self._journal_path)
                        if event.run_id == self.run_id and event.seq > after_seq
                    }
                )
            except OSError:
                logger.exception("Could not replay journal for run %s", self.run_id)
        # In-memory events win over an older copy in the durable journal.
        backlog_by_seq.update(
            {
                event.seq: event
                for event in self._buffer
                if event.seq > after_seq
            }
        )
        backlog = [backlog_by_seq[key] for key in sorted(backlog_by_seq)]
        highest = after_seq
        try:
            for event in backlog:
                highest = event.seq
                yield event
            if self._closed:
                return
            while True:
                queued_event = await queue.get()
                if queued_event is None:
                    break
                if queued_event.seq <= highest:
                    continue  # already delivered from the backlog
                highest = queued_event.seq
                yield queued_event
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
        if _active_run_streams.get(self.run_id) is self:
            _active_run_streams.pop(self.run_id, None)
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
        """Rebuild a run's timeline from disk after a backend restart.

        A line this build cannot interpret is skipped, never raised on: a
        journal written by another build (or truncated by a full disk) still
        yields every event that *is* understood.
        """
        if not path.is_file():
            return []
        events: list[RuntimeEvent] = []
        with path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    decoded = json.loads(raw)
                except (ValueError, TypeError):
                    logger.warning("Skipping malformed journal line in %s", path)
                    continue
                event = RuntimeEvent.try_from_dict(decoded)
                if event is not None:
                    events.append(event)
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
    "get_active_run_event_stream",
    "run_event_journal_path",
]
