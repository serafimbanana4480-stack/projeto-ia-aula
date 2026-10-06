"""End-to-end tests for AI agent responses."""
from __future__ import annotations

import pytest

from backend.agents.ai_team.ml_engineer_agent import MLEngineerAgent
from backend.agents.ai_team.prompt_engineer_agent import PromptEngineerAgent
from backend.agents.base import AgentRequest
from backend.agents.frontend.component_agent import ComponentAgent
from backend.agents.frontend.state_manager_agent import StateManagerAgent
from backend.agents.frontend.uiux_agent import UIUXAgent
from backend.config.settings import get_settings
from backend.tools.ollama_client import OllamaClient


def _make_request(query: str) -> AgentRequest:
    return AgentRequest(
        session_id="test-session",
        query=query,
        client=OllamaClient(get_settings().ollama_host),
    )


class TestAIResponses:
    @pytest.mark.asyncio
    async def test_uiux_agent_review_response(self):
        agent = UIUXAgent()
        request = _make_request("review accessibility")
        chunks = [chunk async for chunk in agent.run(request)]
        text = "".join(chunks)
        assert "UI/UX Review" in text
        assert "Accessibility" in text

    @pytest.mark.asyncio
    async def test_uiux_agent_design_response(self):
        agent = UIUXAgent()
        request = _make_request("design a landing page")
        chunks = [chunk async for chunk in agent.run(request)]
        text = "".join(chunks)
        assert "Design Proposal" in text
        assert "Color Palette" in text

    @pytest.mark.asyncio
    async def test_component_agent_generates_template(self):
        agent = ComponentAgent()
        request = _make_request("generate a Navbar component")
        chunks = [chunk async for chunk in agent.run(request)]
        text = "".join(chunks)
        assert "Navbar" in text
        assert "tsx" in text

    def test_component_agent_analyze(self):
        agent = ComponentAgent()
        code = """
import React from "react";
export function Button(props) {
  return <button>{props.label}</button>;
}
"""
        result = agent.analyze_component(code)
        assert result["lines"] > 0
        assert "hooks_used" in result

    @pytest.mark.asyncio
    async def test_state_manager_zustand_response(self):
        agent = StateManagerAgent()
        request = _make_request("how to use zustand")
        chunks = [chunk async for chunk in agent.run(request)]
        text = "".join(chunks)
        assert "Zustand" in text
        assert "create" in text

    @pytest.mark.asyncio
    async def test_ml_engineer_architecture_response(self):
        agent = MLEngineerAgent()
        request = _make_request("train a classification model")
        chunks = [chunk async for chunk in agent.run(request)]
        text = "".join(chunks)
        assert "ML Model Development" in text
        assert "Pipeline" in text

    def test_ml_engineer_suggest_architecture(self):
        agent = MLEngineerAgent()
        result = agent.suggest_architecture("classification")
        assert "Random Forest" in result["models"]
        assert "accuracy" in result["metrics"]

    def test_prompt_engineer_evaluate_good(self):
        agent = PromptEngineerAgent()
        prompt = "You are an expert. Analyze this data step by step. Return JSON. Example: {\"result\": true}"
        result = agent.evaluate_prompt(prompt)
        assert result["score"] > 50
        assert len(result["strengths"]) >= 3

    def test_prompt_engineer_evaluate_bad(self):
        agent = PromptEngineerAgent()
        result = agent.evaluate_prompt("do it")
        assert result["score"] < 50
        assert len(result["issues"]) > 0
