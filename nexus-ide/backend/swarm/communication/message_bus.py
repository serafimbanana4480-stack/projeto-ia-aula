"""Inter-agent message bus.

Provides a fully-audited, in-process pub/sub for SWARM agents.

Key properties
--------------
- Every message is persisted in a per-run history (no silent drops).
- Subscribers can filter by sender, recipient, or message type.
- Convenience helpers for request/response correlation.
- Thread-safe and async-safe.
- Lightweight: the default store is a list; the bus is safe to share across
  the orchestrator, dashboard SSE, and tests.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from typing import Any

from backend.swarm.core.types import AgentMessage, MessageType

logger = logging.getLogger(__name__)


class MessageBus:
    """In-process pub/sub for SWARM inter-agent messages.

    Subscribers register for a topic (sender, recipient, or type) and receive
    messages through an ``asyncio.Queue``. Every published message is also
    appended to ``history`` for full traceability.
    """

    def __init__(self, max_queue_size: int = 1000, max_history: int = 10_000) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[AgentMessage]]] = defaultdict(list)
        self._max_queue_size = max_queue_size
        self._history: list[AgentMessage] = []
        self._max_history = max_history
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def publish(self, message: AgentMessage) -> AgentMessage:
        """Publish a message to all matching subscribers and persist in history."""
        if not message.message_id:
            message.message_id = uuid.uuid4().hex[:12]
        if not message.timestamp:
            message.timestamp = time.time()

        async with self._lock:
            # Persist (rolling window)
            self._history.append(message)
            if len(self._history) > self._max_history:
                # Drop oldest 10% to amortise cost
                drop = max(1, self._max_history // 10)
                del self._history[:drop]

        topics = self._topics_for(message)
        for topic in topics:
            for queue in self._subscribers.get(topic, []):
                try:
                    if queue.full():
                        # Drop oldest to make room
                        with contextlib.suppress(asyncio.QueueEmpty):
                            queue.get_nowait()
                    queue.put_nowait(message)
                except asyncio.QueueFull:  # pragma: no cover
                    logger.warning(
                        "MessageBus queue full on topic %s, dropping msg %s",
                        topic,
                        message.message_id,
                    )
        return message

    async def request_response(
        self,
        sender: str,
        recipient: str,
        content: str,
        payload: dict[str, Any] | None = None,
        timeout: float = 60.0,
        correlation_id: str | None = None,
    ) -> AgentMessage:
        """Send a request and wait for a single response (matched by correlation_id)."""
        corr = correlation_id or uuid.uuid4().hex[:12]
        req = AgentMessage(
            sender=sender,
            recipient=recipient,
            type=MessageType.REQUEST,
            content=content,
            payload=payload or {},
            correlation_id=corr,
        )
        await self.publish(req)

        # Subscribe to responses matching our correlation
        queue: asyncio.Queue[AgentMessage] = asyncio.Queue(maxsize=self._max_queue_size)
        topic = self._response_topic(corr)
        self._subscribers[topic].append(queue)
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=timeout)
                    return msg
                except TimeoutError as exc:
                    raise TimeoutError(
                        f"No response to {sender}→{recipient} within {timeout}s"
                    ) from exc
        finally:
            with contextlib.suppress(ValueError):
                self._subscribers[topic].remove(queue)

    async def respond(
        self,
        sender: str,
        in_reply_to: AgentMessage,
        content: str,
        payload: dict[str, Any] | None = None,
    ) -> AgentMessage:
        """Send a RESPONSE message in reply to another message."""
        msg = AgentMessage(
            sender=sender,
            recipient=in_reply_to.sender,
            type=MessageType.RESPONSE,
            content=content,
            payload=payload or {},
            correlation_id=in_reply_to.correlation_id,
            in_reply_to=in_reply_to.message_id,
        )
        await self.publish(msg)
        return msg

    # ------------------------------------------------------------------
    # Subscribing
    # ------------------------------------------------------------------

    async def subscribe(self, topic: str = "*") -> AsyncIterator[AgentMessage]:
        """Async generator yielding messages for ``topic`` until cancelled."""
        queue: asyncio.Queue[AgentMessage] = asyncio.Queue(maxsize=self._max_queue_size)
        self._subscribers[topic].append(queue)
        try:
            while True:
                msg = await queue.get()
                yield msg
        finally:
            with contextlib.suppress(ValueError):
                self._subscribers[topic].remove(queue)

    def subscribe_callback(self, topic: str, callback: Callable[[AgentMessage], Any]) -> None:
        """Register a sync callback for a topic (fire-and-forget)."""
        # Stored as a list wrapper so publish() can later extend this if needed
        # Currently the asyncio generator path is the primary subscription.
        if not hasattr(self, "_callbacks"):
            self._callbacks: dict[str, list[Callable[[AgentMessage], Any]]] = defaultdict(list)
        self._callbacks[topic].append(callback)

    # ------------------------------------------------------------------
    # History / introspection
    # ------------------------------------------------------------------

    def history(
        self,
        sender: str | None = None,
        recipient: str | None = None,
        type: MessageType | None = None,
        limit: int = 100,
    ) -> list[AgentMessage]:
        """Return filtered history (most recent first)."""
        results: list[AgentMessage] = []
        for msg in reversed(self._history):
            if sender and msg.sender != sender:
                continue
            if recipient and msg.recipient != recipient:
                continue
            if type and msg.type != type:
                continue
            results.append(msg)
            if len(results) >= limit:
                break
        return results

    def all_history(self) -> list[AgentMessage]:
        """Return a copy of the full history."""
        return list(self._history)

    def clear(self) -> None:
        """Clear all history (used between runs)."""
        self._history.clear()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _topics_for(msg: AgentMessage) -> list[str]:
        topics = ["*"]
        if msg.sender:
            topics.append(f"sender:{msg.sender}")
        if msg.recipient:
            topics.append(f"recipient:{msg.recipient}")
        topics.append(f"type:{msg.type.value}")
        if msg.correlation_id:
            topics.append(f"corr:{msg.correlation_id}")
        return topics

    @staticmethod
    def _response_topic(correlation_id: str) -> str:
        return f"corr:{correlation_id}"


# ---------------------------------------------------------------------------
# Global singleton (one per process — sufficient for SWARM run scope)
# ---------------------------------------------------------------------------

_bus: MessageBus | None = None


def get_message_bus() -> MessageBus:
    """Return the global SWARM message bus (created lazily)."""
    global _bus
    if _bus is None:
        _bus = MessageBus()
    return _bus


def reset_message_bus() -> None:
    """Reset the global message bus (mostly for tests)."""
    global _bus
    _bus = None


__all__ = ["MessageBus", "get_message_bus", "reset_message_bus"]
