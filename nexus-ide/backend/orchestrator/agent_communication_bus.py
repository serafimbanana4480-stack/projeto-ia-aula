"""Real-time Agent Communication Bus — pub/sub messaging between agents."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)





@dataclass
class AgentMessage:
    """A message sent between agents."""

    message_id: str
    sender: str
    recipient: str  # "*" for broadcast
    message_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    priority: int = 0  # Higher = more urgent


class AgentCommunicationBus:
    """Real-time pub/sub bus for inter-agent communication.

    Supports:
    - Direct messaging between agents
    - Broadcast messages
    - Priority queueing
    - Message history
    """

    def __init__(self, max_history: int = 1000) -> None:
        self._subscribers: dict[str, list[Callable[[AgentMessage], Any]]] = {}
        self._broadcast_subscribers: list[Callable[[AgentMessage], Any]] = []
        self._history: list[AgentMessage] = []
        self._max_history = max_history
        self._message_count = 0
        self._lock = threading.Lock()

    def subscribe(self, agent_id: str, handler: Callable[[AgentMessage], Any]) -> None:
        """Subscribe an agent to receive direct messages."""
        if agent_id not in self._subscribers:
            self._subscribers[agent_id] = []
        self._subscribers[agent_id].append(handler)
        logger.debug("Agent %s subscribed", agent_id)

    def subscribe_broadcast(self, handler: Callable[[AgentMessage], Any]) -> None:
        """Subscribe to broadcast messages."""
        self._broadcast_subscribers.append(handler)

    def unsubscribe(self, agent_id: str, handler: Callable[[AgentMessage], Any]) -> None:
        """Unsubscribe an agent."""
        if agent_id in self._subscribers:
            if handler in self._subscribers[agent_id]:
                self._subscribers[agent_id].remove(handler)

    def send(self, message: AgentMessage) -> bool:
        """Send a message (direct or broadcast)."""
        with self._lock:
            self._history.append(message)
            if len(self._history) > self._max_history:
                self._history.pop(0)
            self._message_count += 1

        delivered = False

        if message.recipient == "*":
            # Broadcast
            for handler in self._broadcast_subscribers:
                try:
                    handler(message)
                    delivered = True
                except Exception as e:
                    logger.error("Broadcast handler error: %s", e)
        else:
            # Direct message
            handlers = self._subscribers.get(message.recipient, [])
            for handler in handlers:
                try:
                    handler(message)
                    delivered = True
                except Exception as e:
                    logger.error("Message handler error for %s: %s", message.recipient, e)

        logger.debug("Message %s delivered=%s", message.message_id, delivered)
        return delivered

    def get_history(
        self,
        sender: Optional[str] = None,
        recipient: Optional[str] = None,
        message_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[AgentMessage]:
        """Query message history with filters."""
        messages = self._history
        if sender:
            messages = [m for m in messages if m.sender == sender]
        if recipient:
            messages = [m for m in messages if m.recipient == recipient]
        if message_type:
            messages = [m for m in messages if m.message_type == message_type]
        return messages[-limit:]

    def stats(self) -> dict[str, Any]:
        return {
            "total_messages": self._message_count,
            "history_size": len(self._history),
            "subscribers": len(self._subscribers),
            "broadcast_subscribers": len(self._broadcast_subscribers),
        }
