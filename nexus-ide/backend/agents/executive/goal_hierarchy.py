"""GoalHierarchy — hierarchical goal decomposition and tracking."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class GoalStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GoalPriority(int, Enum):
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


@dataclass
class Goal:
    """A goal in the hierarchy."""

    goal_id: str
    title: str
    description: str
    status: GoalStatus = GoalStatus.PENDING
    priority: GoalPriority = GoalPriority.MEDIUM
    parent_id: Optional[str] = None
    subgoals: list[str] = field(default_factory=list)
    assigned_agent: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    progress: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "parent_id": self.parent_id,
            "subgoals": self.subgoals,
            "assigned_agent": self.assigned_agent,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "progress": self.progress,
            "metadata": self.metadata,
        }


class GoalHierarchy:
    """Manages hierarchical goal decomposition."""

    def __init__(self) -> None:
        self._goals: dict[str, Goal] = {}

    # ── CRUD ──────────────────────────────────────────────────────────

    def create_goal(
        self,
        title: str,
        description: str,
        priority: GoalPriority = GoalPriority.MEDIUM,
        parent_id: Optional[str] = None,
        metadata: dict[str, Any] | None = None,
    ) -> Goal:
        goal_id = f"goal-{uuid.uuid4().hex[:8]}"
        goal = Goal(
            goal_id=goal_id,
            title=title,
            description=description,
            priority=priority,
            parent_id=parent_id,
            metadata=metadata or {},
        )
        self._goals[goal_id] = goal

        if parent_id and parent_id in self._goals:
            self._goals[parent_id].subgoals.append(goal_id)

        logger.info("Goal created: %s (%s)", title, goal_id)
        return goal

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        return self._goals.get(goal_id)

    def update_goal(self, goal_id: str, **fields: Any) -> Optional[Goal]:
        goal = self._goals.get(goal_id)
        if not goal:
            return None
        for key, value in fields.items():
            if hasattr(goal, key):
                setattr(goal, key, value)
        return goal

    def delete_goal(self, goal_id: str) -> bool:
        if goal_id not in self._goals:
            return False
        goal = self._goals[goal_id]
        # Remove from parent's subgoals
        if goal.parent_id and goal.parent_id in self._goals:
            self._goals[goal.parent_id].subgoals.remove(goal_id)
        # Delete subgoals recursively
        for sub_id in list(goal.subgoals):
            self.delete_goal(sub_id)
        del self._goals[goal_id]
        return True

    # ── Status transitions ───────────────────────────────────────────

    def start_goal(self, goal_id: str) -> Optional[Goal]:
        goal = self._goals.get(goal_id)
        if goal and goal.status == GoalStatus.PENDING:
            goal.status = GoalStatus.ACTIVE
            goal.started_at = time.time()
            logger.info("Goal started: %s", goal_id)
        return goal

    def complete_goal(self, goal_id: str) -> Optional[Goal]:
        goal = self._goals.get(goal_id)
        if goal and goal.status == GoalStatus.ACTIVE:
            goal.status = GoalStatus.COMPLETED
            goal.completed_at = time.time()
            goal.progress = 1.0
            self._update_parent_progress(goal.parent_id)
            logger.info("Goal completed: %s", goal_id)
        return goal

    def fail_goal(self, goal_id: str, reason: str = "") -> Optional[Goal]:
        goal = self._goals.get(goal_id)
        if goal:
            goal.status = GoalStatus.FAILED
            goal.metadata["failure_reason"] = reason
            logger.warning("Goal failed: %s — %s", goal_id, reason)
        return goal

    def block_goal(self, goal_id: str, blocker: str) -> Optional[Goal]:
        goal = self._goals.get(goal_id)
        if goal:
            goal.status = GoalStatus.BLOCKED
            goal.metadata["blocker"] = blocker
            logger.info("Goal blocked: %s — %s", goal_id, blocker)
        return goal

    def update_progress(self, goal_id: str, progress: float) -> Optional[Goal]:
        goal = self._goals.get(goal_id)
        if goal:
            goal.progress = max(0.0, min(1.0, progress))
            self._update_parent_progress(goal.parent_id)
        return goal

    def _update_parent_progress(self, parent_id: Optional[str]) -> None:
        if not parent_id or parent_id not in self._goals:
            return
        parent = self._goals[parent_id]
        if not parent.subgoals:
            return
        total = sum(self._goals[g_id].progress for g_id in parent.subgoals if g_id in self._goals)
        parent.progress = total / len(parent.subgoals)
        if parent.progress >= 1.0 and all(
            self._goals[g_id].status == GoalStatus.COMPLETED
            for g_id in parent.subgoals
            if g_id in self._goals
        ):
            parent.status = GoalStatus.COMPLETED
            parent.completed_at = time.time()

    # ── Queries ───────────────────────────────────────────────────────

    def list_goals(
        self,
        status: Optional[GoalStatus] = None,
        priority: Optional[GoalPriority] = None,
        parent_id: Optional[str] = None,
    ) -> list[Goal]:
        results = list(self._goals.values())
        if status:
            results = [g for g in results if g.status == status]
        if priority:
            results = [g for g in results if g.priority == priority]
        if parent_id is not None:
            results = [g for g in results if g.parent_id == parent_id]
        return sorted(results, key=lambda g: (g.priority.value, -g.created_at))

    def get_roots(self) -> list[Goal]:
        return sorted(
            [g for g in self._goals.values() if g.parent_id is None],
            key=lambda g: (g.priority.value, -g.created_at),
        )

    def get_tree(self, goal_id: str) -> dict[str, Any]:
        goal = self._goals.get(goal_id)
        if not goal:
            return {}
        return {
            **goal.to_dict(),
            "children": [self.get_tree(cid) for cid in goal.subgoals],
        }

    def stats(self) -> dict[str, Any]:
        statuses = {s.value: 0 for s in GoalStatus}
        for g in self._goals.values():
            statuses[g.status.value] += 1
        return {
            "total": len(self._goals),
            "by_status": statuses,
            "root_goals": len(self.get_roots()),
        }
