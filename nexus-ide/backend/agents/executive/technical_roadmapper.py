"""TechnicalRoadmapper — plans milestones and tracks technical timelines."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class MilestoneStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


@dataclass
class Milestone:
    """A milestone on the technical roadmap."""

    milestone_id: str
    name: str
    target_date: float
    deliverables: list[str]
    dependencies: list[str] = field(default_factory=list)
    progress: float = 0.0
    status: MilestoneStatus = MilestoneStatus.PLANNED
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class TechnicalRoadmapper:
    """Plans milestones, manages timelines, and computes critical paths."""

    def __init__(self) -> None:
        self._milestones: dict[str, Milestone] = {}

    def add_milestone(
        self,
        name: str,
        target_date: float,
        deliverables: list[str],
        dependencies: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Milestone:
        """Add a new milestone to the roadmap.

        Args:
            name: Milestone name.
            target_date: Unix timestamp for the target completion date.
            deliverables: List of expected deliverables.
            dependencies: IDs of milestones that must complete first.
            metadata: Optional extra data.

        Returns:
            The created ``Milestone``.
        """
        milestone_id = f"ms-{uuid.uuid4().hex[:8]}"
        milestone = Milestone(
            milestone_id=milestone_id,
            name=name,
            target_date=target_date,
            deliverables=deliverables,
            dependencies=dependencies or [],
            metadata=metadata or {},
        )
        self._milestones[milestone_id] = milestone
        logger.info("Milestone added: %s (%s)", name, milestone_id)
        return milestone

    def get_milestone(self, milestone_id: str) -> Milestone | None:
        return self._milestones.get(milestone_id)

    def get_timeline(self) -> list[Milestone]:
        """Return all milestones sorted by target date (earliest first)."""
        return sorted(self._milestones.values(), key=lambda m: m.target_date)

    def get_critical_path(self) -> list[Milestone]:
        """Return milestones on the critical path.

        The critical path includes milestones that either:
        - Have unresolved dependencies, or
        - Are depended upon by other milestones, or
        - Are currently in progress or blocked.
        """
        if not self._milestones:
            return []

        depended_ids = set()
        for m in self._milestones.values():
            for dep_id in m.dependencies:
                if dep_id in self._milestones:
                    depended_ids.add(dep_id)

        critical: list[Milestone] = []
        for m in self._milestones.values():
            is_active = m.status in (MilestoneStatus.IN_PROGRESS, MilestoneStatus.BLOCKED)
            has_unresolved_deps = any(
                self._milestones.get(d) is not None
                and self._milestones[d].status != MilestoneStatus.COMPLETED
                for d in m.dependencies
            )
            is_depended = m.milestone_id in depended_ids
            if is_active or has_unresolved_deps or is_depended:
                critical.append(m)

        return sorted(critical, key=lambda m: m.target_date)

    def update_progress(
        self,
        milestone_id: str,
        progress: float,
    ) -> Milestone | None:
        """Update milestone progress (0.0–1.0).

        Automatically marks the milestone as completed when progress reaches 1.0.
        """
        milestone = self._milestones.get(milestone_id)
        if not milestone:
            return None
        milestone.progress = max(0.0, min(1.0, progress))
        if milestone.progress >= 1.0:
            milestone.status = MilestoneStatus.COMPLETED
            milestone.completed_at = time.time()
            logger.info("Milestone completed: %s", milestone_id)
        elif milestone.status == MilestoneStatus.PLANNED and milestone.progress > 0.0:
            milestone.status = MilestoneStatus.IN_PROGRESS
            logger.info("Milestone started: %s", milestone_id)
        else:
            logger.info("Milestone %s progress: %.0f%%", milestone_id, milestone.progress * 100)
        return milestone

    def update_status(self, milestone_id: str, status: str) -> Milestone | None:
        """Manually update milestone status."""
        milestone = self._milestones.get(milestone_id)
        if not milestone:
            return None
        try:
            milestone.status = MilestoneStatus(status)
        except ValueError:
            logger.warning("Invalid milestone status '%s' for %s", status, milestone_id)
            return None
        return milestone

    def remove_milestone(self, milestone_id: str) -> bool:
        if milestone_id in self._milestones:
            del self._milestones[milestone_id]
            return True
        return False

    def stats(self) -> dict[str, Any]:
        statuses = {s.value: 0 for s in MilestoneStatus}
        for m in self._milestones.values():
            statuses[m.status.value] += 1
        total = len(self._milestones)
        completed = sum(1 for m in self._milestones.values() if m.status == MilestoneStatus.COMPLETED)
        return {
            "total": total,
            "by_status": statuses,
            "completion_rate": completed / max(total, 1),
        }
