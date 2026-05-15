"""Tests for backend.agents.architect."""

from __future__ import annotations

from backend.agents.architect import ArchitectAgent


class TestArchitectAgent:
    def test_metadata(self) -> None:
        agent = ArchitectAgent()
        assert agent.name == "ARCHITECT"
        assert agent.model_key == "reasoning"
        assert agent.prompt_file == "architect"
