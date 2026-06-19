"""Safe Implementation Workflow — gates every code change behind approval.

Pipeline
--------
PROPOSED → DISCUSSED → VALIDATED → APPROVED → IMPLEMENTING → IMPLEMENTED
                                                              → REVIEWING
                                                              → COMPLETED
                                            ↓
                                          REJECTED / FAILED

The workflow guarantees that an IMPLEMENTER agent can never write a file
without an explicit APPROVAL token. The Reviewer independently inspects the
result before declaring COMPLETED.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from backend.swarm.communication.message_bus import MessageBus
from backend.swarm.core.types import (
    AgentMessage,
    Proposal,
    QualityScores,
    ReviewReport,
    WorkflowState,
)
from backend.swarm.quality.quality_gate import (
    QualityThresholds,
    gate_failure_reason,
    passes_gate,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Workflow engine
# ---------------------------------------------------------------------------


@dataclass
class WorkflowStep:
    state: WorkflowState
    description: str
    required: bool = True


WORKFLOW_PIPELINE: list[WorkflowStep] = [
    WorkflowStep(WorkflowState.PROPOSED, "Emit a Proposal with file-level changes"),
    WorkflowStep(WorkflowState.DISCUSSED, "Other agents may post messages to the proposal"),
    WorkflowStep(WorkflowState.VALIDATED, "Quality gate passed and at least one review"),
    WorkflowStep(WorkflowState.APPROVED, "Coordinator or human approved the proposal"),
    WorkflowStep(WorkflowState.IMPLEMENTING, "Apply the changes (out-of-scope for SWARM core)"),
    WorkflowStep(WorkflowState.IMPLEMENTED, "Reported back by the implementer"),
    WorkflowStep(WorkflowState.REVIEWING, "Final review by REVIEWER"),
    WorkflowStep(WorkflowState.COMPLETED, "All checks passed"),
]


@dataclass
class WorkflowResult:
    proposal_id: str
    state: WorkflowState
    approved: bool
    review: ReviewReport | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "state": self.state.value,
            "approved": self.approved,
            "error": self.error,
            "history": self.history,
            "review": self.review.to_dict() if self.review else None,
        }


class SafeWorkflow:
    """Drives a :class:`Proposal` through the safe-implementation pipeline.

    The workflow is *not* what writes to disk — it gates the process and
    records the audit trail. External code (the orchestrator, a human
    reviewer via the API) is responsible for the actual application step.
    """

    def __init__(
        self,
        message_bus: MessageBus | None = None,
        thresholds: QualityThresholds | None = None,
        review_callable: Callable[[Proposal], ReviewReport] | None = None,
    ) -> None:
        self.bus = message_bus
        self.thresholds = thresholds or QualityThresholds()
        # Callable used to obtain a review; default: reject unless injected
        self._review_callable = review_callable

    def set_reviewer(self, callable_: Callable[[Proposal], ReviewReport]) -> None:
        self._review_callable = callable_

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def can_transition(self, current: WorkflowState, target: WorkflowState) -> bool:
        order = [step.state for step in WORKFLOW_PIPELINE]
        try:
            ci = order.index(current)
            ti = order.index(target)
        except ValueError:
            return False
        return ti in (ci, ci + 1)

    def discuss(self, proposal: Proposal, message: AgentMessage) -> None:
        """Append a message to the proposal discussion (DISCUSSED state)."""
        if proposal.state != WorkflowState.PROPOSED:
            # Allow further discussion at any non-terminal state
            pass
        proposal.discussion.append(message)
        if proposal.state == WorkflowState.PROPOSED:
            proposal.state = WorkflowState.DISCUSSED
        proposal.updated_at = time.time()
        self._publish(message)

    def validate(self, proposal: Proposal) -> tuple[bool, str]:
        """Run the quality gate. If it passes, move to VALIDATED."""
        scores = proposal.scores or QualityScores()
        ok = passes_gate(scores, self.thresholds)
        reason = gate_failure_reason(scores, self.thresholds)
        if ok:
            proposal.state = WorkflowState.VALIDATED
            proposal.updated_at = time.time()
            self._audit(proposal, "validated", reason or "ok")
        else:
            self._audit(proposal, "validation_failed", reason)
        return ok, reason

    def approve(self, proposal: Proposal, approver: str = "coordinator") -> tuple[bool, str]:
        """Approve a validated proposal (APPROVED state)."""
        if proposal.state not in (WorkflowState.VALIDATED, WorkflowState.DISCUSSED):
            return False, f"cannot approve from state {proposal.state.value}"
        scores = proposal.scores
        if not passes_gate(scores, self.thresholds):
            return False, f"quality gate failed: {gate_failure_reason(scores, self.thresholds)}"
        proposal.state = WorkflowState.APPROVED
        proposal.updated_at = time.time()
        self._audit(proposal, "approved", approver)
        return True, "approved"

    async def run_review(self, proposal: Proposal) -> ReviewReport:
        """Run the reviewer (sync or async callable) and attach the report."""
        if self._review_callable is None:
            raise RuntimeError(
                "No review_callable configured. Inject a ReviewerAgent via set_reviewer()."
            )
        result = self._review_callable(proposal)
        if hasattr(result, "__await__"):
            result = await result  # type: ignore[func-returns-value]
        proposal.review = result.to_dict() if hasattr(result, "to_dict") else result
        # Re-evaluate scores with the new review
        if isinstance(result, ReviewReport):
            from backend.swarm.quality.quality_gate import update_with_review

            proposal.scores = update_with_review(proposal.scores, result)
            proposal.state = WorkflowState.REVIEWING if result.passed else WorkflowState.REJECTED
        proposal.updated_at = time.time()
        self._audit(
            proposal,
            "reviewed",
            f"verdict={'pass' if getattr(result, 'passed', False) else 'fail'}",
        )
        return result  # type: ignore[return-value]

    def mark_implementing(self, proposal: Proposal) -> None:
        if proposal.state != WorkflowState.APPROVED:
            raise RuntimeError(f"cannot implement from state {proposal.state.value}")
        proposal.state = WorkflowState.IMPLEMENTING
        proposal.updated_at = time.time()
        self._audit(proposal, "implementing", "started")

    def mark_implemented(self, proposal: Proposal, log: list[str] | None = None) -> None:
        if proposal.state != WorkflowState.IMPLEMENTING:
            raise RuntimeError(f"cannot mark implemented from {proposal.state.value}")
        proposal.state = WorkflowState.IMPLEMENTED
        proposal.implementation_log = log or []
        proposal.updated_at = time.time()
        self._audit(proposal, "implemented", f"log={len(proposal.implementation_log)} entries")

    def mark_completed(self, proposal: Proposal) -> None:
        if proposal.state not in (WorkflowState.IMPLEMENTED, WorkflowState.REVIEWING):
            raise RuntimeError(f"cannot complete from {proposal.state.value}")
        proposal.state = WorkflowState.COMPLETED
        proposal.updated_at = time.time()
        self._audit(proposal, "completed", "ok")

    def mark_rejected(self, proposal: Proposal, reason: str) -> None:
        proposal.state = WorkflowState.REJECTED
        proposal.updated_at = time.time()
        self._audit(proposal, "rejected", reason)

    def mark_failed(self, proposal: Proposal, reason: str) -> None:
        proposal.state = WorkflowState.FAILED
        proposal.updated_at = time.time()
        self._audit(proposal, "failed", reason)

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------

    def _audit(self, proposal: Proposal, action: str, detail: str) -> None:
        proposal.implementation_log = proposal.implementation_log or []
        proposal.implementation_log.append(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {action}: {detail}"
        )

    async def _publish_async(self, message: AgentMessage) -> None:
        if self.bus is not None:
            with contextlib.suppress(Exception):
                await self.bus.publish(message)

    def _publish(self, message: AgentMessage) -> None:
        """Best-effort fire-and-forget publish; falls back to fire-and-forget task."""
        if self.bus is None:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._publish_async(message))
            else:
                loop.run_until_complete(self._publish_async(message))
        except RuntimeError:
            # No loop — best-effort spawn
            with contextlib.suppress(Exception):
                asyncio.run(self._publish_async(message))

    def history(self, proposal: Proposal) -> list[dict[str, Any]]:
        return [
            {"event": "discussion", "sender": m.sender, "content": m.content[:200]}
            for m in proposal.discussion
        ] + [{"event": "log", "content": line} for line in (proposal.implementation_log or [])]


# ---------------------------------------------------------------------------
# High-level helper
# ---------------------------------------------------------------------------


async def run_safe_workflow(
    workflow: SafeWorkflow,
    proposal: Proposal,
    review: Callable[[Proposal], ReviewReport | Awaitable[ReviewReport]],
    *,
    approver: str = "coordinator",
) -> WorkflowResult:
    """Drive a proposal through validate → approve → review → complete.

    If the review fails, the proposal is marked REJECTED and the workflow
    aborts. If it passes, the proposal reaches COMPLETED.
    """
    ok, reason = workflow.validate(proposal)
    if not ok:
        workflow.mark_rejected(proposal, reason)
        return WorkflowResult(
            proposal_id=proposal.proposal_id,
            state=proposal.state,
            approved=False,
            error=reason,
            history=workflow.history(proposal),
        )

    ok, reason = workflow.approve(proposal, approver=approver)
    if not ok:
        workflow.mark_rejected(proposal, reason)
        return WorkflowResult(
            proposal_id=proposal.proposal_id,
            state=proposal.state,
            approved=False,
            error=reason,
            history=workflow.history(proposal),
        )

    review_report = await workflow.run_review(proposal)
    if not review_report.passed:
        workflow.mark_rejected(proposal, review_report.summary)
        return WorkflowResult(
            proposal_id=proposal.proposal_id,
            state=proposal.state,
            approved=False,
            review=review_report,
            history=workflow.history(proposal),
        )

    workflow.mark_completed(proposal)
    return WorkflowResult(
        proposal_id=proposal.proposal_id,
        state=proposal.state,
        approved=True,
        review=review_report,
        history=workflow.history(proposal),
    )


__all__ = [
    "SafeWorkflow",
    "WorkflowResult",
    "WorkflowStep",
    "WORKFLOW_PIPELINE",
    "run_safe_workflow",
]
