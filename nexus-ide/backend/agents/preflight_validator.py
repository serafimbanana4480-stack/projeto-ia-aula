"""Pre-Flight Validator Agent — validates improvement proposals before execution.

Called by META_ANALYZER as part of approval workflow.
Validates: feasibility, dependencies, risk, resource availability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.agents.base import AgentAction, AgentBase

logger = logging.getLogger(__name__)


@dataclass
class PreFlightReport:
    feasible: bool
    risk_score: float
    blocked_by: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    estimated_effort: str = "medium"
    details: dict[str, Any] = field(default_factory=dict)


class PreFlightValidatorAgent(AgentBase):
    """Runs BEFORE any improvement execution.

    Called by META_ANALYZER as part of approval workflow.
    Validates: feasibility, dependencies, risk, resource availability.
    """

    name = "PREFLIGHT_VALIDATOR"
    model_key = "reasoning"
    prompt_file = "preflight_validator"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.ANALYZE_DATA,
    }

    def __init__(self) -> None:
        super().__init__()
        self._predictor: Any | None = None
        try:
            from backend.core.predictive_failure_detector import PredictiveFailureDetector
            self._predictor = PredictiveFailureDetector()
        except Exception:
            logger.debug("PredictiveFailureDetector not available")

    async def validate(self, proposal: Any, project_id: str = "*") -> PreFlightReport:
        blocked_by: list[str] = []
        recommendations: list[str] = []

        if self._predictor:
            try:
                decision = await self._predictor.should_proceed(proposal, project_id)
                if decision == "block":
                    blocked_by.append("Predictive risk assessment blocked this proposal")
            except Exception:
                logger.debug("Predictive check failed", exc_info=True)

        risk_score = 0.0
        if self._predictor:
            try:
                assessment = await self._predictor.predict_risk(proposal, project_id)
                risk_score = assessment.risk_score
                recommendations.extend(assessment.mitigations)
            except Exception:
                logger.debug("Risk prediction failed", exc_info=True)

        feasible = len(blocked_by) == 0 and risk_score < 0.7
        effort = self._estimate_effort(proposal)

        return PreFlightReport(
            feasible=feasible,
            risk_score=risk_score,
            blocked_by=blocked_by,
            recommendations=recommendations,
            estimated_effort=effort,
            details={"project_id": project_id},
        )

    def _estimate_effort(self, proposal: Any) -> str:
        category = getattr(proposal, "category", "")
        if category in {"architecture", "tool"}:
            return "high"
        if category in {"prompt", "budget"}:
            return "low"
        return "medium"
