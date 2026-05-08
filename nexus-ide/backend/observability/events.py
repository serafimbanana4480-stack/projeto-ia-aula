"""Internal event bus feeding the Dashboard Agent and SSE streams."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _utcnow() -> datetime:
    """UTC ``now`` with timezone attached. Replaces deprecated ``datetime.utcnow``."""
    return datetime.now(timezone.utc)


@dataclass
class Event:
    type: str                 # e.g. "agent_started", "token", "anomaly", "fallback"
    agent: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=_utcnow)


class EventBus:
    """In-process pub/sub with async subscribers.

    TODO: back with Redis Pub/Sub for multi-worker deployments.
    """

    async def publish(self, event: Event) -> None:
        raise NotImplementedError

    async def subscribe(self, topic: str):
        """Async generator yielding events matching `topic`."""
        raise NotImplementedError
