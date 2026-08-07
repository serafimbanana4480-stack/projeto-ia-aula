"""Tests for backend.observability.events — Event and EventBus."""

from __future__ import annotations

import asyncio
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
        now = datetime.datetime.now(datetime.UTC)
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
    def test_publish_and_subscribe(self) -> None:
        """Test that events are published and received by subscribers."""
        bus = EventBus()
        received: list[Event] = []

        async def _test():
            # Start subscriber task
            async def subscriber():
                async for event in bus.subscribe("test_topic"):
                    received.append(event)
                    if len(received) >= 2:
                        return

            sub_task = asyncio.create_task(subscriber())

            # Give subscriber time to register
            await asyncio.sleep(0.05)

            # Publish events
            await bus.publish(Event(type="test_topic", agent="CODER"))
            await bus.publish(Event(type="test_topic", agent="ARCHITECT"))

            # Wait for subscriber to receive
            await asyncio.wait_for(sub_task, timeout=2.0)

        asyncio.run(_test())
        assert len(received) == 2
        assert received[0].agent == "CODER"
        assert received[1].agent == "ARCHITECT"

    def test_subscribe_queue(self) -> None:
        """Test subscribe_queue returns a queue that receives events."""
        bus = EventBus()
        queue = bus.subscribe_queue("metrics")

        async def _test():
            await bus.publish(Event(type="metrics", payload={"cpu": 85}))
            event = await asyncio.wait_for(queue.get(), timeout=2.0)
            assert event.type == "metrics"
            assert event.payload["cpu"] == 85

        asyncio.run(_test())

    def test_subscriber_count(self) -> None:
        """Test subscriber count tracking."""
        bus = EventBus()
        assert bus.subscriber_count() == 0
        bus.subscribe_queue("topic_a")
        bus.subscribe_queue("topic_a")
        bus.subscribe_queue("topic_b")
        assert bus.subscriber_count("topic_a") == 2
        assert bus.subscriber_count("topic_b") == 1
        assert bus.subscriber_count() == 3


class TestEmitAliasAndDataKeyword:
    """50 call sites in 11 modules were dead code until these aliases existed.

    ``reflection_system``, ``meta_cognition``, ``approval_queue``,
    ``intervention_points``, ``oversight_interface``, ``cross_session_memory``,
    ``advanced_analytics``, ``edge_computing``, ``federated_learning``,
    ``neural_architecture_search`` and ``quantum_computing`` all call::

        await self.event_bus.emit(Event(type="...", data={...}))

    Neither ``EventBus.emit`` nor ``Event(data=...)`` existed. Both raised
    inside a broad ``except Exception``, so each subsystem logged a generic
    failure of its *own* feature and nobody traced it back to the bus.
    """

    def test_event_accepts_the_data_keyword(self) -> None:
        event = Event(type="reflection_completed", data={"score": 0.9})
        assert event.payload == {"score": 0.9}

    def test_data_and_payload_are_the_same_dict(self) -> None:
        event = Event(type="x", data={"a": 1})
        event.payload["b"] = 2
        assert event.data == {"a": 1, "b": 2}

    def test_payload_keyword_still_wins(self) -> None:
        event = Event(type="x", payload={"canonical": True})
        assert event.payload == {"canonical": True}
        assert event.data == {"canonical": True}

    def test_default_is_an_empty_dict_not_none(self) -> None:
        event = Event(type="x")
        assert event.payload == {}
        assert event.data == {}

    @pytest.mark.asyncio
    async def test_emit_delivers_like_publish(self) -> None:
        bus = EventBus()
        stream = bus.subscribe("reflection_completed")
        pending = asyncio.create_task(stream.__anext__())
        await asyncio.sleep(0)

        await bus.emit(Event(type="reflection_completed", data={"score": 0.9}))

        received = await asyncio.wait_for(pending, timeout=2)
        assert received.payload == {"score": 0.9}
