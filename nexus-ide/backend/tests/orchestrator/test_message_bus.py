"""Tests for MessageBus."""
import asyncio

import pytest

from backend.orchestrator.message_bus import AgentMessage, MessageBus


class TestMessageBus:
    @pytest.mark.asyncio
    async def test_send_and_receive(self) -> None:
        bus = MessageBus()
        received: list[AgentMessage] = []

        async def consumer() -> None:
            async for msg in bus.subscribe_messages("agent-b"):
                received.append(msg)
                if len(received) >= 1:
                    break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)

        msg = AgentMessage(msg_type="CONSULT", sender="agent-a", recipient="agent-b", payload={"q": "hello"})
        await bus.send(msg)

        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.TimeoutError:
            task.cancel()

        assert len(received) == 1
        assert received[0].sender == "agent-a"
        assert received[0].payload["q"] == "hello"

    @pytest.mark.asyncio
    async def test_request_response(self) -> None:
        bus = MessageBus()

        request = AgentMessage(msg_type="CONSULT", sender="a", recipient="b", payload={"task": "x"})
        # Response would normally come from another agent; here we simulate
        asyncio.create_task(asyncio.sleep(0.1))

        # Since no one responds, we test timeout
        response = await bus.request(request, timeout=0.05)
        assert response is None  # Timeout

    @pytest.mark.asyncio
    async def test_broadcast(self) -> None:
        bus = MessageBus()
        # Broadcast with no responders returns empty list quickly due to timeout
        responses = await bus.broadcast("a", "Who can code?")
        assert isinstance(responses, list)
