"""Tests for backend.agents.debugger."""

from __future__ import annotations

from backend.agents.base import AgentAction
from backend.agents.debugger import DebuggerAgent


class TestDebuggerAgent:
    def test_metadata(self) -> None:
        agent = DebuggerAgent()
        assert agent.name == "DEBUGGER"
        assert agent.model_key == "coder"
        assert agent.prompt_file == "debugger"

    def test_supported_actions(self) -> None:
        agent = DebuggerAgent()
        expected = {
            AgentAction.READ_FILE,
            AgentAction.READ_FILE_ABSOLUTE,
            AgentAction.EXECUTE_CODE,
            AgentAction.SEARCH_CODEBASE,
            AgentAction.SEARCH_SYMBOLS,
            AgentAction.INDEX_SYMBOLS,
            AgentAction.CONSULT_AGENT,
            AgentAction.RECALL_CONTEXT,
            AgentAction.STORE_MEMORY,
        }
        assert agent.supported_actions == expected
