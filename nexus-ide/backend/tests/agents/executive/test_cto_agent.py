"""Tests for CTO Agent and technology executive components."""
from __future__ import annotations

import time

import pytest

from backend.agents.base import AgentRequest
from backend.agents.executive.architecture_decision_maker import (
    ADRStatus,
    ArchitectureDecisionMaker,
    ArchitectureDecisionRecord,
)
from backend.agents.executive.cto_agent import CTOAgent
from backend.agents.executive.stack_selector import StackSelection, StackSelector
from backend.agents.executive.technical_debt_manager import (
    DebtItem,
    Severity,
    TechnicalDebtManager,
)
from backend.agents.executive.technical_roadmapper import (
    Milestone,
    MilestoneStatus,
    TechnicalRoadmapper,
)
from backend.agents.executive.technology_strategist import (
    CRITERIA,
    StackScore,
    TechnologyStrategist,
)
from backend.tools.ollama_client import OllamaClient


class TestTechnologyStrategist:
    def test_evaluate_stack(self) -> None:
        ts = TechnologyStrategist()
        stack = ts.evaluate_stack(
            "FastAPI + PostgreSQL",
            {"performance": 0.9, "scalability": 0.8, "security": 0.85},
        )
        assert isinstance(stack, StackScore)
        assert stack.name == "FastAPI + PostgreSQL"
        assert stack.overall > 0.0
        assert stack.stack_id.startswith("stack-")
        for c in CRITERIA:
            assert c in stack.scores

    def test_get_recommendation(self) -> None:
        ts = TechnologyStrategist()
        ts.evaluate_stack("Stack A", {"performance": 0.9, "scalability": 0.5})
        ts.evaluate_stack("Stack B", {"performance": 0.6, "scalability": 0.9})
        results = ts.get_recommendation({"performance": 1.0})
        assert len(results) == 2
        assert results[0].name == "Stack A"

    def test_list_stacks(self) -> None:
        ts = TechnologyStrategist()
        ts.evaluate_stack("S1", {"performance": 0.5})
        ts.evaluate_stack("S2", {"performance": 0.9})
        stacks = ts.list_stacks()
        assert len(stacks) == 2
        assert stacks[0].name == "S2"  # highest overall first

    def test_remove_stack(self) -> None:
        ts = TechnologyStrategist()
        stack = ts.evaluate_stack("ToRemove", {"performance": 0.5})
        assert ts.remove_stack(stack.stack_id)
        assert ts.get_stack(stack.stack_id) is None

    def test_stats(self) -> None:
        ts = TechnologyStrategist()
        assert ts.stats()["total_stacks"] == 0
        ts.evaluate_stack("S1", {"performance": 0.8, "scalability": 0.6})
        stats = ts.stats()
        assert stats["total_stacks"] == 1
        assert stats["avg_overall"] > 0.0
        assert "avg_by_criterion" in stats


class TestArchitectureDecisionMaker:
    def test_record_decision(self) -> None:
        adm = ArchitectureDecisionMaker()
        adr = adm.record_decision(
            title="Use FastAPI",
            context="Need async web framework",
            decision="Adopt FastAPI",
            consequences="Team needs to learn async patterns",
            status="proposed",
        )
        assert isinstance(adr, ArchitectureDecisionRecord)
        assert adr.title == "Use FastAPI"
        assert adr.status == ADRStatus.PROPOSED
        assert adr.adr_id.startswith("adr-")

    def test_get_decisions_filter(self) -> None:
        adm = ArchitectureDecisionMaker()
        adm.record_decision("A", "ctx", "dec", "cons", "accepted")
        adm.record_decision("B", "ctx", "dec", "cons", "rejected")
        all_decisions = adm.get_decisions()
        assert len(all_decisions) == 2
        accepted = adm.get_decisions(status="accepted")
        assert len(accepted) == 1
        assert accepted[0].title == "A"

    def test_update_status(self) -> None:
        adm = ArchitectureDecisionMaker()
        adr = adm.record_decision("A", "ctx", "dec", "cons", "proposed")
        updated = adm.update_status(adr.adr_id, "accepted")
        assert updated is not None
        assert updated.status == ADRStatus.ACCEPTED
        assert adm.update_status("nonexistent", "accepted") is None

    def test_invalid_status_defaults(self) -> None:
        adm = ArchitectureDecisionMaker()
        adr = adm.record_decision("A", "ctx", "dec", "cons", status="invalid")
        assert adr.status == ADRStatus.PROPOSED
        assert adm.update_status(adr.adr_id, "bad_status") is None

    def test_get_stats(self) -> None:
        adm = ArchitectureDecisionMaker()
        adm.record_decision("A", "ctx", "dec", "cons", "accepted")
        adm.record_decision("B", "ctx", "dec", "cons", "proposed")
        stats = adm.get_stats()
        assert stats["total"] == 2
        assert stats["by_status"]["accepted"] == 1
        assert stats["by_status"]["proposed"] == 1
        assert stats["accepted_rate"] == 0.5


