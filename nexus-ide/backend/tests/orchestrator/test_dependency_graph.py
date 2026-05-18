"""Tests for backend.orchestrator.dependency_graph — DAG and task orchestration."""

from __future__ import annotations

import pytest

from backend.orchestrator.dependency_graph import (
    DependencyGraph,
    ExecutionPlan,
    TaskNode,
    TaskPriority,
    TaskStatus,
)


class TestDependencyGraph:
    """Test DependencyGraph core functionality."""

    def test_create_empty_graph(self) -> None:
        """Test that empty graph has no tasks."""
        graph = DependencyGraph()
        assert graph.get_all_tasks() == []
        assert len(graph._nodes) == 0
        assert len(graph._adjacency) == 0

    def test_add_task_to_graph(self) -> None:
        """Test adding a simple task to the graph."""
        graph = DependencyGraph()
        task = TaskNode(name="test_task", description="Test", agent="CODER")
        graph.add_task(task)

        assert len(graph.get_all_tasks()) == 1
        assert graph.get_task(task.task_id) == task
        assert task.status == TaskStatus.PENDING

    def test_add_task_with_dependencies(self) -> None:
        """Test adding a task with dependencies."""
        graph = DependencyGraph()
        task1 = TaskNode(name="task1", description="First task", agent="CODER")
        task2 = TaskNode(
            name="task2",
            description="Second task",
            agent="CODER",
            depends_on=[task1.task_id],
        )

        graph.add_task(task1)
        graph.add_task(task2)

        assert len(graph.get_all_tasks()) == 2
        assert task2.depends_on == [task1.task_id]
        assert task1.required_by == [task2.task_id]

    def test_add_duplicate_task_raises_error(self) -> None:
        """Test that adding duplicate task_id raises ValueError."""
        graph = DependencyGraph()
        task = TaskNode(name="test", description="Test", agent="CODER")
        graph.add_task(task)

        with pytest.raises(ValueError, match="Duplicate task_id"):
            graph.add_task(task)

    def test_get_ready_tasks_no_deps(self) -> None:
        """Test that tasks without dependencies are ready."""
        graph = DependencyGraph()
        task1 = TaskNode(name="task1", description="First", agent="CODER")
        task2 = TaskNode(name="task2", description="Second", agent="CODER")

        graph.add_task(task1)
        graph.add_task(task2)

        ready = graph.get_ready_tasks()
        assert len(ready) == 2
        assert task1 in ready
        assert task2 in ready

    def test_get_ready_tasks_with_deps_satisfied(self) -> None:
        """Test that tasks with satisfied dependencies are ready."""
        graph = DependencyGraph()
        task1 = TaskNode(name="task1", description="First", agent="CODER")
        task2 = TaskNode(
            name="task2",
            description="Second",
            agent="CODER",
            depends_on=[task1.task_id],
        )

        graph.add_task(task1)
        graph.add_task(task2)

        # Initially only task1 is ready
        ready = graph.get_ready_tasks()
        assert len(ready) == 1
        assert task1 in ready
        assert task2 not in ready

        # Complete task1
        graph.update_status(task1.task_id, TaskStatus.COMPLETED)

        # Now task2 is ready
        ready = graph.get_ready_tasks()
        assert len(ready) == 1
        assert task2 in ready

    def test_get_ready_tasks_with_deps_unsatisfied(self) -> None:
        """Test that tasks with unsatisfied dependencies are not ready."""
        graph = DependencyGraph()
        task1 = TaskNode(name="task1", description="First", agent="CODER")
        task2 = TaskNode(
            name="task2",
            description="Second",
            agent="CODER",
            depends_on=[task1.task_id],
        )

        graph.add_task(task1)
        graph.add_task(task2)

        # task2 should not be ready since task1 is not completed
        ready = graph.get_ready_tasks()
        assert task2 not in ready

    def test_update_status(self) -> None:
        """Test updating task status."""
        graph = DependencyGraph()
        task = TaskNode(name="test", description="Test", agent="CODER")
        graph.add_task(task)

        graph.update_status(task.task_id, TaskStatus.RUNNING)
        assert task.status == TaskStatus.RUNNING

        graph.update_status(task.task_id, TaskStatus.COMPLETED)
        assert task.status == TaskStatus.COMPLETED

    def test_is_complete(self) -> None:
        """Test checking if graph is complete."""
        graph = DependencyGraph()
        task1 = TaskNode(name="task1", description="First", agent="CODER")
        task2 = TaskNode(name="task2", description="Second", agent="CODER")

        graph.add_task(task1)
        graph.add_task(task2)

        # Not complete when pending
        assert not graph.is_complete()

        # Complete one task
        graph.update_status(task1.task_id, TaskStatus.COMPLETED)
        assert not graph.is_complete()

        # Complete all tasks
        graph.update_status(task2.task_id, TaskStatus.COMPLETED)
        assert graph.is_complete()

    def test_circular_dependencies_detected(self) -> None:
        """Test that circular dependencies are detected."""
        graph = DependencyGraph()
        task1 = TaskNode(name="task1", description="First", agent="CODER")
        task2 = TaskNode(name="task2", description="Second", agent="CODER")

        graph.add_task(task1)
        graph.add_task(task2)

        # Add circular dependency
        graph.add_dependency(task1.task_id, task2.task_id)
        graph.add_dependency(task2.task_id, task1.task_id)

        is_valid, error = graph.validate()
        assert not is_valid
        assert "cycle" in error.lower()

    def test_parallel_execution_order(self) -> None:
        """Test that topological layers determine parallel execution order."""
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

        layers = graph.topological_layers()
        assert len(layers) == 2

        # First layer: task1 and task2 (no deps)
        assert set(layers[0]) == {task1.task_id, task2.task_id}

        # Second layer: task3 (depends on task1 and task2)
        assert layers[1] == [task3.task_id]


