"""Internal event bus feeding the Dashboard Agent and SSE streams.

In-process pub/sub using asyncio queues. For multi-worker deployments,
swap in Redis Pub/Sub.
"""

from __future__ import annotations

import asyncio
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
    type: str  # e.g. "agent_started", "token", "anomaly", "fallback"
    agent: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=_utcnow)


class EventBus:
    """In-process pub/sub with async subscribers.

    Subscribers register for a topic and receive events through an
    asyncio.Queue. Events are published to all matching subscribers.
    """

    def __init__(self, max_queue_size: int = 1000) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[Event]]] = defaultdict(list)
        self._max_queue_size = max_queue_size

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers matching its type."""
        topic = event.type
        queues = self._subscribers.get(topic, []) + self._subscribers.get("*", [])

        for queue in queues:
            try:
                # Use put_nowait to avoid blocking; drop oldest if full
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
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
                try:
                    self._subscribers[topic].remove(queue)
                except ValueError:
                    pass

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
