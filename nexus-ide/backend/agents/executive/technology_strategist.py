"""TechnologyStrategist — evaluates and scores technology stacks."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

CRITERIA = ["performance", "scalability", "security", "maintainability", "ecosystem"]


@dataclass
class StackScore:
    """Scores for a technology stack across standard criteria."""

    stack_id: str
    name: str
    scores: dict[str, float] = field(default_factory=dict)
    overall: float = 0.0
    notes: str = ""
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self._normalize_scores()

    def _normalize_scores(self) -> None:
        for criterion in CRITERIA:
            self.scores.setdefault(criterion, 0.0)
            self.scores[criterion] = max(0.0, min(1.0, self.scores[criterion]))
        if len(CRITERIA) > 0:
            self.overall = sum(self.scores[c] for c in CRITERIA) / len(CRITERIA)


class TechnologyStrategist:
    """Evaluates and scores technology stacks for architectural decisions.

    Stores stacks in memory with scores for:
    - performance
    - scalability
    - security
    - maintainability
    - ecosystem
    """

    def __init__(self) -> None:
        self._stacks: dict[str, StackScore] = {}

    def evaluate_stack(
        self,
        name: str,
        criteria_dict: dict[str, float],
        notes: str = "",
    ) -> StackScore:
        """Evaluate and store a technology stack.

        Args:
            name: Human-readable stack name (e.g. "FastAPI + PostgreSQL").
            criteria_dict: Mapping of criterion name to 0.0–1.0 score.
            notes: Optional free-form notes.

        Returns:
            The created ``StackScore`` instance.
        """
        stack_id = f"stack-{uuid.uuid4().hex[:8]}"
        stack = StackScore(
            stack_id=stack_id,
            name=name,
            scores={k: v for k, v in criteria_dict.items() if k in CRITERIA},
            notes=notes,
        )
        self._stacks[stack_id] = stack
        logger.info("Stack evaluated: %s (overall=%.2f)", name, stack.overall)
        return stack

    def get_stack(self, stack_id: str) -> StackScore | None:
        return self._stacks.get(stack_id)

    def get_recommendation(
        self,
        requirements: dict[str, float],
        min_overall: float = 0.0,
    ) -> list[StackScore]:
        """Return stacks ranked by weighted fit to *requirements*.

        Args:
            requirements: Criterion → importance weight (0.0–1.0).
            min_overall: Minimum overall score to be considered.

        Returns:
            Sorted list of matching stacks (best fit first).
        """
        scored: list[tuple[float, StackScore]] = []
        for stack in self._stacks.values():
            if stack.overall < min_overall:
                continue
            fit = 0.0
            total_weight = 0.0
            for criterion, weight in requirements.items():
                if criterion in stack.scores:
                    fit += stack.scores[criterion] * weight
                    total_weight += weight
            if total_weight > 0:
                fit /= total_weight
            else:
                fit = stack.overall
            scored.append((fit, stack))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored]

    def list_stacks(self) -> list[StackScore]:
        """Return all evaluated stacks."""
        return sorted(self._stacks.values(), key=lambda s: s.overall, reverse=True)

    def remove_stack(self, stack_id: str) -> bool:
        if stack_id in self._stacks:
            del self._stacks[stack_id]
            return True
        return False

    def stats(self) -> dict[str, Any]:
        if not self._stacks:
            return {"total_stacks": 0}
        totals = {c: 0.0 for c in CRITERIA}
        for stack in self._stacks.values():
            for c in CRITERIA:
                totals[c] += stack.scores.get(c, 0.0)
        count = len(self._stacks)
        return {
            "total_stacks": count,
            "avg_overall": sum(s.overall for s in self._stacks.values()) / count,
            "avg_by_criterion": {c: totals[c] / count for c in CRITERIA},
        }