class TestTaskNode:
    """Test TaskNode dataclass."""

    def test_task_node_defaults(self) -> None:
        """Test that TaskNode has correct defaults."""
        task = TaskNode(name="test", description="Test", agent="CODER")
        assert task.status == TaskStatus.PENDING
        assert task.priority == TaskPriority.MEDIUM
        assert task.model_key == "coder"
        assert task.depends_on == []
        assert task.required_by == []
        assert task.subtasks == []

    def test_task_node_to_dict(self) -> None:
        """Test TaskNode serialization to dict."""
        task = TaskNode(
            name="test",
            description="Test",
            agent="CODER",
            priority=TaskPriority.HIGH,
        )
        task_dict = task.to_dict()

        assert task_dict["name"] == "test"
        assert task_dict["agent"] == "CODER"
        assert task_dict["priority"] == TaskPriority.HIGH.value
        assert task_dict["status"] == TaskStatus.PENDING.value


class TestExecutionPlan:
    """Test ExecutionPlan dataclass."""

    def test_execution_plan_from_steps(self) -> None:
        """Test creating a plan from steps."""
        task1 = TaskNode(name="task1", description="First", agent="CODER")
        task2 = TaskNode(name="task2", description="Second", agent="CODER")

        plan = ExecutionPlan.from_steps(
            title="Test Plan",
            description="Test description",
            steps=[task1, task2],
            session_id="test-session",
        )

        assert plan.title == "Test Plan"
        assert plan.total_steps == 2
        assert len(plan.steps) == 2
        assert plan.session_id == "test-session"

    def test_execution_plan_to_dict(self) -> None:
        """Test ExecutionPlan serialization to dict."""
        task = TaskNode(name="task1", description="First", agent="CODER")
        plan = ExecutionPlan.from_steps(
            title="Test Plan",
            description="Test description",
            steps=[task],
        )

        plan_dict = plan.to_dict()
        assert plan_dict["title"] == "Test Plan"
        assert plan_dict["total_steps"] == 1
        assert "graph" in plan_dict
