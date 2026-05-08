"""Tests for backend.agents.analyzer."""
from __future__ import annotations

from backend.agents.analyzer import AnalyzerAgent


class TestAnalyzerAgent:
    def test_metadata(self) -> None:
        agent = AnalyzerAgent()
        assert agent.name == "ANALYZER"
        assert agent.model_key == "large"
        assert agent.prompt_file == "analyzer"
