"""Predictive Failure Detector — uses historical patterns to predict failures before they happen.

Runs before each improvement cycle to assess risk and recommend mitigations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RiskAssessment:
    risk_score: float
    risk_level: str
    mitigations: list[str]
    matched_patterns: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class PredictiveFailureDetector:
    """Uses historical patterns to PREDICT failures before they happen."""

    def __init__(self) -> None:
        self._knowledge_base: Any | None = None
        try:
            from backend.core.knowledge_base import KnowledgeBase
            self._knowledge_base = KnowledgeBase.get_instance()
        except Exception:
            logger.debug("KnowledgeBase not available for PredictiveFailureDetector")

    async def predict_risk(self, proposal: Any, project_id: str = "*") -> RiskAssessment:
        mitigations: list[str] = []
        matched_patterns: list[str] = []
        risk_score = 0.0

        if self._knowledge_base:
            try:
                context = {"target": getattr(proposal, "target", ""), "category": getattr(proposal, "category", "")}
                pattern = self._knowledge_base.find_matching_pattern(project_id, context)
                if pattern:
                    matched_patterns.append(pattern.pattern_id)
                    risk_score = max(risk_score, 1.0 - pattern.confidence)
                    if pattern.success_rate < 0.5:
                        mitigations.append(f"Pattern success rate is low ({pattern.success_rate:.0%}); consider manual review")
                    risk_score = min(1.0, risk_score)
            except Exception:
                logger.debug("Pattern lookup failed", exc_info=True)

        confidence = getattr(proposal, "confidence", 0.5)
        if confidence < 0.5:
            risk_score = max(risk_score, 0.6)
            mitigations.append("Low proposal confidence; require additional validation")

        if risk_score > 0.7:
            risk_level = "high"
        elif risk_score > 0.4:
            risk_level = "medium"
        else:
            risk_level = "low"

        if not mitigations:
            mitigations.append("No specific mitigations; proceed with standard quality gates")

        return RiskAssessment(
            risk_score=risk_score,
            risk_level=risk_level,
            mitigations=mitigations,
            matched_patterns=matched_patterns,
            details={"confidence": confidence, "project_id": project_id},
        )

    async def should_proceed(self, proposal: Any, project_id: str = "*") -> str:
        risk = await self.predict_risk(proposal, project_id)
        if risk.risk_score > 0.7:
            return "block"
        if risk.risk_score > 0.4:
            return "approval_required"
        return "proceed"
