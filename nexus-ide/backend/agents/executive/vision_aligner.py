"""VisionAligner — ensures all actions align with company vision and values."""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AlignmentCheck:
    """Result of a vision alignment check."""

    aligned: bool
    score: float  # 0.0 to 1.0
    violations: list[str]
    suggestions: list[str]


class VisionAligner:
    """Ensures all actions and goals align with the company vision.

    Uses keyword overlap and heuristic rules to check alignment.
    """

    def __init__(self, vision: str = "") -> None:
        self._vision = vision
        self._values: list[str] = []

    @property
    def vision(self) -> str:
        return self._vision

    def set_vision(self, vision: str) -> None:
        self._vision = vision
        logger.info("Vision updated: %s...", vision[:100])

    def add_value(self, value: str) -> None:
        self._values.append(value)
        logger.info("Value added: %s", value)

    def check_alignment(
        self,
        action_description: str,
        context: str = "",
    ) -> AlignmentCheck:
        """Check if an action aligns with the vision."""
        if not self._vision:
            return AlignmentCheck(
                aligned=True,
                score=1.0,
                violations=[],
                suggestions=[],
            )

        vision_words = set(self._vision.lower().split())
        action_words = set(action_description.lower().split())
        set(context.lower().split())

        # Calculate overlap
        overlap = len(action_words & vision_words)
        total_vision = len(vision_words)
        score = min(1.0, overlap / max(1, total_vision * 0.2))

        violations = []
        suggestions = []

        # Check for obvious anti-patterns
        anti_patterns = [
            ("bypass security", "Security should never be bypassed"),
            ("ignore test", "All changes must include tests"),
            ("quick hack", "Technical debt should be documented and scheduled"),
            ("skip review", "Code review is mandatory"),
            ("hardcoded secret", "Secrets must use secure storage"),
        ]

        action_lower = action_description.lower()
        for pattern, suggestion in anti_patterns:
            if pattern in action_lower:
                violations.append(f"Anti-pattern detected: {pattern}")
                suggestions.append(suggestion)
                score -= 0.3

        # Check value alignment
        for value in self._values:
            value_words = set(value.lower().split())
            if not (action_words & value_words):
                suggestions.append(f"Consider how this aligns with: {value}")
                score -= 0.1

        score = max(0.0, min(1.0, score))
        aligned = score >= 0.5 and not violations

        return AlignmentCheck(
            aligned=aligned,
            score=score,
            violations=violations,
            suggestions=suggestions,
        )

    def suggest_improvements(self, goal_description: str) -> list[str]:
        """Suggest improvements to better align a goal with vision."""
        if not self._vision:
            return []

        suggestions = []
        vision_keywords = set(self._vision.lower().split())
        goal_keywords = set(goal_description.lower().split())

        missing = vision_keywords - goal_keywords
        if missing:
            top_missing = list(missing)[:5]
            suggestions.append(
                f"Consider incorporating these vision elements: {', '.join(top_missing)}"
            )

        return suggestions
