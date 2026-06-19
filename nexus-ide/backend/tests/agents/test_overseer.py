"""Tests for OverseerAgent."""

from __future__ import annotations

import time

import pytest

from backend.agents.base import AgentAction
from backend.agents.overseer import OverseerAgent


@pytest.fixture
def overseer():
    return OverseerAgent()


class TestOverseerMetadata:
    def test_name(self, overseer):
        assert overseer.name == "OVERSEER"

    def test_model_key(self, overseer):
        assert overseer.model_key == "reasoning"

    def test_prompt_file(self, overseer):
        assert overseer.prompt_file == "overseer"

    def test_supported_actions(self, overseer):
        assert overseer.supported_actions == {
            AgentAction.READ_FILE,
            AgentAction.SEARCH_CODEBASE,
            AgentAction.CONSULT_AGENT,
            AgentAction.RECALL_CONTEXT,
        }


class TestOverseerHealthTracking:
    @pytest.mark.asyncio
    async def test_record_agent_event(self, overseer):
        await overseer.record_agent_event("CODER", "agent_started", {"task": "write tests"})
        status = overseer.get_agent_status("CODER")
        assert status is not None
        assert status["status"] == "running"
        assert status["task"] == "write tests"

    @pytest.mark.asyncio
    async def test_record_iteration_and_tokens(self, overseer):
        await overseer.record_agent_event(
            "CODER", "iteration", {"iteration": 3, "tokens_used": 1500}
        )
        status = overseer.get_agent_status("CODER")
        assert status["iteration"] == 3
        assert status["tokens_used"] == 1500

    @pytest.mark.asyncio
    async def test_detect_conflicts(self, overseer):
        await overseer.record_agent_event("CODER", "file_locked", {"path": "/src/main.py"})
        await overseer.record_agent_event("DEBUGGER", "iteration", {"current_file": "/src/main.py"})
        dashboard = overseer.get_dashboard()
        conflicts = dashboard["file_conflicts"]
        assert len(conflicts) == 1
        assert conflicts[0]["file"] == "/src/main.py"
        assert sorted(conflicts[0]["agents"]) == ["CODER", "DEBUGGER"]

    @pytest.mark.asyncio
    async def test_detect_stuck(self, overseer):
        await overseer.record_agent_event("CODER", "agent_started", {})
        # Manually set blocked_since and status to simulate stuck detection
        overseer._health["CODER"].status = "stuck"
        overseer._health["CODER"].blocked_since = time.time()
        stuck = overseer.get_dashboard()["stuck_agents"]
        assert len(stuck) == 1
        assert stuck[0]["agent"] == "CODER"

    @pytest.mark.asyncio
    async def test_error_loop(self, overseer):
        for _ in range(3):
            await overseer.record_agent_event("CODER", "agent_failed", {})
        status = overseer.get_agent_status("CODER")
        assert status["status"] == "stuck"
        assert status["failure_count"] == 3


class TestOverseerIntervention:
    @pytest.mark.asyncio
    async def test_pause_resume(self, overseer):
        await overseer.record_agent_event("CODER", "agent_started", {})
        result = await overseer.intervene("CODER", "pause", "too hot")
        assert result["success"] is True
        assert result["current_status"] == "paused"
        result = await overseer.intervene("CODER", "resume", "")
        assert result["current_status"] == "running"

    @pytest.mark.asyncio
    async def test_abort(self, overseer):
        await overseer.record_agent_event("CODER", "agent_started", {})
        result = await overseer.intervene("CODER", "abort", "infinite loop")
        assert result["success"] is True
        assert result["current_status"] == "error"

    @pytest.mark.asyncio
    async def test_intervene_unknown_agent(self, overseer):
        result = await overseer.intervene("UNKNOWN", "pause")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_intervene_invalid_action(self, overseer):
        await overseer.record_agent_event("CODER", "agent_started", {})
        result = await overseer.intervene("CODER", "dance")
        assert "error" in result


class TestOverseerQualityGates:
    def test_no_review(self, overseer):
        result = overseer.check_quality_gate("CODER", "/src/main.py")
        assert result["passed"] is False

    def test_review_passed(self, overseer):
        overseer.record_review("/src/main.py", "ANALYZER", True)
        result = overseer.check_quality_gate("CODER", "/src/main.py")
        assert result["passed"] is True
        assert result["reviewer"] == "ANALYZER"

    def test_review_failed(self, overseer):
        overseer.record_review("/src/main.py", "ANALYZER", False)
        result = overseer.check_quality_gate("CODER", "/src/main.py")
        assert result["passed"] is False


class TestOverseerMissions:
    def test_start_and_update(self, overseer):
        overseer.start_mission("m1", "Refactor auth", ["CODER", "ANALYZER"])
        dashboard = overseer.get_dashboard()
        missions = dashboard["missions"]
        assert len(missions) == 1
        assert missions[0]["name"] == "Refactor auth"

        result = overseer.update_mission("m1", status="completed")
        assert result["success"] is True
        assert overseer.get_dashboard()["missions"][0]["status"] == "completed"

    def test_update_add_blocker(self, overseer):
        overseer.start_mission("m1", "Fix bug", ["DEBUGGER"])
        overseer.update_mission("m1", blocker="Missing test data")
        mission = overseer.get_dashboard()["missions"][0]
        assert "Missing test data" in mission["blockers"]

    def test_update_unknown_mission(self, overseer):
        result = overseer.update_mission("unknown", status="completed")
        assert "error" in result


class TestOverseerDashboard:
    @pytest.mark.asyncio
    async def test_dashboard_structure(self, overseer):
        await overseer.record_agent_event("CODER", "agent_started", {})
        dashboard = overseer.get_dashboard()
        assert "timestamp" in dashboard
        assert "agents" in dashboard
        assert "file_conflicts" in dashboard
        assert "stuck_agents" in dashboard
        assert "missions" in dashboard
        assert "interventions" in dashboard
        assert "CODER" in dashboard["agents"]


class TestTokenBudget:
    @pytest.mark.asyncio
    async def test_default_budget(self, overseer):
        await overseer.record_agent_event("CODER", "iteration", {"tokens_used": 500})
        status = overseer.get_agent_status("CODER")
        assert status["token_budget"] == 100_000
        assert status["budget_remaining"] == 99_500

    @pytest.mark.asyncio
    async def test_custom_budget(self, overseer):
        await overseer.set_token_budget("CODER", 10_000)
        await overseer.record_agent_event("CODER", "iteration", {"tokens_used": 500})
        status = overseer.get_agent_status("CODER")
        assert status["token_budget"] == 10_000
        assert status["budget_remaining"] == 9_500
