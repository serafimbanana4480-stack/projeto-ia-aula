"""TechnicalDebtManager — tracks and manages technical debt."""
from __future__ import annotations

import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}


@dataclass
class DebtItem:
    """A single item of technical debt."""

    debt_id: str
    description: str
    severity: Severity
    location: str
    estimated_effort: float  # hours
    status: str = "open"
    created_at: float = field(default_factory=time.time)
    resolved_at: float | None = None
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class TechnicalDebtManager:
    """Records, prioritizes, and tracks payoff of technical debt."""

    def __init__(self) -> None:
        self._debts: dict[str, DebtItem] = {}

    def record_debt(
        self,
        description: str,
        severity: str,
        location: str,
        estimated_effort: float,
        notes: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> DebtItem:
        """Record a new technical debt item.

        Args:
            description: What the debt is.
            severity: ``critical``, ``high``, ``medium``, or ``low``.
            location: File, module, or subsystem where the debt lives.
            estimated_effort: Estimated hours to resolve.
            notes: Additional context.
            metadata: Free-form metadata.

        Returns:
            The created ``DebtItem``.
        """
        debt_id = f"debt-{uuid.uuid4().hex[:8]}"
        try:
            sev = Severity(severity)
        except ValueError:
            sev = Severity.MEDIUM
            logger.warning("Invalid severity '%s', defaulting to 'medium'", severity)

        item = DebtItem(
            debt_id=debt_id,
            description=description,
            severity=sev,
            location=location,
            estimated_effort=estimated_effort,
            notes=notes,
            metadata=metadata or {},
        )
        self._debts[debt_id] = item
        logger.info("Technical debt recorded: %s (%s, %s)", debt_id, sev.value, location)
        return item

    def get_debt(self, debt_id: str) -> DebtItem | None:
        return self._debts.get(debt_id)

    def get_debt_queue(self, status: str = "open") -> list[DebtItem]:
        """Return debt items sorted by severity (most urgent first).

        Args:
            status: Filter by status (default ``open``).
        """
        items = [d for d in self._debts.values() if d.status == status]
        return sorted(
            items,
            key=lambda d: (SEVERITY_ORDER.get(d.severity, 99), d.created_at),
        )

    def pay_debt(self, debt_id: str) -> DebtItem | None:
        """Mark a debt item as resolved (paid off).

        Returns:
            The updated item, or ``None`` if not found.
        """
        item = self._debts.get(debt_id)
        if not item:
            return None
        item.status = "resolved"
        item.resolved_at = time.time()
        logger.info("Technical debt resolved: %s", debt_id)
        return item

    def update_debt(
        self,
        debt_id: str,
        severity: str | None = None,
        estimated_effort: float | None = None,
        notes: str | None = None,
    ) -> DebtItem | None:
        """Update fields of an existing debt item."""
        item = self._debts.get(debt_id)
        if not item:
            return None
        if severity is not None:
            with contextlib.suppress(ValueError):
                item.severity = Severity(severity)
        if estimated_effort is not None:
            item.estimated_effort = estimated_effort
        if notes is not None:
            item.notes = notes
        return item

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate statistics for technical debt."""
        counts = {s.value: 0 for s in Severity}
        total_effort_open = 0.0
        total_effort_resolved = 0.0
        resolved_count = 0
        for d in self._debts.values():
            counts[d.severity.value] += 1
            if d.status == "open":
                total_effort_open += d.estimated_effort
            else:
                total_effort_resolved += d.estimated_effort
                resolved_count += 1

        total = len(self._debts)
        return {
            "total": total,
            "open": sum(1 for d in self._debts.values() if d.status == "open"),
            "resolved": resolved_count,
            "by_severity": counts,
            "total_estimated_effort_open": total_effort_open,
            "total_estimated_effort_resolved": total_effort_resolved,
        }
