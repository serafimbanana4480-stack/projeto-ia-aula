"""StackSelector — selects optimal technology stacks for projects."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.agents.executive.technology_strategist import TechnologyStrategist

logger = logging.getLogger(__name__)


@dataclass
class StackSelection:
    """Record of a stack selection decision."""

    selection_id: str
    project_requirements: dict[str, Any]
    chosen_stack_id: str
    chosen_name: str
    score: float
    compared_stacks: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    rationale: str = ""


class StackSelector:
    """Selects optimal stacks by comparing evaluated options.

    Integrates with ``TechnologyStrategist`` to pick the best fit for a
    given set of project requirements.
    """

    def __init__(
        self,
        strategist: TechnologyStrategist | None = None,
    ) -> None:
        self._strategist = strategist or TechnologyStrategist()
        self._history: list[StackSelection] = []

    @property
    def strategist(self) -> TechnologyStrategist:
        return self._strategist

    def select_stack(
        self,
        project_requirements: dict[str, Any],
    ) -> StackSelection | None:
        """Select the best stack for the given requirements.

        Args:
            project_requirements: May contain:
                - ``weights``: dict of criterion → importance (0.0–1.0)
                - ``must_have``: list of required capabilities or tags
                - ``notes``: free-form notes

        Returns:
            A ``StackSelection`` record, or ``None`` if no stacks are evaluated.
        """
        weights = project_requirements.get("weights", {})
        recommendations = self._strategist.get_recommendation(weights)
        if not recommendations:
            logger.warning("No stacks available for selection")
            return None

        best = recommendations[0]
        selection = StackSelection(
            selection_id=f"sel-{uuid.uuid4().hex[:8]}",
            project_requirements=dict(project_requirements),
            chosen_stack_id=best.stack_id,
            chosen_name=best.name,
            score=best.overall,
            compared_stacks=[r.name for r in recommendations[:5]],
            rationale=f"Selected based on weighted fit across {len(weights)} criteria",
        )
        self._history.append(selection)
        logger.info(
            "Stack selected: %s (score=%.2f) for %s",
            best.name,
            best.overall,
            project_requirements.get("notes", "unknown project"),
        )
        return selection

    def compare_stacks(self, stack_names: list[str]) -> dict[str, Any]:
        """Compare specific stacks by name (partial match supported).

        Returns a dictionary with comparison tables and deltas.
        """
        all_stacks = self._strategist.list_stacks()
        matched: list[Any] = []
        for name in stack_names:
            for stack in all_stacks:
                if name.lower() in stack.name.lower():
                    matched.append(stack)
                    break

        if not matched:
            return {"error": "No matching stacks found", "comparisons": []}

        from backend.agents.executive.technology_strategist import CRITERIA

        comparisons = []
        for stack in matched:
            comparisons.append({
                "name": stack.name,
                "stack_id": stack.stack_id,
                "overall": stack.overall,
                "scores": {c: stack.scores.get(c, 0.0) for c in CRITERIA},
            })

        # Find best overall
        best = max(matched, key=lambda s: s.overall)
        return {
            "best_overall": best.name,
            "comparisons": comparisons,
        }

    def get_selection_history(self) -> list[StackSelection]:
        """Return all past stack selections (newest first)."""
        return sorted(self._history, key=lambda s: s.timestamp, reverse=True)

    def stats(self) -> dict[str, Any]:
        if not self._history:
            return {"total_selections": 0}
        return {
            "total_selections": len(self._history),
            "unique_stacks_selected": len({s.chosen_stack_id for s in self._history}),
            "avg_score": sum(s.score for s in self._history) / len(self._history),
        }
