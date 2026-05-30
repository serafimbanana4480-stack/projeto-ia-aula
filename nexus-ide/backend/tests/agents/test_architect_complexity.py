"""Tests for backend.agents.architect_complexity."""

from __future__ import annotations

from backend.agents.architect_complexity import ArchitectComplexityAgent
from backend.agents.base import AgentAction


class TestArchitectComplexityAgent:
    def test_metadata(self) -> None:
        agent = ArchitectComplexityAgent()
        assert agent.name == "ARCHITECT_COMPLEXITY"
        assert agent.model_key == "reasoning"
        assert agent.prompt_file == "architect_complexity"

    def test_supported_actions(self) -> None:
        agent = ArchitectComplexityAgent()
        assert agent.supported_actions == {
            AgentAction.READ_FILE,
            AgentAction.SEARCH_CODEBASE,
            AgentAction.CONSULT_AGENT,
            AgentAction.ANALYZE_DATA,
        }
