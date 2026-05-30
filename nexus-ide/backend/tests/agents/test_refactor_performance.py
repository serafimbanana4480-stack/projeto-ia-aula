"""Tests for backend.agents.refactor_performance."""

from __future__ import annotations

from backend.agents.base import AgentAction, AgentRequest
from backend.agents.refactor_performance import RefactorPerformanceAgent


class TestRefactorPerformanceAgent:
    def test_metadata(self) -> None:
        agent = RefactorPerformanceAgent()
        assert agent.name == "REFACTOR_PERFORMANCE"
        assert agent.model_key == "coder"
        assert agent.prompt_file == "refactor_performance"

    def test_supported_actions(self) -> None:
        agent = RefactorPerformanceAgent()
        expected = {
            AgentAction.READ_FILE,
            AgentAction.WRITE_FILE,
            AgentAction.EXECUTE_CODE,
            AgentAction.SEARCH_CODEBASE,
            AgentAction.CONSULT_AGENT,
        }
        assert agent.supported_actions == expected

    async def test_run_streams_tokens(self, ollama_client) -> None:
        agent = RefactorPerformanceAgent()
        req = AgentRequest(
            session_id="s1",
            query="optimize this slow function",
            client=ollama_client,
        )
        tokens = [t async for t in agent.run(req)]
        # ReAct loop emits event markers; raw tokens are in the stream
        assert len(tokens) > 0
        await ollama_client.aclose()
