"""Auto-Correction Loop — closed-loop self-healing for NEXUS IDE.

Monitors the Agent Bus and automatically spawns fix agents when problems are
detected. Enforces a maximum of 5 iterations per artifact before escalating to
META_ANALYZER + OVERSEER.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.core.agent_bus import BusMessage, get_agent_bus

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5


@dataclass
class _CorrectionTracker:
    artifact_id: str
    trigger: str
    iterations: int = 0
    agents_spawned: list[str] = field(default_factory=list)
    status: str = "active"
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class AutoCorrectionLoop:
    """Closed-loop self-healing monitor.

    Usage::

        loop = get_auto_correction_loop()
        await loop.start_monitoring()
        ...
        await loop.stop_monitoring()
    """

    def __init__(self) -> None:
        self._task: asyncio.Task[Any] | None = None
        self._stop_event = asyncio.Event()
        self._status: dict[str, Any] = {
            "monitoring": False,
            "corrections": [],
        }
        self._lock = asyncio.Lock()

    async def start_monitoring(self) -> None:
        """Start the background bus-monitoring task."""
        if self._task is not None and not self._task.done():
            logger.warning("Auto-correction loop already running")
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._monitor())
        self._status["monitoring"] = True
        logger.info("Auto-correction loop started")

    async def stop_monitoring(self) -> None:
        """Stop the background bus-monitoring task."""
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._status["monitoring"] = False
        logger.info("Auto-correction loop stopped")

    # ------------------------------------------------------------------
    # Bus monitoring
    # ------------------------------------------------------------------

    async def _monitor(self) -> None:
        bus = get_agent_bus()

        async def _on_test_results(msg: BusMessage) -> None:
            payload = msg.payload or {}
            failures = payload.get("failures", 0)
            if failures and failures > 0:
                await self._handle_test_failure(payload)

        async def _on_errors_found(msg: BusMessage) -> None:
            payload = msg.payload or {}
            severity = payload.get("severity", "low")
            if severity in ("CRITICAL", "HIGH"):
                await self._handle_critical_error(payload)

        async def _on_review_completed(msg: BusMessage) -> None:
            payload = msg.payload or {}
            review_id = payload.get("review_id")
            if review_id:
                await self._handle_review_completed(review_id, payload)

        async def _on_performance_regression(msg: BusMessage) -> None:
            payload = msg.payload or {}
            await self._handle_performance_regression(payload)

        sub1 = await bus.subscribe("test.results", _on_test_results)
        sub2 = await bus.subscribe("errors.found", _on_errors_found)
        sub3 = await bus.subscribe("review.completed", _on_review_completed)
        sub4 = await bus.subscribe("performance.regression", _on_performance_regression)

        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(1.0)
        finally:
            for sub in (sub1, sub2, sub3, sub4):
                try:
                    await bus.unsubscribe(sub.subscription_id)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_test_failure(self, payload: dict[str, Any]) -> None:
        artifact_id = payload.get("artifact_id", "unknown")
        async with self._lock:
            tracker = self._get_or_create_tracker(artifact_id, "test_failure")
            if tracker.iterations >= MAX_ITERATIONS:
                await self._escalate(
                    artifact_id,
                    "Max auto-correction iterations reached for test failure",
                )
                return
            tracker.iterations += 1
            tracker.agents_spawned.extend(["DEBUGGER", "CODER"])

        await self._publish_status(
            "test_failure",
            artifact_id,
            tracker.iterations,
            "spawned DEBUGGER + CODER",
        )

    async def _handle_critical_error(self, payload: dict[str, Any]) -> None:
        artifact_id = payload.get("artifact_id", "unknown")
        async with self._lock:
            tracker = self._get_or_create_tracker(artifact_id, "critical_error")
            if tracker.iterations >= MAX_ITERATIONS:
                await self._escalate(
                    artifact_id,
                    "Max auto-correction iterations reached for critical error",
                )
                return
            tracker.iterations += 1
            tracker.agents_spawned.extend(["CODER", "OVERSEER"])

        await self._publish_status(
            "critical_error",
            artifact_id,
            tracker.iterations,
            "spawned CODER + OVERSEER",
        )

    async def _handle_review_completed(
        self, review_id: str, payload: dict[str, Any]
    ) -> None:
        from backend.core.peer_review import get_peer_review_system

        prs = get_peer_review_system()
        review = prs.get_review_request(review_id)
        if review is None:
            return
        if review.status != "changes_requested":
            return

        artifact_id = review.artifact_id
        async with self._lock:
            tracker = self._get_or_create_tracker(artifact_id, "review_changes")
            if tracker.iterations >= MAX_ITERATIONS:
                await self._escalate(
                    artifact_id,
                    "Max auto-correction iterations reached for review changes",
                )
                return
            tracker.iterations += 1
            if review.artifact_type == "code":
                tracker.agents_spawned.extend(["REFACTOR_CLEAN", "CODER"])
            else:
                tracker.agents_spawned.extend(["REFACTOR_CLEAN"])

        await self._publish_status(
            "review_changes",
            artifact_id,
            tracker.iterations,
            f"spawned fix agents for {review.artifact_type}",
        )

    async def _handle_performance_regression(
        self, payload: dict[str, Any]
    ) -> None:
        artifact_id = payload.get("artifact_id", "unknown")
        async with self._lock:
            tracker = self._get_or_create_tracker(
                artifact_id, "performance_regression"
            )
            if tracker.iterations >= MAX_ITERATIONS:
                await self._escalate(
                    artifact_id,
                    "Max auto-correction iterations reached for performance regression",
                )
                return
            tracker.iterations += 1
            tracker.agents_spawned.append("REFACTOR_PERFORMANCE")

        await self._publish_status(
            "performance_regression",
            artifact_id,
            tracker.iterations,
            "spawned REFACTOR_PERFORMANCE",
        )

    # ------------------------------------------------------------------
    # Tracking helpers
    # ------------------------------------------------------------------

    def _get_or_create_tracker(
        self, artifact_id: str, trigger: str
    ) -> _CorrectionTracker:
        for c in self._status["corrections"]:
            if c["artifact_id"] == artifact_id and c["trigger"] == trigger:
                # Rehydrate dataclass from dict for mutation
                return _CorrectionTracker(
                    artifact_id=c["artifact_id"],
                    trigger=c["trigger"],
                    iterations=c["iterations"],
                    agents_spawned=list(c["agents_spawned"]),
                    status=c["status"],
                    started_at=c["started_at"],
                )
        tracker = _CorrectionTracker(artifact_id=artifact_id, trigger=trigger)
        self._status["corrections"].append(
            {
                "artifact_id": artifact_id,
                "trigger": trigger,
                "iterations": tracker.iterations,
                "agents_spawned": tracker.agents_spawned,
                "status": tracker.status,
                "started_at": tracker.started_at,
            }
        )
        return tracker

    def _update_tracker(self, tracker: _CorrectionTracker) -> None:
        for c in self._status["corrections"]:
            if (
                c["artifact_id"] == tracker.artifact_id
                and c["trigger"] == tracker.trigger
            ):
                c["iterations"] = tracker.iterations
                c["agents_spawned"] = tracker.agents_spawned
                c["status"] = tracker.status
                return

    async def _escalate(self, artifact_id: str, reason: str) -> None:
        logger.warning(
            "Escalating artifact %s to META_ANALYZER + OVERSEER: %s",
            artifact_id,
            reason,
        )
        bus = get_agent_bus()
        await bus.publish(
            "auto_correction.status",
            BusMessage(
                message_id=uuid.uuid4().hex[:16],
                source_agent="AUTO_CORRECTION",
                payload={
                    "artifact_id": artifact_id,
                    "status": "escalated",
                    "reason": reason,
                    "escalation_targets": ["META_ANALYZER", "OVERSEER"],
                },
            ),
        )

    async def _publish_status(
        self,
        trigger: str,
        artifact_id: str,
        iteration: int,
        detail: str,
    ) -> None:
        bus = get_agent_bus()
        await bus.publish(
            "auto_correction.status",
            BusMessage(
                message_id=uuid.uuid4().hex[:16],
                source_agent="AUTO_CORRECTION",
                payload={
                    "trigger": trigger,
                    "artifact_id": artifact_id,
                    "iteration": iteration,
                    "detail": detail,
                    "status": "active",
                },
            ),
        )

    # ------------------------------------------------------------------
    # Public introspection
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Return the current monitoring status and correction history."""
        return {
            "monitoring": self._status["monitoring"],
            "corrections": list(self._status["corrections"]),
        }


# ──────────────────────────────────────────────────────────────────────────────
# Convenience accessor
# ──────────────────────────────────────────────────────────────────────────────


def get_auto_correction_loop() -> AutoCorrectionLoop:
    """Return the singleton :class:`AutoCorrectionLoop` instance."""
    return AutoCorrectionLoop()
