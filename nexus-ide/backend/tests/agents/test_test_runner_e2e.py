"""Tests for backend.agents.test_runner_e2e."""

from __future__ import annotations

from backend.agents.base import AgentAction, AgentRequest
from backend.agents.test_runner_e2e import TestRunnerE2EAgent


class TestTestRunnerE2EAgent:
    def test_metadata(self) -> None:
        agent = TestRunnerE2EAgent()
        assert agent.name == "TEST_RUNNER_E2E"
        assert agent.model_key == "coder"
        assert agent.prompt_file == "test_runner_e2e"

    def test_supported_actions(self) -> None:
        agent = TestRunnerE2EAgent()
        expected = {
            AgentAction.READ_FILE,
            AgentAction.EXECUTE_CODE,
            AgentAction.SEARCH_CODEBASE,
            AgentAction.CONSULT_AGENT,
        }
        assert agent.supported_actions == expected

    async def test_run_streams_tokens(self, ollama_client) -> None:
        agent = TestRunnerE2EAgent()
        req = AgentRequest(
            session_id="s1",
            query="run end-to-end tests for this project",
            client=ollama_client,
        )
        tokens = [t async for t in agent.run(req)]
        # ReAct loop emits event markers; raw tokens are in the stream
        assert len(tokens) > 0
        await ollama_client.aclose()
