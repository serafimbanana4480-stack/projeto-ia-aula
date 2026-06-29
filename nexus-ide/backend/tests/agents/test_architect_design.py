"""Tests for backend.agents.architect_design."""

from __future__ import annotations

from backend.agents.architect_design import ArchitectDesignAgent
from backend.agents.base import AgentAction


class TestArchitectDesignAgent:
    def test_metadata(self) -> None:
        agent = ArchitectDesignAgent()
        assert agent.name == "ARCHITECT_DESIGN"
        assert agent.model_key == "reasoning"
        assert agent.prompt_file == "architect_design"

    def test_supported_actions(self) -> None:
        agent = ArchitectDesignAgent()
        assert agent.supported_actions == {
            AgentAction.READ_FILE,
            AgentAction.SEARCH_CODEBASE,
            AgentAction.CONSULT_AGENT,
            AgentAction.RECALL_CONTEXT,
            AgentAction.WRITE_FILE,
        }
