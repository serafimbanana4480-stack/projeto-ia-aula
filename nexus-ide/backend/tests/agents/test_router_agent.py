"""Tests for backend.agents.router_agent."""
from __future__ import annotations

from backend.agents.base import AgentRequest
from backend.agents.router_agent import RouterAgent


class TestRouterAgent:
    def test_metadata(self) -> None:
        agent = RouterAgent()
        assert agent.name == "ROUTER"
        assert agent.model_key == "nano"
        assert agent.prompt_file == "router"
        assert agent.supported_actions == set()

    async def test_run_streams_tokens(self, ollama_client) -> None:
        agent = RouterAgent()
        req = AgentRequest(session_id="s1", query="hi", client=ollama_client)
        tokens = [t async for t in agent.run(req)]
        # RouterAgent just relays through stream_llm — fixture returns 4 tokens.
        assert tokens == ["Hello", ", ", "world", "!"]
        await ollama_client.aclose()
