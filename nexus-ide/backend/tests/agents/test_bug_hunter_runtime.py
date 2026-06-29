"""Tests for backend.agents.bug_hunter_runtime."""

from __future__ import annotations

from backend.agents.base import AgentAction
from backend.agents.bug_hunter_runtime import BugHunterRuntimeAgent


class TestBugHunterRuntimeAgent:
    def test_metadata(self) -> None:
        agent = BugHunterRuntimeAgent()
        assert agent.name == "BUG_HUNTER_RUNTIME"
        assert agent.model_key == "coder"
        assert agent.prompt_file == "bug_hunter_runtime"

    def test_supported_actions(self) -> None:
        agent = BugHunterRuntimeAgent()
        expected = {
            AgentAction.READ_FILE,
            AgentAction.EXECUTE_CODE,
            AgentAction.SEARCH_CODEBASE,
            AgentAction.CONSULT_AGENT,
        }
        assert agent.supported_actions == expected
