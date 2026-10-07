"""Tests for CEO Agent and executive components."""
from __future__ import annotations

import tempfile
from pathlib import Path

from backend.agents.executive.ceo_agent import CEOAgent
from backend.agents.executive.goal_hierarchy import GoalHierarchy, GoalPriority, GoalStatus
from backend.agents.executive.priority_manager import PriorityLevel, PriorityManager
from backend.agents.executive.resource_allocator import ResourceAllocator
from backend.agents.executive.strategic_memory import StrategicDecision, StrategicMemory
from backend.agents.executive.vision_aligner import VisionAligner


class TestStrategicMemory:
    def test_set_and_get_vision(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            mem = StrategicMemory(path=Path(f.name))
            mem.set_vision("Build the best AI platform")
            assert mem.vision == "Build the best AI platform"

    def test_record_and_retrieve_decision(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            mem = StrategicMemory(path=Path(f.name))
            d = mem.record_decision(
                context="Should we expand to Europe?",
                options=["yes", "no"],
                chosen="yes",
                reasoning="Market opportunity",
                confidence=0.85,
            )
            assert isinstance(d, StrategicDecision)
            assert d.chosen == "yes"
            assert d.confidence == 0.85
            decisions = mem.get_decisions()
            assert len(decisions) == 1

    def test_find_similar(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            mem = StrategicMemory(path=Path(f.name))
            mem.record_decision(
                context="Expand to European market",
                options=["yes", "no"],
                chosen="yes",
                reasoning="Market growth",
                confidence=0.9,
            )
            similar = mem.find_similar("European expansion strategy", top_k=1)
            assert len(similar) == 1

    def test_stats(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            mem = StrategicMemory(path=Path(f.name))
            assert mem.stats()["total_decisions"] == 0
            mem.record_decision(
                context="test", options=["a"], chosen="a",
                reasoning="test", confidence=0.9,
            )
            stats = mem.stats()
            assert stats["total_decisions"] == 1
            assert stats["avg_confidence"] == 0.9


class TestGoalHierarchy:
    def test_create_and_get_goal(self) -> None:
        gh = GoalHierarchy()
        goal = gh.create_goal("Build API", "Create REST API", GoalPriority.HIGH)
        assert goal.title == "Build API"
        assert goal.priority == GoalPriority.HIGH
        assert gh.get_goal(goal.goal_id) == goal

    def test_subgoals(self) -> None:
        gh = GoalHierarchy()
        parent = gh.create_goal("Parent", "Parent goal")
        child = gh.create_goal("Child", "Child goal", parent_id=parent.goal_id)
        assert child.parent_id == parent.goal_id
        assert child.goal_id in parent.subgoals

    def test_complete_updates_parent(self) -> None:
        gh = GoalHierarchy()
        parent = gh.create_goal("Parent", "Parent goal")
        child = gh.create_goal("Child", "Child goal", parent_id=parent.goal_id)
        gh.start_goal(child.goal_id)
        gh.complete_goal(child.goal_id)
        assert parent.progress == 1.0
        assert parent.status == GoalStatus.COMPLETED

    def test_delete_recursive(self) -> None:
        gh = GoalHierarchy()
        parent = gh.create_goal("Parent", "Parent goal")
        child = gh.create_goal("Child", "Child goal", parent_id=parent.goal_id)
        assert gh.delete_goal(parent.goal_id)
        assert gh.get_goal(parent.goal_id) is None
        assert gh.get_goal(child.goal_id) is None

    def test_stats(self) -> None:
        gh = GoalHierarchy()
        gh.create_goal("G1", "Goal 1")
        gh.create_goal("G2", "Goal 2")
        stats = gh.stats()
        assert stats["total"] == 2
        assert stats["root_goals"] == 2


class TestResourceAllocator:
    def test_register_and_allocate(self) -> None:
        ra = ResourceAllocator()
        ra.register_agent("a1", "Coder", ["code", "python"])
        agent = ra.allocate(["code"])
        assert agent is not None
        assert agent.name == "Coder"

    def test_allocate_none_available(self) -> None:
        ra = ResourceAllocator()
        agent = ra.allocate(["design"])
        assert agent is None

    def test_allocate_prefers_healthy(self) -> None:
        ra = ResourceAllocator()
        ra.register_agent("a1", "Healthy", ["code"])
        ra.register_agent("a2", "Sick", ["code"])
        ra.update_health("a2", "unhealthy")
        agent = ra.allocate(["code"])
        assert agent.name == "Healthy"

    def test_stats(self) -> None:
        ra = ResourceAllocator()
        ra.register_agent("a1", "Agent1", ["code"])
        stats = ra.stats()
        assert stats["total_agents"] == 1
        assert stats["healthy"] == 1


class TestPriorityManager:
    def test_add_and_queue(self) -> None:
        pm = PriorityManager()
        pm.add_item("i1", "Task A", PriorityLevel.MEDIUM)
        pm.add_item("i2", "Task B", PriorityLevel.HIGH)
        queue = pm.get_queue()
        assert len(queue) == 2
        assert queue[0].title == "Task B"  # HIGH before MEDIUM

    def test_escalate(self) -> None:
        pm = PriorityManager()
        pm.add_item("i1", "Task", PriorityLevel.MEDIUM)
        pm.escalate("i1")
        item = pm.get_queue()[0]
        assert item.base_priority == PriorityLevel.HIGH

    def test_auto_escalate(self) -> None:
        pm = PriorityManager()
        import time
        pm.add_item("i1", "Old Task", PriorityLevel.LOW)
        # Manually set created_at to past
        pm._items["i1"].created_at = time.time() - 100000
        escalated = pm.auto_escalate(stale_hours=1)
        assert len(escalated) == 1


class TestVisionAligner:
    def test_aligned_action(self) -> None:
        va = VisionAligner("Build secure AI systems")
        result = va.check_alignment("Implement security audit for AI pipeline")
        assert result.aligned
        assert result.score > 0.5

    def test_anti_pattern(self) -> None:
        va = VisionAligner("Build secure AI systems")
        result = va.check_alignment("Bypass security for quick deployment")
        assert not result.aligned
        assert len(result.violations) > 0

    def test_suggest_improvements(self) -> None:
        va = VisionAligner("Build secure AI systems")
        suggestions = va.suggest_improvements("Create a database")
        assert len(suggestions) > 0


class TestCEOAgent:
    def test_dashboard(self) -> None:
        ceo = CEOAgent()
        dashboard = ceo.get_dashboard()
        assert "vision" in dashboard
        assert "goals" in dashboard
        assert "priorities" in dashboard
        assert "resources" in dashboard

    def test_set_company_vision(self) -> None:
        ceo = CEOAgent()
        ceo.set_company_vision("Build the best AI", ["innovation", "quality"])
        assert ceo._memory.vision == "Build the best AI"
        assert "innovation" in ceo._vision._values
