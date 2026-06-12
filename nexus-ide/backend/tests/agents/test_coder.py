"""Tests for backend.agents.coder."""

from __future__ import annotations

from backend.agents.base import AgentAction, AgentRequest
from backend.agents.coder import CoderAgent


class TestCoderAgent:
    def test_metadata(self) -> None:
        agent = CoderAgent()
        assert agent.name == "CODER"
        # Tier 1 uses the 7B coder ("medium") to keep RAM footprint reasonable.
        # Upgrade to "expert" (32B) once hardware is validated.
        assert agent.model_key == "coder"
        assert agent.prompt_file == "coder"

    def test_supported_actions(self) -> None:
        agent = CoderAgent()
        expected = {
            AgentAction.READ_FILE,
            AgentAction.READ_FILE_ABSOLUTE,
            AgentAction.WRITE_FILE,
            AgentAction.WRITE_FILE_ABSOLUTE,
            AgentAction.LIST_DIR,
            AgentAction.LIST_DIR_ABSOLUTE,
            AgentAction.SEARCH_CODEBASE,
            AgentAction.SEARCH_SYMBOLS,
            AgentAction.INDEX_SYMBOLS,
            AgentAction.CONSULT_AGENT,
            AgentAction.EXECUTE_CODE,
            AgentAction.RECALL_CONTEXT,
            AgentAction.STORE_MEMORY,
            AgentAction.FETCH_URL,
        }
        assert agent.supported_actions == expected

    async def test_run_streams_tokens(self, ollama_client) -> None:
        agent = CoderAgent()
        req = AgentRequest(
            session_id="s1",
            query="write hello world in python",
            client=ollama_client,
        )
        tokens = [t async for t in agent.run(req)]
        # ReAct loop emits event markers; raw tokens are in the stream
        assert "Hello" in tokens
        await ollama_client.aclose()
