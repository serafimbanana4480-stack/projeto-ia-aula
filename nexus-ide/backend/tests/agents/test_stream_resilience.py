"""Regression tests for agent-level streaming fallback behaviour."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from backend.agents.base import AgentBase, AgentRequest


class _TestAgent(AgentBase):
    name = "STREAM_TEST"
    model_key = "nano"
    prompt_file = "router"
    enable_memory = False


class _PartialClient:
    def __init__(self) -> None:
        self.models: list[str] = []
        self.options: dict[str, Any] | None = None

    async def chat_stream(self, model: str, messages, options=None, **kwargs) -> AsyncIterator[str]:
        self.models.append(model)
        self.options = options
        yield "visible output"
        raise RuntimeError("stream disconnected")


class _InspectOptionsClient:
    def __init__(self) -> None:
        self.options: dict[str, Any] | None = None

    async def chat_stream(self, model: str, messages, options=None, **kwargs) -> AsyncIterator[str]:
        self.options = options
        yield "ok"


@pytest.mark.asyncio
async def test_agent_does_not_restart_model_after_visible_output() -> None:
    agent = _TestAgent()
    client = _PartialClient()
    request = AgentRequest(session_id="stream-test", query="hello", client=client)

    stream = agent.stream_llm(request)
    assert await anext(stream) == "visible output"
    with pytest.raises(RuntimeError, match="stream disconnected"):
        await anext(stream)

    # The nano tier has a configured fallback; it must not be started after
    # the first provider has already emitted text.
    assert len(client.models) == 1


@pytest.mark.asyncio
async def test_agent_supplies_a_bounded_output_budget_to_all_provider_styles() -> None:
    agent = _TestAgent()
    client = _InspectOptionsClient()
    request = AgentRequest(session_id="budget-test", query="hello", client=client)

    assert [token async for token in agent.stream_llm(request)] == ["ok"]
    assert client.options is not None
    assert client.options["num_predict"] == 512
    assert client.options["max_tokens"] == 512
    assert client.options["max_output_tokens"] == 512