class TestTechnicalRoadmapper:
    def test_add_milestone(self) -> None:
        tr = TechnicalRoadmapper()
        ms = tr.add_milestone(
            name="MVP",
            target_date=time.time() + 86400,
            deliverables=["API", "UI"],
        )
        assert isinstance(ms, Milestone)
        assert ms.name == "MVP"
        assert ms.milestone_id.startswith("ms-")
        assert ms.status == MilestoneStatus.PLANNED

    def test_get_timeline(self) -> None:
        tr = TechnicalRoadmapper()
        tr.add_milestone("Late", time.time() + 86400 * 2, ["D2"])
        tr.add_milestone("Early", time.time() + 86400, ["D1"])
        timeline = tr.get_timeline()
        assert timeline[0].name == "Early"
        assert timeline[1].name == "Late"

    def test_get_critical_path(self) -> None:
        tr = TechnicalRoadmapper()
        ms1 = tr.add_milestone("A", time.time() + 86400, ["D1"])
        ms2 = tr.add_milestone("B", time.time() + 172800, ["D2"], dependencies=[ms1.milestone_id])
        path = tr.get_critical_path()
        assert len(path) == 2
        ids = [m.milestone_id for m in path]
        assert ms1.milestone_id in ids
        assert ms2.milestone_id in ids

    def test_update_progress(self) -> None:
        tr = TechnicalRoadmapper()
        ms = tr.add_milestone("A", time.time() + 86400, ["D1"])
        updated = tr.update_progress(ms.milestone_id, 0.5)
        assert updated is not None
        assert updated.progress == 0.5
        assert updated.status == MilestoneStatus.IN_PROGRESS
        completed = tr.update_progress(ms.milestone_id, 1.0)
        assert completed is not None
        assert completed.status == MilestoneStatus.COMPLETED

    def test_update_status(self) -> None:
        tr = TechnicalRoadmapper()
        ms = tr.add_milestone("A", time.time() + 86400, ["D1"])
        updated = tr.update_status(ms.milestone_id, "blocked")
        assert updated is not None
        assert updated.status == MilestoneStatus.BLOCKED

    def test_stats(self) -> None:
        tr = TechnicalRoadmapper()
        tr.add_milestone("A", time.time() + 86400, ["D1"])
        ms2 = tr.add_milestone("B", time.time() + 172800, ["D2"])
        tr.update_progress(ms2.milestone_id, 1.0)
        stats = tr.stats()
        assert stats["total"] == 2
        assert stats["by_status"]["completed"] == 1
        assert stats["by_status"]["planned"] == 1
        assert stats["completion_rate"] == 0.5


class TestStackSelector:
    def test_select_stack(self) -> None:
        ts = TechnologyStrategist()
        ts.evaluate_stack("FastAPI", {"performance": 0.9, "scalability": 0.8})
        selector = StackSelector(ts)
        sel = selector.select_stack({"weights": {"performance": 1.0}})
        assert isinstance(sel, StackSelection)
        assert sel.chosen_name == "FastAPI"
        assert sel.selection_id.startswith("sel-")

    def test_select_stack_empty(self) -> None:
        selector = StackSelector()
        assert selector.select_stack({}) is None

    def test_compare_stacks(self) -> None:
        ts = TechnologyStrategist()
        ts.evaluate_stack("FastAPI", {"performance": 0.9})
        ts.evaluate_stack("Django", {"performance": 0.7})
        selector = StackSelector(ts)
        result = selector.compare_stacks(["FastAPI", "Django"])
        assert "best_overall" in result
        assert len(result["comparisons"]) == 2

    def test_compare_stacks_no_match(self) -> None:
        selector = StackSelector()
        result = selector.compare_stacks(["Unknown"])
        assert "error" in result

    def test_get_selection_history(self) -> None:
        ts = TechnologyStrategist()
        ts.evaluate_stack("A", {"performance": 0.5})
        selector = StackSelector(ts)
        selector.select_stack({"weights": {"performance": 1.0}})
        history = selector.get_selection_history()
        assert len(history) == 1

    def test_stats(self) -> None:
        ts = TechnologyStrategist()
        ts.evaluate_stack("A", {"performance": 0.5})
        selector = StackSelector(ts)
        selector.select_stack({"weights": {"performance": 1.0}})
        stats = selector.stats()
        assert stats["total_selections"] == 1
        assert stats["unique_stacks_selected"] == 1


