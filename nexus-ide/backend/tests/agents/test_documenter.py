"""Tests for backend.agents.documenter."""
from __future__ import annotations

from backend.agents.documenter import DocumenterAgent


class TestDocumenterAgent:
    def test_metadata(self) -> None:
        agent = DocumenterAgent()
        assert agent.name == "DOCUMENTER"
        assert agent.model_key == "small"
        assert agent.prompt_file == "documenter"
