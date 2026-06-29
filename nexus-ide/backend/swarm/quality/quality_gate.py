"""Quality Gate — compute and validate the 4 quality scores.

Quality, Confidence, Risk, Complexity. Each in [0, 1]. The gate keeps
risky / low-quality proposals from auto-approving.

Scoring is intentionally simple & deterministic so the gate is auditable.
The COORDINATOR can override the gate with a human-in-the-loop approval.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.swarm.core.types import Proposal, QualityScores, ReviewReport

logger = logging.getLogger(__name__)


@dataclass
class QualityThresholds:
    """Configurable thresholds for the default quality gate."""

    min_quality: float = 0.65
    max_risk: float = 0.70
    min_confidence: float = 0.45
    max_complexity: float = 0.90  # we accept complex work but flag it


# ---------------------------------------------------------------------------
# Heuristic scoring helpers
# ---------------------------------------------------------------------------

_RISKY_KEYWORDS = (
    "delete",
    "remove",
    "drop",
    "truncate",
    "wipe",
    "destroy",
    "password",
    "secret",
    "token",
    "credential",
    "auth",
    "permission",
    "role",
    "migration",
    "schema",
    "database",
    "production",
    "prod",
    "live",
    "rm -rf",
    "format",
    "exec",
    "eval",
    "shell",
)

_QUALITY_POSITIVE = (
    "test",
    "tests",
    "spec",
    "type",
    "validate",
    "verify",
    "check",
    "doc",
    "comment",
    "explain",
    "rationale",
    "refactor",
    "clean",
    "consistent",
)

_COMPLEXITY_MARKERS = (
    "rewrite",
    "redesign",
    "from scratch",
    "migrate",
    "all files",
    "entire",
    "global",
    "system-wide",
    "cross-cutting",
)


def _score_complexity(text: str) -> float:
    """Heuristic complexity score in [0, 1]."""
    if not text:
        return 0.0
    lowered = text.lower()
    hits = sum(1 for k in _COMPLEXITY_MARKERS if k in lowered)
    # Length contribution (normalised)
    length_factor = min(1.0, len(text) / 4000.0)
    return min(1.0, hits * 0.15 + length_factor * 0.5)


def _score_risk(text: str, file_count: int) -> float:
    """Heuristic risk score in [0, 1]."""
    if not text:
        return 0.0
    lowered = text.lower()
    hits = sum(1 for k in _RISKY_KEYWORDS if k in lowered)
    file_factor = min(1.0, file_count / 10.0)
    return min(1.0, hits * 0.20 + file_factor * 0.30)


def _score_quality(text: str) -> float:
    """Heuristic quality score in [0, 1] based on presence of good signals."""
    if not text:
        return 0.0
    lowered = text.lower()
    pos = sum(1 for k in _QUALITY_POSITIVE if k in lowered)
    # Reward longer, structured text (has paragraphs, bullet points, code blocks)
    has_structure = any(marker in text for marker in ("\n\n", "## ", "```", "- "))
    structure_bonus = 0.15 if has_structure else 0.0
    base = min(1.0, pos * 0.12)
    return min(1.0, base + structure_bonus)


def _score_confidence(
    text: str,
    evidence_count: int,
    decision_count: int,
    review_passed: bool | None,
) -> float:
    """Heuristic confidence score in [0, 1]."""
    if not text:
        return 0.0
    base = 0.4
    base += min(0.3, evidence_count * 0.10)
    base += min(0.2, decision_count * 0.10)
    if review_passed is True:
        base += 0.15
    elif review_passed is False:
        base -= 0.20
    return max(0.0, min(1.0, base))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_proposal(proposal: Proposal) -> QualityScores:
    """Compute a QualityScores for a Proposal purely from its textual content.

    This is the cold-start scorer used before any REVIEWER has run.
    """
    blob = " ".join(
        [
            proposal.title,
            proposal.description,
            proposal.rationale,
            " ".join(str(c) for c in proposal.files_to_change),
        ]
    )
    return QualityScores(
        quality=_score_quality(blob),
        confidence=_score_confidence(
            blob,
            evidence_count=len(proposal.evidence_refs),
            decision_count=len(proposal.decision_refs),
            review_passed=None,
        ),
        risk=_score_risk(blob, file_count=len(proposal.files_to_change)),
        complexity=_score_complexity(blob),
    )


def merge_scores(*scores: QualityScores) -> QualityScores:
    """Average multiple scores (used to combine independent reviewers)."""
    if not scores:
        return QualityScores()
    n = len(scores)
    return QualityScores(
        quality=sum(s.quality for s in scores) / n,
        confidence=sum(s.confidence for s in scores) / n,
        risk=sum(s.risk for s in scores) / n,
        complexity=sum(s.complexity for s in scores) / n,
    )


def passes_gate(scores: QualityScores, thresholds: QualityThresholds | None = None) -> bool:
    """Return True if the scores pass the quality gate."""
    th = thresholds or QualityThresholds()
    return (
        scores.quality >= th.min_quality
        and scores.risk <= th.max_risk
        and scores.confidence >= th.min_confidence
        and scores.complexity <= th.max_complexity
    )


def gate_failure_reason(scores: QualityScores, thresholds: QualityThresholds | None = None) -> str:
    """Return a human-readable explanation when the gate fails."""
    th = thresholds or QualityThresholds()
    reasons: list[str] = []
    if scores.quality < th.min_quality:
        reasons.append(f"quality {scores.quality:.2f} < {th.min_quality}")
    if scores.risk > th.max_risk:
        reasons.append(f"risk {scores.risk:.2f} > {th.max_risk}")
    if scores.confidence < th.min_confidence:
        reasons.append(f"confidence {scores.confidence:.2f} < {th.min_confidence}")
    if scores.complexity > th.max_complexity:
        reasons.append(f"complexity {scores.complexity:.2f} > {th.max_complexity}")
    return "; ".join(reasons) if reasons else "ok"


def update_with_review(scores: QualityScores, review: ReviewReport) -> QualityScores:
    """Adjust a base score using a REVIEWER's findings (post-hoc)."""
    n = len(review.findings)
    if n == 0:
        # No findings → trust the review
        return QualityScores(
            quality=min(1.0, scores.quality + 0.10),
            confidence=min(1.0, scores.confidence + 0.10),
            risk=max(0.0, scores.risk - 0.10),
            complexity=scores.complexity,
        )

    critical = sum(1 for f in review.findings if f.get("severity") == "critical")
    high = sum(1 for f in review.findings if f.get("severity") == "high")
    medium = sum(1 for f in review.findings if f.get("severity") == "medium")

    risk = min(1.0, scores.risk + critical * 0.25 + high * 0.10 + medium * 0.04)
    quality = max(0.0, scores.quality - critical * 0.20 - high * 0.10)
    confidence = max(0.0, scores.confidence - critical * 0.15 - high * 0.05)
    return QualityScores(
        quality=quality,
        confidence=confidence,
        risk=risk,
        complexity=scores.complexity,
    )


__all__ = [
    "QualityThresholds",
    "score_proposal",
    "merge_scores",
    "passes_gate",
    "gate_failure_reason",
    "update_with_review",
]
