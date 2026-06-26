"""ArchitectureDecisionMaker — records and manages Architecture Decision Records (ADRs)."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ADRStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"
    SUPERSEDED = "superseded"


@dataclass
class ArchitectureDecisionRecord:
    """A single Architecture Decision Record (ADR)."""

    adr_id: str
    title: str
    context: str
    decision: str
    consequences: str
    status: ADRStatus
    created_at: float
    updated_at: float
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class ArchitectureDecisionMaker:
    """Records, tracks, and queries Architecture Decision Records (ADRs)."""

    def __init__(self) -> None:
        self._records: dict[str, ArchitectureDecisionRecord] = {}

    def record_decision(
        self,
        title: str,
        context: str,
        decision: str,
        consequences: str,
        status: str = "proposed",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArchitectureDecisionRecord:
        """Record a new architecture decision.

        Args:
            title: Short title for the decision.
            context: Background and problem statement.
            decision: What was decided.
            consequences: Expected impact (positive and negative).
            status: One of the ``ADRStatus`` values.
            tags: Optional classification tags.
            metadata: Free-form metadata.

        Returns:
            The created ``ArchitectureDecisionRecord``.
        """
        adr_id = f"adr-{uuid.uuid4().hex[:8]}"
        now = time.time()
        try:
            adr_status = ADRStatus(status)
        except ValueError:
            adr_status = ADRStatus.PROPOSED
            logger.warning("Invalid ADR status '%s', defaulting to 'proposed'", status)

        record = ArchitectureDecisionRecord(
            adr_id=adr_id,
            title=title,
            context=context,
            decision=decision,
            consequences=consequences,
            status=adr_status,
            created_at=now,
            updated_at=now,
            tags=tags or [],
            metadata=metadata or {},
        )
        self._records[adr_id] = record
        logger.info("ADR recorded: %s (%s)", title, adr_id)
        return record

    def get_decisions(self, status: str | None = None) -> list[ArchitectureDecisionRecord]:
        """Return ADRs, optionally filtered by status.

        Args:
            status: If provided, only return decisions with this status.

        Returns:
            List of matching records (newest first).
        """
        records = list(self._records.values())
        if status is not None:
            try:
                target = ADRStatus(status)
                records = [r for r in records if r.status == target]
            except ValueError:
                return []
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def get_decision(self, adr_id: str) -> ArchitectureDecisionRecord | None:
        return self._records.get(adr_id)

    def update_status(self, adr_id: str, status: str) -> ArchitectureDecisionRecord | None:
        """Update the status of an existing ADR.

        Args:
            adr_id: The ADR identifier.
            status: New status value.

        Returns:
            The updated record, or ``None`` if not found.
        """
        record = self._records.get(adr_id)
        if not record:
            return None
        try:
            record.status = ADRStatus(status)
        except ValueError:
            logger.warning("Invalid ADR status '%s' for %s", status, adr_id)
            return None
        record.updated_at = time.time()
        logger.info("ADR %s status updated to %s", adr_id, status)
        return record

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate statistics for recorded ADRs."""
        counts = {s.value: 0 for s in ADRStatus}
        for r in self._records.values():
            counts[r.status.value] += 1
        return {
            "total": len(self._records),
            "by_status": counts,
            "accepted_rate": counts[ADRStatus.ACCEPTED.value] / max(len(self._records), 1),
        }
