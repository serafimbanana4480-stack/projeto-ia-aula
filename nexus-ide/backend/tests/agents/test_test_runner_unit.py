"""Tests for backend.agents.test_runner_unit."""

from __future__ import annotations

from backend.agents.base import AgentAction, AgentRequest
from backend.agents.test_runner_unit import TestRunnerUnitAgent


class TestTestRunnerUnitAgent:
    def test_metadata(self) -> None:
        agent = TestRunnerUnitAgent()
        assert agent.name == "TEST_RUNNER_UNIT"
        assert agent.model_key == "coder"
        assert agent.prompt_file == "test_runner_unit"

    def test_supported_actions(self) -> None:
        agent = TestRunnerUnitAgent()
        expected = {
            AgentAction.READ_FILE,
            AgentAction.EXECUTE_CODE,
            AgentAction.SEARCH_CODEBASE,
            AgentAction.WRITE_FILE,
            AgentAction.CONSULT_AGENT,
        }
        assert agent.supported_actions == expected

    async def test_run_streams_tokens(self, ollama_client) -> None:
        agent = TestRunnerUnitAgent()
        req = AgentRequest(
            session_id="s1",
            query="run unit tests for this project",
            client=ollama_client,
        )
        tokens = [t async for t in agent.run(req)]
        # ReAct loop emits event markers; raw tokens are in the stream
        assert len(tokens) > 0
        await ollama_client.aclose()
