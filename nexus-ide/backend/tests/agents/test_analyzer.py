"""Tests for backend.agents.analyzer."""

from __future__ import annotations

from backend.agents.analyzer import AnalyzerAgent
from backend.agents.base import AgentAction


class TestAnalyzerAgent:
    def test_metadata(self) -> None:
        agent = AnalyzerAgent()
        assert agent.name == "ANALYZER"
        assert agent.model_key == "reasoning"
        assert agent.prompt_file == "analyzer"

    def test_supported_actions(self) -> None:
        agent = AnalyzerAgent()
        expected = {
            AgentAction.READ_FILE,
            AgentAction.READ_FILE_ABSOLUTE,
            AgentAction.LIST_DIR,
            AgentAction.SEARCH_CODEBASE,
            AgentAction.SEARCH_SYMBOLS,
            AgentAction.INDEX_SYMBOLS,
            AgentAction.READ_DOCS,
            AgentAction.ANALYZE_DATA,
            AgentAction.CONSULT_AGENT,
            AgentAction.RECALL_CONTEXT,
            AgentAction.STORE_MEMORY,
            AgentAction.EXECUTE_CODE,
        }
        assert agent.supported_actions == expected
