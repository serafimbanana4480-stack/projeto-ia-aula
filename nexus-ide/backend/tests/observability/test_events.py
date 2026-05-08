"""Tests for backend.observability.events — Event and EventBus dataclasses."""
from __future__ import annotations

import datetime

import pytest

from backend.observability.events import Event, EventBus


class TestEvent:
    def test_defaults(self) -> None:
        e = Event(type="test_event")
        assert e.type == "test_event"
        assert e.agent is None
        assert e.payload == {}
        assert isinstance(e.timestamp, datetime.datetime)

    def test_full_instantiation(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        e = Event(
            type="agent_started",
            agent="ROUTER",
            payload={"query": "hello"},
            timestamp=now,
        )
        assert e.agent == "ROUTER"
        assert e.payload["query"] == "hello"
        assert e.timestamp.tzinfo is not None


class TestEventBus:
    def test_publish_raises(self) -> None:
        bus = EventBus()
        import asyncio

        with pytest.raises(NotImplementedError):
            asyncio.run(bus.publish(Event(type="x")))

    def test_subscribe_raises(self) -> None:
        import asyncio

        bus = EventBus()
        with pytest.raises(NotImplementedError):
            asyncio.run(bus.subscribe("#"))
