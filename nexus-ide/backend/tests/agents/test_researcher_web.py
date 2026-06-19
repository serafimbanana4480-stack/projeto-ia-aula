"""Tests for backend.agents.researcher_web."""

from __future__ import annotations

from backend.agents.base import AgentAction
from backend.agents.researcher_web import ResearcherWebAgent


class TestResearcherWebAgent:
    def test_metadata(self) -> None:
        agent = ResearcherWebAgent()
        assert agent.name == "RESEARCHER_WEB"
        assert agent.model_key == "coder"
        assert agent.prompt_file == "researcher_web"

    def test_supported_actions(self) -> None:
        agent = ResearcherWebAgent()
        expected = {
            AgentAction.SEARCH_WEB,
            AgentAction.FETCH_URL,
            AgentAction.ANALYZE_DATA,
            AgentAction.CONSULT_AGENT,
            AgentAction.GENERATE_REPORT,
            AgentAction.SEARCH_GITHUB,
            AgentAction.SEARCH_DOCS,
            AgentAction.DEEP_RESEARCH,
        }
        assert agent.supported_actions == expected

    def test_has_execute_method(self) -> None:
        agent = ResearcherWebAgent()
        assert hasattr(agent, "_execute")
        assert callable(agent._execute)
