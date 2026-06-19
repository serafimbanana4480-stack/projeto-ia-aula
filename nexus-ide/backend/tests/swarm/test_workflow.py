"""Unit tests for the safe-implementation workflow."""

from __future__ import annotations

import pytest

from backend.swarm.core.types import (
    AgentMessage,
    AgentRole,
    MessageType,
    Proposal,
    ReviewReport,
    WorkflowState,
)
from backend.swarm.workflows.safe_workflow import SafeWorkflow, run_safe_workflow


def _good_proposal() -> Proposal:
    return Proposal(
        title="Refactor helper",
        description=(
            "## Plan\n\n"
            "Clean up the small helper.\n\n"
            "- refactor to be consistent\n"
            "- add type hints\n"
            "- add docstring\n"
            "- validate via tests\n"
        ),
        rationale=(
            "## Rationale\n\n"
            "- tests cover the change\n"
            "- type hints added\n"
            "- doc updated\n"
            "- validated by reviewer\n"
        ),
        files_to_change=[
            {"path": "h.py", "change": "refactor + add types", "rationale": "clarity"}
        ],
        evidence_refs=["h.py:1-20"],
    )


def _bad_proposal() -> Proposal:
    return Proposal(
        title="DROP TABLE",
        description="TRUNCATE sessions",
        rationale="",
        files_to_change=[{"path": "db.py", "change": "rm -rf"}] * 8,
    )


def test_workflow_can_transition() -> None:
    w = SafeWorkflow()
    assert w.can_transition(WorkflowState.PROPOSED, WorkflowState.DISCUSSED)
    assert w.can_transition(WorkflowState.DISCUSSED, WorkflowState.VALIDATED)
    assert not w.can_transition(WorkflowState.PROPOSED, WorkflowState.COMPLETED)


def test_workflow_rejects_unsafe_proposal() -> None:
    w = SafeWorkflow()
    p = _bad_proposal()
    ok, reason = w.validate(p)
    assert not ok
    assert p.state == WorkflowState.PROPOSED  # stays where it is
    assert "risk" in reason or "quality" in reason


def test_workflow_approves_then_completes() -> None:
    w = SafeWorkflow()

    def review(p: Proposal) -> ReviewReport:
        return ReviewReport(target_id=p.proposal_id, passed=True, summary="ok")

    w.set_reviewer(review)
    p = _good_proposal()
    ok, _ = w.validate(p)
    assert ok
    assert p.state == WorkflowState.VALIDATED
    ok, _ = w.approve(p)
    assert ok
    assert p.state == WorkflowState.APPROVED


@pytest.mark.asyncio
async def test_run_safe_workflow_happy_path() -> None:
    w = SafeWorkflow()

    def review(p: Proposal) -> ReviewReport:
        return ReviewReport(target_id=p.proposal_id, passed=True, summary="ok")

    w.set_reviewer(review)
    p = _good_proposal()
    result = await run_safe_workflow(w, p, review)
    assert result.approved
    assert result.state == WorkflowState.COMPLETED
    assert result.review is not None
    assert result.review.passed


@pytest.mark.asyncio
async def test_run_safe_workflow_blocks_unsafe() -> None:
    w = SafeWorkflow()
    p = _bad_proposal()
    result = await run_safe_workflow(
        w, p, lambda x: ReviewReport(target_id=x.proposal_id, passed=True)
    )
    assert not result.approved
    assert result.state in (WorkflowState.REJECTED, WorkflowState.FAILED, WorkflowState.PROPOSED)


def test_discuss_appends_message() -> None:
    w = SafeWorkflow()
    p = _good_proposal()
    msg = AgentMessage(
        sender=AgentRole.ARCHITECT.value,
        recipient=AgentRole.COORDINATOR.value,
        content="Looks good",
        type=MessageType.RESPONSE,
    )
    w.discuss(p, msg)
    assert len(p.discussion) == 1
    assert p.state == WorkflowState.DISCUSSED
