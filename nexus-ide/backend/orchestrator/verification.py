"""Verification and autonomous self-improvement helpers for the orchestrator.

Extracted from ``backend.orchestrator.engine`` so the engine file stays focused
on coordination logic.
"""

from __future__ import annotations

from typing import Any

from backend.orchestrator.dependency_graph import TaskNode, TaskPriority
from backend.orchestrator.types import OrchestrationResult

__all__ = [
    "_find_tasks_needing_verification",
    "_create_verification_tasks",
    "_extract_verification_issues",
    "_create_fix_tasks",
    "_create_final_review_task",
]


def _find_tasks_needing_verification(result: OrchestrationResult) -> list[dict]:
    """Find completed CODER tasks that should be verified by DEBUGGER."""
    tasks_needing_verify: list[dict] = []
    for task_id, artifact in result.task_results.items():
        if not isinstance(artifact, dict):
            continue
        agent = artifact.get("agent", "")
        status = artifact.get("status", "")
        if agent == "CODER" and status == "completed":
            tasks_needing_verify.append(
                {
                    "task_id": task_id,
                    "name": artifact.get("name", "Unknown"),
                    "output": artifact.get("output", ""),
                }
            )
    return tasks_needing_verify


def _create_verification_tasks(
    tasks_to_verify: list[dict[str, Any]],
    result: OrchestrationResult,
    session_id: str,
) -> list[TaskNode]:
    """Create DEBUGGER verification tasks for completed CODER work."""
    verify_steps: list[TaskNode] = []
    for task_info in tasks_to_verify:
        verify_task = TaskNode(
            name=f"Verify: {task_info['name']}",
            description=(
                f"Verify the output of task '{task_info['name']}'. "
                f"Check for: bugs, syntax errors, missing imports, "
                f"logic errors, edge cases. "
                f"Run any tests if available. "
                f"Original output:\n{task_info['output'][:1000]}"
            ),
            agent="DEBUGGER",
            priority=TaskPriority.HIGH,
            context=task_info["output"][:2000],
        )
        verify_steps.append(verify_task)
    return verify_steps


def _extract_verification_issues(verify_result: OrchestrationResult) -> list[dict]:
    """Extract issues found by DEBUGGER from verification results."""
    issues: list[dict] = []
    for task_id, artifact in verify_result.task_results.items():
        if not isinstance(artifact, dict):
            continue
        output = artifact.get("output", "")
        agent = artifact.get("agent", "")
        if agent != "DEBUGGER":
            continue
        error_indicators = [
            "error",
            "bug",
            "issue",
            "problem",
            "fix",
            "failed",
            "incorrect",
            "missing",
            "broken",
            "erro",
            "problema",
            "falha",
        ]
        output_lower = output.lower()
        if any(ind in output_lower for ind in error_indicators):
            issues.append(
                {
                    "task_id": task_id,
                    "name": artifact.get("name", "Unknown verification"),
                    "output": output,
                    "agent": agent,
                }
            )
    return issues


def _create_fix_tasks(
    issues: list[dict[str, Any]],
    verify_tasks: list[TaskNode],
    session_id: str,
) -> list[TaskNode]:
    """Create CODER fix tasks based on DEBUGGER findings."""
    fix_steps: list[TaskNode] = []
    for issue in issues:
        fix_task = TaskNode(
            name=f"Fix: {issue['name']}",
            description=(
                f"Fix the issues found during verification of '{issue['name']}'. "
                f"DEBUGGER findings:\n{issue['output'][:2000]}\n\n"
                f"Apply all necessary fixes and ensure the code works correctly."
            ),
            agent="CODER",
            priority=TaskPriority.HIGH,
            context=issue["output"][:2000],
        )
        fix_steps.append(fix_task)
    return fix_steps


def _create_final_review_task(
    objective: str,
    result: OrchestrationResult,
    session_id: str,
) -> TaskNode:
    """Create a final ANALYZER review task."""
    completed_summary = "\n".join(
        f"- {a.get('name', 'Unknown')}: {a.get('status', '?')}"
        for a in result.task_results.values()
        if isinstance(a, dict)
    )
    return TaskNode(
        name="Final Quality Review",
        description=(
            f"Perform a comprehensive quality review of all work done for: {objective}\n\n"
            f"Completed tasks:\n{completed_summary}\n\n"
            f"Check for: consistency, completeness, code quality, "
            f"security issues, performance problems, missing documentation."
        ),
        agent="ANALYZER",
        priority=TaskPriority.MEDIUM,
    )
