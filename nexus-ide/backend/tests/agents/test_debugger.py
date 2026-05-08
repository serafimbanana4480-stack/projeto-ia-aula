"""Tests for backend.agents.debugger."""
from __future__ import annotations

from backend.agents.base import AgentAction
from backend.agents.debugger import DebuggerAgent


class TestDebuggerAgent:
    def test_metadata(self) -> None:
        agent = DebuggerAgent()
        assert agent.name == "DEBUGGER"
        assert agent.model_key == "medium"
        assert agent.prompt_file == "debugger"

    def test_supported_actions(self) -> None:
        agent = DebuggerAgent()
        expected = {
            AgentAction.READ_FILE,
            AgentAction.EXECUTE_CODE,
            AgentAction.SEARCH_CODEBASE,
        }
        assert agent.supported_actions == expected
