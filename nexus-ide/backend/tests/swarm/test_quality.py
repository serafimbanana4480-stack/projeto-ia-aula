"""Unit tests for SWARM quality gate."""

from __future__ import annotations

from backend.swarm.core.types import Proposal, ReviewReport
from backend.swarm.quality.quality_gate import (
    QualityThresholds,
    gate_failure_reason,
    merge_scores,
    passes_gate,
    score_proposal,
    update_with_review,
)


def test_score_proposal_detects_risky_keywords() -> None:
    p = Proposal(
        title="Wipe production database",
        description="delete all rows",
        rationale="clean up",
        files_to_change=[{"path": "db.py", "change": "DELETE FROM users"}] * 8,
    )
    s = score_proposal(p)
    assert s.risk > 0.4
    assert s.complexity > 0.0


def test_passes_gate_with_balanced_scores() -> None:
    s = score_proposal(
        Proposal(
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
            files_to_change=[{"path": "h.py", "change": "refactor + add types"}],
            evidence_refs=["h.py:1-50"],
        )
    )
    assert passes_gate(s), f"should pass but: {s.to_dict()}"


def test_gate_failure_reason_lists_all_violations() -> None:
    # A proposal that's clearly bad on every axis
    p = Proposal(
        title="DROP TABLE users",
        description="DELETE all rows from production",
        rationale="rm -rf the database",
        files_to_change=[{"path": "db.py", "change": "TRUNCATE sessions"}] * 8,
    )
    s = score_proposal(p)
    reason = gate_failure_reason(s, thresholds=QualityThresholds(min_quality=0.99, max_risk=0.0))
    assert "quality" in reason
    assert "risk" in reason


def test_update_with_review_drops_quality_on_critical_findings() -> None:
    # Build a base proposal that already has SOME quality so the delta is visible
    base = score_proposal(
        Proposal(
            title=("## Plan\n\nAdd admin endpoint with proper validation, tests and docs."),
            description=("- Add endpoint\n- Validate input\n- Add tests\n- Add doc"),
            rationale=("- tests added\n- type hints added\n- docs updated"),
            files_to_change=[{"path": "a.py", "change": "add endpoint with validation"}],
            evidence_refs=["a.py:1-50"],
        )
    )
    review = ReviewReport(
        target_id="t",
        findings=[{"severity": "critical", "category": "security", "message": "x"}],
    )
    new = update_with_review(base, review)
    assert new.quality < base.quality
    assert new.risk > base.risk


def test_merge_scores_averages() -> None:
    a = score_proposal(Proposal(title="A", description="A", rationale="A"))
    b = score_proposal(Proposal(title="B", description="B", rationale="B"))
    m = merge_scores(a, b)
    assert 0 <= m.quality <= 1
    assert abs(m.quality - (a.quality + b.quality) / 2) < 1e-9
