"""Tests for AI Team agents."""
from __future__ import annotations

import pytest

from backend.agents.ai_team.ml_engineer_agent import MLEngineerAgent
from backend.agents.ai_team.data_scientist_agent import DataScientistAgent
from backend.agents.ai_team.prompt_engineer_agent import PromptEngineerAgent
from backend.agents.ai_team.team_lead import AITeamLead


class TestMLEngineerAgent:
    def test_suggest_architecture(self) -> None:
        agent = MLEngineerAgent()
        result = agent.suggest_architecture("classification")
        assert "models" in result
        assert "metrics" in result
        assert len(result["models"]) > 0

    def test_suggest_unknown(self) -> None:
        agent = MLEngineerAgent()
        result = agent.suggest_architecture("unknown")
        assert "models" in result


class TestDataScientistAgent:
    def test_analyze_dataset(self) -> None:
        agent = DataScientistAgent()
        schema = {"age": "int", "name": "str", "salary": "float"}
        result = agent.analyze_dataset(schema)
        assert "numeric_columns" in result
        assert "categorical_columns" in result
        assert "age" in result["numeric_columns"]
        assert "name" in result["categorical_columns"]


class TestPromptEngineerAgent:
    def test_evaluate_good_prompt(self) -> None:
        agent = PromptEngineerAgent()
        prompt = "You are an expert. Analyze this data step by step. Return JSON. Example: {\"result\": true}"
        result = agent.evaluate_prompt(prompt)
        assert result["score"] > 50

    def test_evaluate_bad_prompt(self) -> None:
        agent = PromptEngineerAgent()
        result = agent.evaluate_prompt("do it")
        assert result["score"] < 50
        assert len(result["issues"]) > 0


class TestAITeamLead:
    def test_team_status(self) -> None:
        lead = AITeamLead()
        status = lead.get_team_status()
        assert status["team"] == "ai"
        assert len(status["members"]) == 3
        assert "ML_ENGINEER" in status["members"]
