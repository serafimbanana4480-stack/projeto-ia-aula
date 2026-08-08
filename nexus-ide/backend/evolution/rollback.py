"""Rollback — automatic revert on production degradation.

FASE 9. If a promoted champion starts failing in production (detected via
trace lake metrics or RegressionGuard violations), the Rollback manager
archives the failing version and restores the previous champion.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.evolution.registry import (
    ChampionRegistry,
    ComponentStatus,
    ComponentVersion,
    _utcnow_iso,
)

logger = logging.getLogger(__name__)


@dataclass
class RollbackEvent:
    """Record of a rollback action."""

    component_kind: str
    from_version: str     # version that was rolled back (the bad champion)
    to_version: str       # version restored (the previous champion)
    reason: str
    timestamp: str
    metrics_before: dict[str, Any]
    metrics_after: dict[str, Any] | None = None


class RollbackManager:
    """Monitors production health and reverts bad promotions.

    Usage:
        rollback = RollbackManager(registry)
        if rollback.should_rollback("planner", metrics):
            rollback.execute_rollback("planner", reason="...")
    """

    # Thresholds for triggering rollback
    SUCCESS_RATE_DROP_THRESHOLD: float = 0.15  # 15% drop from baseline
    REGRESSION_RATE_THRESHOLD: float = 0.10    # 10% tasks regressed
    SCORE_DROP_THRESHOLD: float = 0.20         # 20% score drop
    MIN_TASKS_FOR_ROLLBACK: int = 10           # minimum tasks to trigger

    def __init__(self, registry: ChampionRegistry) -> None:
        self._registry = registry

    def evaluate_health(
        self,
        component_kind: str,
        current_metrics: dict[str, Any],
        baseline_metrics: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """Evaluate whether the current champion is healthy.

        Args:
            component_kind: The component to check.
            current_metrics: Recent metrics (last N tasks).
            baseline_metrics: Baseline metrics for comparison (champion's stored metrics or historical).

        Returns:
            (should_rollback, reason)
        """
        if not baseline_metrics:
            champion = self._registry.get_champion(component_kind)
            if champion is None:
                return False, "No champion found"
            baseline_metrics = champion.metrics

        current_success = current_metrics.get("success_rate", 0.0)
        baseline_success = baseline_metrics.get("success_rate", 0.0)
        current_score = current_metrics.get("avg_score", 0.0)
        baseline_score = baseline_metrics.get("avg_score", 0.0)
        regression_rate = current_metrics.get("regression_rate", 0.0)
        task_count = current_metrics.get("total_tasks", 0)

        if task_count < self.MIN_TASKS_FOR_ROLLBACK:
            return False, f"Insufficient data ({task_count} tasks, need {self.MIN_TASKS_FOR_ROLLBACK})"

        # Check success rate drop
        if baseline_success > 0:
            drop = (baseline_success - current_success) / baseline_success
            if drop > self.SUCCESS_RATE_DROP_THRESHOLD:
                return True, (
                    f"Success rate dropped {drop:.1%} "
                    f"(from {baseline_success:.3f} to {current_success:.3f})"
                )

        # Check regression rate
        if regression_rate > self.REGRESSION_RATE_THRESHOLD:
            return True, f"Regression rate {regression_rate:.1%} exceeds threshold {self.REGRESSION_RATE_THRESHOLD:.1%}"

        # Check score drop
        if baseline_score > 0:
            drop = (baseline_score - current_score) / baseline_score
            if drop > self.SCORE_DROP_THRESHOLD:
                return True, (
                    f"Score dropped {drop:.1%} "
                    f"(from {baseline_score:.3f} to {current_score:.3f})"
                )

        return False, "Champion healthy"

    def should_rollback(
        self,
        component_kind: str,
        current_metrics: dict[str, Any],
    ) -> tuple[bool, str]:
        """Check if the current champion should be rolled back."""
        champion = self._registry.get_champion(component_kind)
        if champion is None:
            return False, "No champion"

        previous = self._find_previous_champion(component_kind, champion.version)
        if previous is None:
            return False, "No previous champion available for rollback"

        return self.evaluate_health(component_kind, current_metrics, champion.metrics)

    def execute_rollback(
        self,
        component_kind: str,
        reason: str = "",
    ) -> RollbackEvent | None:
        """Rollback to the previous champion version.

        Archives the current champion and restores the previous one.
        """
        champion = self._registry.get_champion(component_kind)
        if champion is None:
            logger.warning(f"Cannot rollback {component_kind}: no champion found")
            return None

        previous = self._find_previous_champion(component_kind, champion.version)
        if previous is None:
            logger.warning(
                f"Cannot rollback {component_kind}: no previous champion available"
            )
            return None

        # Archive the failing champion
        self._registry.archive(component_kind, champion.version)

        # Restore previous champion
        self._registry.promote(component_kind, previous.version, changelog=f"Rollback: {reason}")

        event = RollbackEvent(
            component_kind=component_kind,
            from_version=champion.version,
            to_version=previous.version,
            reason=reason or "Unspecified degradation detected",
            timestamp=_utcnow_iso(),
            metrics_before=champion.metrics,
            metrics_after=previous.metrics,
        )

        # Log the rollback event
        import uuid

        from backend.evolution.registry import _connect
        conn = _connect(self._registry.db_path)
        try:
            conn.execute(
                "INSERT INTO evolution_log "
                "(id, experiment_id, event_type, component_kind, version, message, metrics_json, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"log-{uuid.uuid4().hex[:8]}",
                    None,
                    "rolled_back",
                    component_kind,
                    champion.version,
                    reason,
                    _utcnow_iso(),
                    _utcnow_iso(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        logger.info(
            f"Rollback executed: {component_kind} {champion.version} -> {previous.version} "
            f"(reason: {reason})"
        )
        return event

    def _find_previous_champion(
        self,
        component_kind: str,
        current_version: str,
    ) -> ComponentVersion | None:
        """Find the champion version that was active before the current one."""
        archived = self._registry.list_versions(
            component_kind, status=ComponentStatus.ARCHIVED.value
        )

        # Sort by promoted_at descending to find most recent previous champion
        archived_with_promotions = [v for v in archived if v.promoted_at]
        if not archived_with_promotions:
            return None
        archived_with_promotions.sort(key=lambda v: v.promoted_at or "", reverse=True)
        return archived_with_promotions[0]

    def get_rollback_history(self, component_kind: str) -> list[dict[str, Any]]:
        """Get the rollback history for a component (or all if 'all')."""
        import sqlite3
        conn = sqlite3.connect(str(self._registry.db_path))
        conn.row_factory = sqlite3.Row
        try:
            if component_kind and component_kind != "all":
                rows = conn.execute(
                    "SELECT * FROM evolution_log WHERE component_kind = ? AND event_type = 'rolled_back' "
                    "ORDER BY timestamp DESC",
                    (component_kind,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM evolution_log WHERE event_type = 'rolled_back' "
                    "ORDER BY timestamp DESC",
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
