from __future__ import annotations

from backend.orchestrator.dependency_graph import ExecutionPlan, TaskNode
from backend.orchestrator.plan_validation import (
    build_deterministic_plan,
    validate_execution_plan,
)


def _snapshot() -> dict:
    return {
        "absolute_path": "/tmp/project",
        "files": ["/tmp/project/app.py", "/tmp/project/tests/test_app.py"],
        "test_frameworks": ["pytest"],
        "dependency_manifests": ["pyproject.toml"],
    }


def test_deterministic_plan_has_concrete_three_phase_contract() -> None:
    plan = build_deterministic_plan("Add a health endpoint", _snapshot(), "s1")
    assert [task.agent for task in plan.steps] == ["ANALYZER", "CODER", "DEBUGGER"]
    assert all(task.file_scope for task in plan.steps)
    assert all(task.completion_criteria for task in plan.steps)
    assert plan.steps[-1].verification_commands == ["python -m pytest -q"]
    assert validate_execution_plan(plan, _snapshot(), 50).valid

def test_deterministic_plan_dependencies_are_registered_and_ordered() -> None:
    plan = build_deterministic_plan("Add a health endpoint", _snapshot(), "s1")
    assert plan.steps[1].depends_on == [plan.steps[0].task_id]
    assert plan.steps[2].depends_on == [plan.steps[1].task_id]
    assert plan.steps[0].task_id in plan.steps[1].depends_on
    assert plan.dependency_graph.topological_layers() == [
        [plan.steps[0].task_id],
        [plan.steps[1].task_id],
        [plan.steps[2].task_id],
    ]


def test_validator_rejects_unknown_dependency_without_repairing() -> None:
    task = TaskNode(
        name="Implement feature",
        description="Implement the measured feature",
        agent="CODER",
        file_scope=["/tmp/project/app.py"],
        completion_criteria=["feature works"],
        risk="low",
        rollback="revert diff",
        lock_scope="write:/tmp/project",
    )
    plan = ExecutionPlan.from_steps("x", "x", [task], "s1")
    task.depends_on.append("missing-task")
    result = validate_execution_plan(plan, _snapshot(), 50)
    assert not result.valid
    assert any("unknown" in error for error in result.errors)


def test_validator_rejects_generic_and_missing_verification() -> None:
    task = TaskNode(
        name="Execute Objective",
        description="Execute Objective",
        agent="CODER",
        file_scope=["/tmp/project/app.py"],
        completion_criteria=["done"],
        risk="low",
        rollback="revert diff",
        lock_scope="write:/tmp/project",
    )
    plan = ExecutionPlan.from_steps("x", "x", [task], "s1")
    result = validate_execution_plan(plan, _snapshot(), 50)
    assert not result.valid
    assert any("generic" in error for error in result.errors)
    assert any("verification" in error for error in result.errors)


def test_validator_rejects_cycle_without_mutating_plan() -> None:
    first = TaskNode(
        name="First", agent="CODER", file_scope=["/tmp/project/app.py"],
        completion_criteria=["done"], risk="low", rollback="revert", lock_scope="write:x",
    )
    second = TaskNode(
        name="Second", agent="DEBUGGER", file_scope=["/tmp/project/app.py"],
        completion_criteria=["done"], verification_commands=["python -m pytest -q"],
        risk="low", rollback="revert", lock_scope="read:x", depends_on=[first.task_id],
    )
    first.required_by.append(second.task_id)
    plan = ExecutionPlan.from_steps("x", "x", [first, second], "s1")
    first.depends_on.append(second.task_id)
    second.required_by.append(first.task_id)
    result = validate_execution_plan(plan, _snapshot(), 50)
    assert not result.valid
    assert first.depends_on == [second.task_id]
