"""Tests for backend.agents.optimizer."""

from __future__ import annotations

from backend.agents.optimizer import OptimizerAgent


class TestOptimizerAgent:
    def test_metadata(self) -> None:
        agent = OptimizerAgent()
        assert agent.name == "OPTIMIZER"
        assert agent.model_key == "small"
        assert agent.prompt_file == "optimizer"
