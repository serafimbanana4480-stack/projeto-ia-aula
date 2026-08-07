"""Internal event bus feeding the Dashboard Agent and SSE streams.

In-process pub/sub using asyncio queues. For multi-worker deployments,
swap in Redis Pub/Sub.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """UTC ``now`` with timezone attached. Replaces deprecated ``datetime.utcnow``."""
    return datetime.now(UTC)


@dataclass
class Event:
    """A single bus event.

    ``payload`` is the canonical field — 100+ call sites read ``event.payload``.
    ``data`` exists because 50 call sites across 11 modules (reflection,
    meta-cognition, human oversight, cross-session memory, analytics, ...) were
    written against a ``data=`` keyword that this class never had. Every one of
    them raised ``TypeError`` inside a broad ``except Exception``, so those
    subsystems looked implemented while emitting nothing at all.

    Accepting the alias is the smaller change: renaming 50 call sites risks
    touching code paths that have no test coverage, while this keeps both
    spellings valid and always in sync.
    """

    type: str  # e.g. "agent_started", "token", "anomaly", "fallback"
    agent: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=_utcnow)
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Whichever spelling the caller used wins; both then point at the same
        # dict so a mutation through one is visible through the other.
        if self.data and not self.payload:
            self.payload = self.data
        self.data = self.payload


class EventBus:
    """In-process pub/sub with async subscribers.

    Subscribers register for a topic and receive events through an
    asyncio.Queue. Events are published to all matching subscribers.
    """

    def __init__(self, max_queue_size: int = 1000) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[Event]]] = defaultdict(list)
        self._max_queue_size = max_queue_size

    async def emit(self, event: Event) -> None:
        """Alias for :meth:`publish`.

        50 call sites were written against ``bus.emit(...)``, which never
        existed on this class. Each raised ``AttributeError`` into a broad
        ``except Exception`` and was logged as a generic failure of the
        surrounding feature — see ``supreme.py``'s "Failed to perform
        orchestration reflection", where the reflection had in fact succeeded
        and only its announcement was lost.
        """
        await self.publish(event)

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers matching its type."""
        topic = event.type
        queues = self._subscribers.get(topic, []) + self._subscribers.get("*", [])

        for queue in queues:
            try:
                # Use put_nowait to avoid blocking; drop oldest if full
                if queue.full():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        queue.get_nowait()
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Event queue full for topic %s, dropping event", topic)

        logger.debug("Published event type=%s to %d subscribers", topic, len(queues))

    async def subscribe(self, topic: str = "*"):
        """Async generator yielding events matching `topic`.

        Use "*" to subscribe to all events.
        """
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._max_queue_size)
        self._subscribers[topic].append(queue)

        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            # Cleanup on unsubscribe
            if topic in self._subscribers:
                with contextlib.suppress(ValueError):
                    self._subscribers[topic].remove(queue)

    def subscribe_queue(self, topic: str = "*") -> asyncio.Queue[Event]:
        """Get a queue for the given topic (alternative to async generator)."""
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._max_queue_size)
        self._subscribers[topic].append(queue)
        return queue

    def subscriber_count(self, topic: str | None = None) -> int:
        """Return the number of subscribers. If topic is None, return total."""
        if topic:
            return len(self._subscribers.get(topic, []))
        return sum(len(qs) for qs in self._subscribers.values())


# Global singleton
_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get the global EventBus instance."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
