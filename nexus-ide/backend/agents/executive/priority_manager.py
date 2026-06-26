"""PriorityManager — dynamic task priority management with escalation."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class PriorityLevel(int, Enum):
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4
    BACKLOG = 5


@dataclass
class PrioritizedItem:
    """An item with dynamic priority."""

    item_id: str
    title: str
    base_priority: PriorityLevel
    created_at: float = field(default_factory=time.time)
    escalated_at: float | None = None
    deadline: float | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def effective_priority(self) -> float:
        """Calculate effective priority score (lower = more urgent)."""
        score = float(self.base_priority.value)

        # Escalation bonus
        if self.escalated_at:
            score -= 0.5

        # Deadline pressure
        if self.deadline:
            time_left = self.deadline - time.time()
            if time_left < 3600:  # < 1 hour
                score -= 1.0
            elif time_left < 86400:  # < 1 day
                score -= 0.5
            elif time_left < 0:  # overdue
                score -= 2.0

        # Age factor
        age_hours = (time.time() - self.created_at) / 3600
        if age_hours > 24:
            score -= 0.3
        if age_hours > 72:
            score -= 0.5

        return max(0.1, score)


class PriorityManager:
    """Manages dynamic priorities with automatic escalation."""

    def __init__(self) -> None:
        self._items: dict[str, PrioritizedItem] = {}

    def add_item(
        self,
        item_id: str,
        title: str,
        base_priority: PriorityLevel = PriorityLevel.MEDIUM,
        deadline: float | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PrioritizedItem:
        item = PrioritizedItem(
            item_id=item_id,
            title=title,
            base_priority=base_priority,
            deadline=deadline,
            tags=tags or [],
            metadata=metadata or {},
        )
        self._items[item_id] = item
        logger.info("Item added: %s (priority=%s)", title, base_priority.name)
        return item

    def escalate(self, item_id: str) -> PrioritizedItem | None:
        item = self._items.get(item_id)
        if not item:
            return None
        if item.base_priority != PriorityLevel.CRITICAL:
            # Move up one level
            levels = list(PriorityLevel)
            idx = levels.index(item.base_priority)
            if idx > 0:
                item.base_priority = levels[idx - 1]
        item.escalated_at = time.time()
        logger.warning("Item escalated: %s → %s", item_id, item.base_priority.name)
        return item

    def deprioritize(self, item_id: str) -> PrioritizedItem | None:
        item = self._items.get(item_id)
        if not item:
            return None
        levels = list(PriorityLevel)
        idx = levels.index(item.base_priority)
        if idx < len(levels) - 1:
            item.base_priority = levels[idx + 1]
        item.escalated_at = None
        logger.info("Item deprioritized: %s → %s", item_id, item.base_priority.name)
        return item

    def remove_item(self, item_id: str) -> bool:
        if item_id in self._items:
            del self._items[item_id]
            return True
        return False

    def get_queue(self, limit: int = 50) -> list[PrioritizedItem]:
        """Return items sorted by effective priority (most urgent first)."""
        sorted_items = sorted(
            self._items.values(),
            key=lambda i: (i.effective_priority, -i.created_at),
        )
        return sorted_items[:limit]

    def get_by_tag(self, tag: str) -> list[PrioritizedItem]:
        return [i for i in self._items.values() if tag in i.tags]

    def auto_escalate(self, stale_hours: float = 24.0) -> list[PrioritizedItem]:
        """Automatically escalate stale items."""
        escalated = []
        now = time.time()
        for item in self._items.values():
            if item.base_priority == PriorityLevel.CRITICAL:
                continue
            age = (now - item.created_at) / 3600
            if age > stale_hours and not item.escalated_at:
                self.escalate(item.item_id)
                escalated.append(item)
        if escalated:
            logger.info("Auto-escalated %d stale items", len(escalated))
        return escalated

    def stats(self) -> dict[str, Any]:
        by_level = {level.name: 0 for level in PriorityLevel}
        for item in self._items.values():
            by_level[item.base_priority.name] += 1
        return {
            "total": len(self._items),
            "by_priority": by_level,
            "escalated": sum(1 for i in self._items.values() if i.escalated_at),
        }
