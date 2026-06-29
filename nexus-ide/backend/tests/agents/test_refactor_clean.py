"""Tests for backend.agents.refactor_clean."""

from __future__ import annotations

from backend.agents.base import AgentAction, AgentRequest
from backend.agents.refactor_clean import RefactorCleanAgent


class TestRefactorCleanAgent:
    def test_metadata(self) -> None:
        agent = RefactorCleanAgent()
        assert agent.name == "REFACTOR_CLEAN"
        assert agent.model_key == "coder"
        assert agent.prompt_file == "refactor_clean"

    def test_supported_actions(self) -> None:
        agent = RefactorCleanAgent()
        expected = {
            AgentAction.READ_FILE,
            AgentAction.WRITE_FILE,
            AgentAction.SEARCH_CODEBASE,
            AgentAction.CONSULT_AGENT,
        }
        assert agent.supported_actions == expected

    async def test_run_streams_tokens(self, ollama_client) -> None:
        agent = RefactorCleanAgent()
        req = AgentRequest(
            session_id="s1",
            query="refactor this messy class to follow SOLID",
            client=ollama_client,
        )
        tokens = [t async for t in agent.run(req)]
        # ReAct loop emits event markers; raw tokens are in the stream
        assert len(tokens) > 0
        await ollama_client.aclose()
