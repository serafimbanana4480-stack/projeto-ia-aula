"""Tests for backend.agents.architect."""

from __future__ import annotations

from backend.agents.architect import ArchitectAgent
from backend.agents.base import AgentAction


class TestArchitectAgent:
    def test_metadata(self) -> None:
        agent = ArchitectAgent()
        assert agent.name == "ARCHITECT"
        assert agent.model_key == "reasoning"
        assert agent.prompt_file == "architect"

    def test_supported_actions(self) -> None:
        agent = ArchitectAgent()
        expected = {
            AgentAction.CONSULT_AGENT,
            AgentAction.READ_FILE,
            AgentAction.READ_FILE_ABSOLUTE,
            AgentAction.SEARCH_CODEBASE,
            AgentAction.SEARCH_SYMBOLS,
            AgentAction.INDEX_SYMBOLS,
            AgentAction.RECALL_CONTEXT,
            AgentAction.STORE_MEMORY,
            AgentAction.WRITE_FILE,
            AgentAction.WRITE_FILE_ABSOLUTE,
            AgentAction.LIST_DIR,
            AgentAction.LIST_DIR_ABSOLUTE,
        }
        assert agent.supported_actions == expected