class TestTechnicalDebtManager:
    def test_record_debt(self) -> None:
        tdm = TechnicalDebtManager()
        debt = tdm.record_debt(
            description="Refactor monolith",
            severity="high",
            location="src/legacy",
            estimated_effort=16.0,
        )
        assert isinstance(debt, DebtItem)
        assert debt.severity == Severity.HIGH
        assert debt.debt_id.startswith("debt-")

    def test_invalid_severity_defaults(self) -> None:
        tdm = TechnicalDebtManager()
        debt = tdm.record_debt("Bad code", "invalid", "src", 2.0)
        assert debt.severity == Severity.MEDIUM

    def test_get_debt_queue(self) -> None:
        tdm = TechnicalDebtManager()
        tdm.record_debt("A", "medium", "src", 2.0)
        tdm.record_debt("B", "critical", "src", 4.0)
        tdm.record_debt("C", "low", "src", 1.0)
        queue = tdm.get_debt_queue()
        assert queue[0].severity == Severity.CRITICAL
        assert queue[1].severity == Severity.MEDIUM
        assert queue[2].severity == Severity.LOW

    def test_pay_debt(self) -> None:
        tdm = TechnicalDebtManager()
        debt = tdm.record_debt("A", "high", "src", 2.0)
        paid = tdm.pay_debt(debt.debt_id)
        assert paid is not None
        assert paid.status == "resolved"
        assert paid.resolved_at is not None
        assert tdm.pay_debt("nonexistent") is None

    def test_update_debt(self) -> None:
        tdm = TechnicalDebtManager()
        debt = tdm.record_debt("A", "medium", "src", 2.0)
        updated = tdm.update_debt(debt.debt_id, severity="critical", estimated_effort=8.0)
        assert updated is not None
        assert updated.severity == Severity.CRITICAL
        assert updated.estimated_effort == 8.0
        assert tdm.update_debt("nonexistent", severity="high") is None

    def test_get_stats(self) -> None:
        tdm = TechnicalDebtManager()
        tdm.record_debt("A", "high", "src", 4.0)
        tdm.record_debt("B", "low", "src", 2.0)
        tdm.pay_debt(tdm.record_debt("C", "medium", "src", 1.0).debt_id)
        stats = tdm.get_stats()
        assert stats["total"] == 3
        assert stats["open"] == 2
        assert stats["resolved"] == 1
        assert stats["total_estimated_effort_open"] == 6.0
        assert stats["by_severity"]["high"] == 1


class TestCTOAgent:
    def test_dashboard(self) -> None:
        cto = CTOAgent()
        dashboard = cto.get_dashboard()
        assert "stacks" in dashboard
        assert "adrs" in dashboard
        assert "roadmap" in dashboard
        assert "stack_selections" in dashboard
        assert "technical_debt" in dashboard

    def test_system_prompt_loads(self) -> None:
        cto = CTOAgent()
        prompt = cto.system_prompt()
        assert "CTO" in prompt
        assert "Technology Officer" in prompt

    def test_init_with_custom_components(self) -> None:
        ts = TechnologyStrategist()
        adm = ArchitectureDecisionMaker()
        tr = TechnicalRoadmapper()
        ss = StackSelector(ts)
        tdm = TechnicalDebtManager()
        cto = CTOAgent(ts, adm, tr, ss, tdm)
        assert cto._strategist is ts
        assert cto._adr_maker is adm
        assert cto._roadmapper is tr
        assert cto._stack_selector is ss
        assert cto._debt_manager is tdm

    @pytest.mark.asyncio
    async def test_run_stack_handler(self, ollama_client: OllamaClient) -> None:
        cto = CTOAgent()
        cto._strategist.evaluate_stack("FastAPI", {"performance": 0.9})
        request = AgentRequest(
            session_id="test",
            query="What is the best technology stack?",
            client=ollama_client,
        )
        chunks = [c async for c in cto.run(request)]
        text = "".join(chunks)
        assert "Technology Stack Analysis" in text
        assert "FastAPI" in text

    @pytest.mark.asyncio
    async def test_run_architecture_handler(self, ollama_client: OllamaClient) -> None:
        cto = CTOAgent()
        request = AgentRequest(
            session_id="test",
            query="Show architecture decisions",
            client=ollama_client,
        )
        chunks = [c async for c in cto.run(request)]
        text = "".join(chunks)
        assert "Architecture Decision Records" in text

    @pytest.mark.asyncio
    async def test_run_roadmap_handler(self, ollama_client: OllamaClient) -> None:
        cto = CTOAgent()
        cto._roadmapper.add_milestone("MVP", time.time() + 86400, ["API"])
        request = AgentRequest(
            session_id="test",
            query="What is the roadmap?",
            client=ollama_client,
        )
        chunks = [c async for c in cto.run(request)]
        text = "".join(chunks)
        assert "Technical Roadmap" in text

    @pytest.mark.asyncio
    async def test_run_debt_handler(self, ollama_client: OllamaClient) -> None:
        cto = CTOAgent()
        cto._debt_manager.record_debt("Legacy code", "high", "src", 8.0)
        request = AgentRequest(
            session_id="test",
            query="Show technical debt",
            client=ollama_client,
        )
        chunks = [c async for c in cto.run(request)]
        text = "".join(chunks)
        assert "Technical Debt Register" in text

    @pytest.mark.asyncio
    async def test_run_general_handler(self, ollama_client: OllamaClient) -> None:
        cto = CTOAgent()
        request = AgentRequest(
            session_id="test",
            query="Give me a strategy overview",
            client=ollama_client,
        )
        chunks = [c async for c in cto.run(request)]
        text = "".join(chunks)
        assert "Technical Strategy Overview" in text
