"""Tests for EventBus."""
import asyncio
import contextlib

import pytest

from backend.observability.event_bus import EventBus
from backend.observability.events import Event


class TestEventBus:
    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def consumer() -> None:
            async for event in bus.subscribe("agent.*"):
                received.append(event)
                if len(received) >= 2:
                    break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)  # Allow subscriber to register

        await bus.publish(Event(type="agent.started", agent="coder"))
        await bus.publish(Event(type="agent.completed", agent="tester"))
        await bus.publish(Event(type="system.error"))  # Should not match

        try:
            await asyncio.wait_for(task, timeout=2.0)
        except TimeoutError:
            task.cancel()

        assert len(received) == 2
        assert received[0].type == "agent.started"
        assert received[1].type == "agent.completed"

    @pytest.mark.asyncio
    async def test_wildcard_subscribe(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def consumer() -> None:
            async for event in bus.subscribe("*"):
                received.append(event)
                if len(received) >= 2:
                    break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)
        await bus.publish(Event(type="anything"))
        await bus.publish(Event(type="something.else"))
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except TimeoutError:
            task.cancel()

        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_no_match(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def consumer() -> None:
            async for event in bus.subscribe("specific.event"):
                received.append(event)
                break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)
        await bus.publish(Event(type="other.event"))

        # Wait briefly then cancel
        await asyncio.sleep(0.2)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_subscriber_count(self) -> None:
        bus = EventBus()
        assert await bus.subscriber_count("*") == 0

        async def consumer() -> None:
            async for _ in bus.subscribe("*"):
                pass

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)
        assert await bus.subscriber_count("*") == 1

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        await asyncio.sleep(0.05)
        assert await bus.subscriber_count("*") == 0
