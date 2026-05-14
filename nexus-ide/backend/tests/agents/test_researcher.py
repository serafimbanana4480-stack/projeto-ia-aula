"""Tests for backend.agents.researcher."""

from __future__ import annotations

from backend.agents.researcher import ResearcherAgent


class TestResearcherAgent:
    def test_metadata(self) -> None:
        agent = ResearcherAgent()
        assert agent.name == "RESEARCHER"
        assert agent.model_key == "small"
        assert agent.prompt_file == "researcher"
