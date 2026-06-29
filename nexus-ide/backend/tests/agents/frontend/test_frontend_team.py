"""Tests for Frontend Team agents."""
from __future__ import annotations

import pytest

from backend.agents.frontend.uiux_agent import UIUXAgent
from backend.agents.frontend.component_agent import ComponentAgent
from backend.agents.frontend.state_manager_agent import StateManagerAgent
from backend.agents.frontend.team_lead import FrontendTeamLead


class TestUIUXAgent:
    def test_review_component(self) -> None:
        agent = UIUXAgent()
        result = agent.review_component('<div className="p-4">Hello</div>')
        assert "score" in result
        assert isinstance(result["issues"], list)

    def test_review_accessible_component(self) -> None:
        agent = UIUXAgent()
        code = '<button aria-label="Close" className="p-2">X</button>'
        result = agent.review_component(code)
        assert result["passed"] or any("ARIA" in i for i in result["issues"])


class TestComponentAgent:
    def test_analyze_component(self) -> None:
        agent = ComponentAgent()
        code = """
import React from "react";
export function Button(props) {
  return <button>{props.label}</button>;
}
"""
        result = agent.analyze_component(code)
        assert "lines" in result
        assert "hooks_used" in result

    def test_generate_template(self) -> None:
        agent = ComponentAgent()
        template = agent._generate_component_template("Create a Navbar component")
        assert "Navbar" in template
        assert "tsx" in template


class TestStateManagerAgent:
    def test_zustand_template(self) -> None:
        agent = StateManagerAgent()
        template = agent._zustand_template()
        assert "zustand" in template.lower()
        assert "create" in template


class TestFrontendTeamLead:
    def test_team_status(self) -> None:
        lead = FrontendTeamLead()
        status = lead.get_team_status()
        assert status["team"] == "frontend"
        assert len(status["members"]) == 3
        assert "UIUX" in status["members"]
