"""Tests for backend.agents.bug_hunter_static."""

from __future__ import annotations

from backend.agents.base import AgentAction
from backend.agents.bug_hunter_static import BugHunterStaticAgent


class TestBugHunterStaticAgent:
    def test_metadata(self) -> None:
        agent = BugHunterStaticAgent()
        assert agent.name == "BUG_HUNTER_STATIC"
        assert agent.model_key == "coder"
        assert agent.prompt_file == "bug_hunter_static"

    def test_supported_actions(self) -> None:
        agent = BugHunterStaticAgent()
        expected = {
            AgentAction.READ_FILE,
            AgentAction.SEARCH_CODEBASE,
            AgentAction.EXECUTE_CODE,
            AgentAction.CONSULT_AGENT,
        }
        assert agent.supported_actions == expected
