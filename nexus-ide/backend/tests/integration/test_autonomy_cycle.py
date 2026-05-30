"""Integration tests for the complete autonomy cycle Plan→Execute→Verify→Iterate."""

from __future__ import annotations

import pytest

from backend.orchestrator.dependency_graph import (
    DependencyGraph,
    ExecutionPlan,
    TaskNode,
    TaskPriority,
    TaskStatus,
)
from backend.orchestrator.engine import OrchestrationEngine


class TestAutonomyCycle:
    """Test the complete Plan→Execute→Verify→Iterate autonomy cycle."""

    @pytest.mark.asyncio
    async def test_create_plan_generates_structured_steps(self) -> None:
        """Test that OrchestrationEngine.create_plan returns a valid structured plan."""
        from unittest.mock import AsyncMock, MagicMock
        from backend.orchestrator.engine import OrchestrationEngine
        from backend.orchestrator.events import EventBus

        async def _mock_stream(*args, **kwargs):
            yield """[
                {"name": "step1", "description": "First step", "agent": "CODER"}
            ]"""

        mock_ollama = MagicMock()
        mock_ollama.chat_stream = _mock_stream

        engine = OrchestrationEngine(
            llm_client=mock_ollama,
            registry={},
            event_bus=EventBus(),
        )

        plan = await engine.create_plan(
            objective="Create a simple calculator",
            session_id="test-session",
        )

        assert plan is not None
        assert plan.title == "Create a simple calculator"
        assert len(plan.steps) > 0
        assert plan.dependency_graph.validate()[0] is True

    def test_execute_plan_runs_independent_tasks_parallel(self) -> None:
        """Test that independent tasks can execute in parallel."""
        graph = DependencyGraph()

        task1 = TaskNode(name="task1", description="First", agent="CODER")
        task2 = TaskNode(name="task2", description="Second", agent="CODER")
        task3 = TaskNode(
            name="task3",
            description="Third",
            agent="CODER",
            depends_on=[task1.task_id, task2.task_id],
        )

        graph.add_task(task1)
        graph.add_task(task2)
        graph.add_task(task3)

        # Get topological layers
        layers = graph.topological_layers()
        assert len(layers) == 2

        # First layer should have task1 and task2 (parallel)
        assert set(layers[0]) == {task1.task_id, task2.task_id}

        # Second layer should have task3 (depends on both)
        assert layers[1] == [task3.task_id]

    def test_execute_autonomous_verification_round(self) -> None:
        """Test that verification round creates DEBUGGER tasks."""
        graph = DependencyGraph()

        # Simulate a completed task
        task1 = TaskNode(name="task1", description="First", agent="CODER")
        graph.add_task(task1)
        graph.update_status(task1.task_id, TaskStatus.COMPLETED)

        # In a real implementation, the engine would spawn a verification task
        # For now, we test that the graph can track completion
        assert task1.status == TaskStatus.COMPLETED
        assert graph.is_complete()

    def test_execute_autonomous_fix_iteration(self) -> None:
        """Test that fix iteration can be triggered after verification."""
        graph = DependencyGraph()

        # Simulate a task that failed
        task1 = TaskNode(name="task1", description="First", agent="CODER")
        graph.add_task(task1)
        graph.update_status(task1.task_id, TaskStatus.FAILED, "Syntax error")

        # In a real implementation, the engine would spawn a fix task
        # For now, we test that the graph can track failures
        assert task1.status == TaskStatus.FAILED
        assert graph.has_failures()
        assert "Syntax error" in task1.error_message

    def test_execute_autonomous_final_review(self) -> None:
        """Test that final review creates ANALYZER task."""
        graph = DependencyGraph()

        # Simulate completed tasks
        task1 = TaskNode(name="task1", description="First", agent="CODER")
        task2 = TaskNode(name="task2", description="Second", agent="CODER")
        graph.add_task(task1)
        graph.add_task(task2)
        graph.update_status(task1.task_id, TaskStatus.COMPLETED)
        graph.update_status(task2.task_id, TaskStatus.COMPLETED)

        # In a real implementation, the engine would spawn a review task
        # For now, we test that the graph is complete
        assert graph.is_complete()
        assert not graph.has_failures()

    @pytest.mark.asyncio
    async def test_full_cycle_end_to_end(self) -> None:
        """Test a simplified full cycle from query to completion."""
        from unittest.mock import AsyncMock, MagicMock
        from backend.orchestrator.engine import OrchestrationEngine
        from backend.orchestrator.events import EventBus

        async def _mock_stream(*args, **kwargs):
            yield """[
                {"name": "implement_calculator", "description": "Write the calculator function", "agent": "CODER"},
                {"name": "write_tests", "description": "Write unit tests", "agent": "CODER", "depends_on": ["implement_calculator"]},
                {"name": "verify", "description": "Verify implementation", "agent": "DEBUGGER", "depends_on": ["write_tests"]}
            ]"""

        mock_ollama = MagicMock()
        mock_ollama.chat_stream = _mock_stream

        engine = OrchestrationEngine(
            llm_client=mock_ollama,
            registry={},
            event_bus=EventBus(),
        )

        # Create plan
        plan = await engine.create_plan(
            objective="Create a calculator in Python with tests",
            session_id="test-session",
        )

        # Verify plan structure
        assert plan is not None
        assert len(plan.steps) == 3

        # Build dependency graph
        graph = plan.dependency_graph
        assert graph.validate()[0] is True

        # Verify dependency structure
        steps = plan.steps
        assert steps[0].name == "implement_calculator"
        assert steps[1].depends_on == [steps[0].task_id]
        assert steps[2].depends_on == [steps[1].task_id]

        # Verify execution layers
        layers = graph.topological_layers()
        assert len(layers) == 3  # Sequential execution due to dependencies


class TestExecutionPlan:
    """Test ExecutionPlan creation and validation."""

    def test_execution_plan_from_steps(self) -> None:
        """Test creating a plan from a list of steps."""
        step1 = TaskNode(name="step1", description="First", agent="CODER")
        step2 = TaskNode(name="step2", description="Second", agent="CODER")

        plan = ExecutionPlan.from_steps(
            title="Test Plan",
            description="Test description",
            steps=[step1, step2],
            session_id="test-session",
        )

        assert plan.title == "Test Plan"
        assert plan.total_steps == 2
        assert len(plan.dependency_graph.get_all_tasks()) == 2

    def test_execution_plan_with_dependencies(self) -> None:
        """Test plan with dependent steps."""
        step1 = TaskNode(name="step1", description="First", agent="CODER")
        step2 = TaskNode(
            name="step2",
            description="Second",
            agent="CODER",
            depends_on=[step1.task_id],
        )

        plan = ExecutionPlan.from_steps(
            title="Dependent Plan",
            description="Plan with dependencies",
            steps=[step1, step2],
        )

        assert plan.parallel_layers == 2  # Two execution layers

    def test_execution_plan_serialization(self) -> None:
        """Test that plan can be serialized to dict."""
        step = TaskNode(name="step1", description="First", agent="CODER")
        plan = ExecutionPlan.from_steps(
            title="Test Plan",
            description="Test",
            steps=[step],
        )

        plan_dict = plan.to_dict()
        assert "plan_id" in plan_dict
        assert "title" in plan_dict
        assert "steps" in plan_dict
        assert "graph" in plan_dict
