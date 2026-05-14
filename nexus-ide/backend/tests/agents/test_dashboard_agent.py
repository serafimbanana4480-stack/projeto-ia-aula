"""Tests for backend.agents.dashboard_agent."""

from __future__ import annotations

from backend.agents.dashboard_agent import DashboardAgent


class TestDashboardAgent:
    def test_metadata(self) -> None:
        agent = DashboardAgent()
        assert agent.name == "DASHBOARD"
        assert agent.model_key == "dashboard"
        assert agent.prompt_file == "dashboard"
        assert agent.supported_actions == set()
