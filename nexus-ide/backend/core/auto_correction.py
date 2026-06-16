"""Auto-Correction Loop — closed-loop self-healing for NEXUS IDE.

Monitors the Agent Bus and automatically spawns fix agents when problems are
detected. Enforces a maximum of 5 iterations per artifact before escalating to
META_ANALYZER + OVERSEER.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.core.agent_bus import BusMessage, get_agent_bus
from backend.core.agent_lifecycle import AgentLifecycleManager

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
AGENT_TIMEOUT_SECONDS = 300.0


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

    def __init__(self, lifecycle_manager: AgentLifecycleManager | None = None) -> None:
        self._task: asyncio.Task[Any] | None = None
        self._stop_event: asyncio.Event | None = None
        self._status: dict[str, Any] = {
            "monitoring": False,
            "corrections": [],
        }
        self._lock = asyncio.Lock()
        self._lifecycle = lifecycle_manager or AgentLifecycleManager()
        self.active_corrections: dict[str, list[str]] = {}
        self._monitor_tasks: list[asyncio.Task[Any]] = []

    async def start_monitoring(self) -> None:
        """Start the background bus-monitoring task."""
        if self._task is not None and not self._task.done():
            logger.warning("Auto-correction loop already running")
            return

        # Recreate the event in the current loop to avoid cross-loop issues
        self._stop_event = asyncio.Event()
        self._stop_event.clear()
        self._task = asyncio.create_task(self._monitor())
        self._status["monitoring"] = True
        logger.info("Auto-correction loop started")

    async def stop_monitoring(self) -> None:
        """Stop the background bus-monitoring task."""
        if self._stop_event is not None:
            self._stop_event.set()
        for task in self._monitor_tasks:
            if not task.done():
                task.cancel()
        self._monitor_tasks = []
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.debug("Auto-correction task cancelled")
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
            await self._stop_event.wait()
        finally:
            for sub in (sub1, sub2, sub3, sub4):
                try:
                    await bus.unsubscribe(sub.subscription_id)
                except Exception:
                    logger.warning("Failed to unsubscribe from event bus")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_test_failure(self, payload: dict[str, Any]) -> None:
        artifact_id = payload.get("artifact_id", "unknown")

        while True:
            async with self._lock:
                tracker = self._get_or_create_tracker(artifact_id, "test_failure")
                if tracker.iterations >= MAX_ITERATIONS:
                    reason = "Max auto-correction iterations reached for test failure"
                    break
                tracker.iterations += 1
                self._update_tracker(tracker)
                iteration = tracker.iterations

            still_failing = await self._run_test_failure_iteration(artifact_id, payload, iteration)

            if not still_failing:
                await self._publish_status(
                    "test_failure",
                    artifact_id,
                    iteration,
                    f"Tests passed after iteration {iteration}",
                )
                async with self._lock:
                    tracker = self._get_or_create_tracker(artifact_id, "test_failure")
                    tracker.status = "completed"
                    self._update_tracker(tracker)
                return

            # Still failing — check if we have iterations left
            async with self._lock:
                tracker = self._get_or_create_tracker(artifact_id, "test_failure")
                if tracker.iterations >= MAX_ITERATIONS:
                    reason = f"Tests still failing after {MAX_ITERATIONS} iterations"
                    break

            await self._publish_status(
                "test_failure",
                artifact_id,
                iteration,
                f"Tests still failing after iteration {iteration}, looping",
            )

        await self._escalate(artifact_id, reason)

    async def _run_test_failure_iteration(
        self, artifact_id: str, payload: dict[str, Any], iteration: int
    ) -> bool:
        """Run one correction iteration for test failures.

        Returns ``True`` if tests are *still* failing after this iteration.
        """
        test_output = payload.get("output", "N/A")

        # Step 1 — DEBUGGER
        debugger_id = await self._spawn_agent(
            "DEBUGGER",
            f"Analyze test failures and find root cause for artifact {artifact_id}. "
            f"Test output: {test_output}",
            payload,
            artifact_id,
            iteration,
        )
        if not debugger_id:
            return True

        await self._wait_for_agent(debugger_id)
        debugger_output = self._get_agent_output(debugger_id) or ""
        logger.info(
            "AutoCorrection DEBUGGER finished | artifact_id=%s iteration=%d output_len=%d",
            artifact_id,
            iteration,
            len(debugger_output),
        )

        # Step 2 — CODER (uses DEBUGGER findings)
        coder_id = await self._spawn_agent(
            "CODER",
            f"Fix the bugs found by DEBUGGER for artifact {artifact_id}. "
            f"DEBUGGER findings: {debugger_output[:1500]}",
            payload,
            artifact_id,
            iteration,
        )
        if not coder_id:
            return True

        await self._wait_for_agent(coder_id)
        logger.info(
            "AutoCorrection CODER finished | artifact_id=%s iteration=%d",
            artifact_id,
            iteration,
        )

        # Step 3 — TEST_RUNNER_UNIT
        test_runner_id = await self._spawn_agent(
            "TEST_RUNNER_UNIT",
            f"Re-run unit tests for artifact {artifact_id} after fixes applied. "
            f"Previous test output: {test_output}",
            payload,
            artifact_id,
            iteration,
        )
        if not test_runner_id:
            return True

        await self._wait_for_agent(test_runner_id)
        test_runner_output = self._get_agent_output(test_runner_id) or ""
        logger.info(
            "AutoCorrection TEST_RUNNER_UNIT finished | artifact_id=%s iteration=%d output_len=%d",
            artifact_id,
            iteration,
            len(test_runner_output),
        )

        return self._check_still_failing(test_runner_output)

    async def _handle_critical_error(self, payload: dict[str, Any]) -> None:
        artifact_id = payload.get("artifact_id", "unknown")

        while True:
            async with self._lock:
                tracker = self._get_or_create_tracker(artifact_id, "critical_error")
                if tracker.iterations >= MAX_ITERATIONS:
                    reason = "Max auto-correction iterations reached for critical error"
                    break
                tracker.iterations += 1
                self._update_tracker(tracker)
                iteration = tracker.iterations

            still_broken = await self._run_critical_error_iteration(artifact_id, payload, iteration)

            if not still_broken:
                await self._publish_status(
                    "critical_error",
                    artifact_id,
                    iteration,
                    f"Critical error resolved after iteration {iteration}",
                )
                async with self._lock:
                    tracker = self._get_or_create_tracker(artifact_id, "critical_error")
                    tracker.status = "completed"
                    self._update_tracker(tracker)
                return

            async with self._lock:
                tracker = self._get_or_create_tracker(artifact_id, "critical_error")
                if tracker.iterations >= MAX_ITERATIONS:
                    reason = f"Critical error still present after {MAX_ITERATIONS} iterations"
                    break

            await self._publish_status(
                "critical_error",
                artifact_id,
                iteration,
                f"Critical error still present after iteration {iteration}, looping",
            )

        await self._escalate(artifact_id, reason)

    async def _run_critical_error_iteration(
        self, artifact_id: str, payload: dict[str, Any], iteration: int
    ) -> bool:
        """Run one correction iteration for critical errors.

        Returns ``True`` if the error is *still* present after this iteration.
        """
        import backend.core.quality_metrics as qm

        error_report = payload.get("error_report", "N/A")
        project_path = payload.get("project_path", ".")

        before = await qm.measure(project_path)

        # Step 1 — CODER
        coder_id = await self._spawn_agent(
            "CODER",
            f"Fix critical error in artifact {artifact_id}. Error report: {error_report}",
            payload,
            artifact_id,
            iteration,
        )
        if not coder_id:
            return True

        await self._wait_for_agent(coder_id)
        coder_output = self._get_agent_output(coder_id) or ""
        logger.info(
            "AutoCorrection CODER finished | artifact_id=%s iteration=%d",
            artifact_id,
            iteration,
        )

        # Step 2 — OVERSEER monitors the fix
        overseer_id = await self._spawn_agent(
            "OVERSEER",
            f"Oversee fix for critical error in {artifact_id}. CODER output: {coder_output[:1500]}",
            payload,
            artifact_id,
            iteration,
        )
        if overseer_id:
            await self._wait_for_agent(overseer_id)
            logger.info(
                "AutoCorrection OVERSEER finished | artifact_id=%s iteration=%d",
                artifact_id,
                iteration,
            )

        after = await qm.measure(project_path)

        if before is not None and after is not None and qm.should_reject_fix(before, after):
            logger.warning(
                "Fix rejected by quality metrics for artifact %s (iteration %d) — triggering rollback",
                artifact_id,
                iteration,
            )
            await self._trigger_rollback(artifact_id, project_path)
            return True

        # Heuristic: if CODER claims it fixed the issue, assume success
        output_lower = coder_output.lower()
        fixed = any(
            phrase in output_lower
            for phrase in [
                "fixed",
                "resolved",
                "corrected",
                "bug fix applied",
                "error corrected",
            ]
        )
        return not fixed

    async def _trigger_rollback(self, artifact_id: str, project_path: str) -> None:
        """Trigger an automatic rollback when a fix is rejected by quality metrics."""
        try:
            from backend.core.rollback import RollbackManager

            manager = RollbackManager()
            result = await manager.auto_rollback_on_regression(
                artifact_id=artifact_id,
                quality_before={},
                quality_after={},
            )
            logger.info(
                "Rollback triggered for artifact %s | result=%s",
                artifact_id,
                result,
            )
        except Exception:
            logger.exception("Failed to trigger rollback for artifact %s", artifact_id)

    async def _handle_review_completed(self, review_id: str, payload: dict[str, Any]) -> None:
        from backend.core.peer_review import get_peer_review_system

        prs = get_peer_review_system()
        review = await prs.get_review_request(review_id)
        if review is None:
            return
        if review.status != "changes_requested":
            return

        artifact_id = review.artifact_id
        async with self._lock:
            tracker = self._get_or_create_tracker(artifact_id, "review_changes")
            if tracker.iterations >= MAX_ITERATIONS:
                reason = "Max auto-correction iterations reached for review changes"
            else:
                tracker.iterations += 1
                self._update_tracker(tracker)
                iteration = tracker.iterations
                reason = None

        if reason:
            await self._escalate(artifact_id, reason)
            return

        # Fetch review results to get actual comments
        results = await prs.get_review_results(review_id)
        all_comments: list[dict[str, Any]] = []
        for result in results:
            for comment in result.comments:
                all_comments.append(
                    {
                        "reviewer": result.reviewer_agent,
                        "severity": comment.severity,
                        "message": comment.message,
                    }
                )

        comments_str = " | ".join(
            f"{c['reviewer']} ({c['severity']}): {c['message']}" for c in all_comments
        )
        objective = (
            f"Address review changes for {artifact_id} ({review.artifact_type}). "
            f"Review comments: {comments_str or 'N/A'}"
        )
        context: dict[str, Any] = {
            "artifact_id": artifact_id,
            "trigger": "review_changes",
            "review_id": review_id,
            "artifact_type": review.artifact_type,
            "comments": all_comments,
            "iteration": iteration,
        }

        # Spawn agents sequentially
        agent_types: list[str]
        if review.artifact_type == "code":
            agent_types = ["REFACTOR_CLEAN", "CODER"]
        else:
            agent_types = ["REFACTOR_CLEAN"]

        instance_ids: list[str] = []
        for agent_type in agent_types:
            iid = await self._spawn_agent(
                agent_type,
                objective,
                context,
                artifact_id,
                iteration,
            )
            if iid:
                await self._wait_for_agent(iid)
                instance_ids.append(iid)
                logger.info(
                    "AutoCorrection %s finished | artifact_id=%s iteration=%d",
                    agent_type,
                    artifact_id,
                    iteration,
                )

        async with self._lock:
            tracker = self._get_or_create_tracker(artifact_id, "review_changes")
            tracker.agents_spawned.extend(agent_types)
            tracker.status = "completed"
            self._update_tracker(tracker)
            self.active_corrections.setdefault(artifact_id, []).extend(instance_ids)

        await self._publish_status(
            "review_changes",
            artifact_id,
            iteration,
            f"completed {agent_types} ({instance_ids}) for {review.artifact_type}",
        )

    async def _handle_performance_regression(self, payload: dict[str, Any]) -> None:
        artifact_id = payload.get("artifact_id", "unknown")
        async with self._lock:
            tracker = self._get_or_create_tracker(artifact_id, "performance_regression")
            if tracker.iterations >= MAX_ITERATIONS:
                reason = "Max auto-correction iterations reached for performance regression"
            else:
                tracker.iterations += 1
                self._update_tracker(tracker)
                iteration = tracker.iterations
                reason = None

        if reason:
            await self._escalate(artifact_id, reason)
            return

        objective = (
            f"Fix performance regression in artifact {artifact_id}. "
            f"Metrics: {payload.get('metrics', {})}"
        )
        context: dict[str, Any] = {
            "artifact_id": artifact_id,
            "trigger": "performance_regression",
            "metrics": payload.get("metrics", {}),
            "comparison": payload.get("comparison", {}),
            "iteration": iteration,
        }

        instance_id = await self._spawn_agent(
            "REFACTOR_PERFORMANCE",
            objective,
            context,
            artifact_id,
            iteration,
        )
        if instance_id:
            await self._wait_for_agent(instance_id)

        async with self._lock:
            tracker = self._get_or_create_tracker(artifact_id, "performance_regression")
            tracker.agents_spawned.append("REFACTOR_PERFORMANCE")
            tracker.status = "completed"
            self._update_tracker(tracker)
            if instance_id:
                self.active_corrections.setdefault(artifact_id, []).append(instance_id)

        await self._publish_status(
            "performance_regression",
            artifact_id,
            iteration,
            f"completed REFACTOR_PERFORMANCE ({instance_id})",
        )

    # ------------------------------------------------------------------
    # Agent execution helpers
    # ------------------------------------------------------------------

    async def _spawn_agent(
        self,
        agent_type: str,
        objective: str,
        payload: dict[str, Any],
        artifact_id: str,
        iteration: int,
    ) -> str | None:
        """Spawn an agent via the lifecycle manager and return its instance_id."""
        context: dict[str, Any] = {
            **payload,
            "artifact_id": artifact_id,
            "iteration": iteration,
        }
        try:
            instance_id = await self._lifecycle.spawn(
                agent_type,
                objective=objective,
                context=context,
                mission_id=f"auto_fix_{artifact_id}",
            )
            logger.info(
                "AutoCorrection spawned %s | instance_id=%s artifact_id=%s iteration=%d",
                agent_type,
                instance_id,
                artifact_id,
                iteration,
            )
            await self._publish_status(
                payload.get("trigger", "auto_correction"),
                artifact_id,
                iteration,
                f"spawned {agent_type} ({instance_id})",
            )
            return instance_id
        except Exception:
            logger.exception("Failed to spawn %s for %s", agent_type, artifact_id)
            return None

    async def _wait_for_agent(
        self, instance_id: str, timeout: float = AGENT_TIMEOUT_SECONDS
    ) -> None:
        """Poll a single agent instance until it reaches a terminal state."""
        start = time.time()
        while time.time() - start < timeout:
            if self._stop_event is not None and self._stop_event.is_set():
                logger.info("AutoCorrection stop requested while waiting for %s", instance_id)
                return

            instance = self._lifecycle.get_status(instance_id)
            if instance is None:
                logger.warning("Agent instance %s disappeared during monitoring", instance_id)
                return

            if instance.is_terminal():
                logger.info(
                    "AutoCorrection agent finished | instance_id=%s type=%s status=%s",
                    instance_id,
                    instance.agent_type,
                    instance.status,
                )
                return

            # Responsive sleep: wake immediately on stop event
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

        logger.warning(
            "AutoCorrection timeout waiting for agent %s after %.0fs",
            instance_id,
            timeout,
        )
        try:
            await self._lifecycle.abort(instance_id, reason="Auto-correction timeout")
        except Exception:
            logger.warning("Failed to abort lifecycle for %s", instance_id)

    def _get_agent_output(self, instance_id: str) -> str | None:
        """Return the output stored by the lifecycle manager for an instance."""
        instance = self._lifecycle.get_status(instance_id)
        if instance is None:
            return None
        return instance.context.get("output")

    @staticmethod
    def _check_still_failing(test_output: str) -> bool:
        """Heuristic: decide whether test output indicates remaining failures."""
        if not test_output:
            return True
        output_lower = test_output.lower()

        # Strong pass signals — these override generic failure words
        # (e.g. "0 failed" contains "failed" but is clearly a pass)
        strong_pass = [
            "all tests passed",
            "0 failed",
            "0 failures",
            "no failures",
        ]
        if any(p in output_lower for p in strong_pass):
            return False

        # Explicit failure signals
        fail_indicators = [
            "failed",
            "failure",
            "error",
            "tests failed",
            "assertionerror",
        ]
        if any(f in output_lower for f in fail_indicators):
            return True

        # Ambiguous — default to still-failing to be safe
        return True

    # ------------------------------------------------------------------
    # Tracking helpers
    # ------------------------------------------------------------------

    def _get_or_create_tracker(self, artifact_id: str, trigger: str) -> _CorrectionTracker:
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
            if c["artifact_id"] == tracker.artifact_id and c["trigger"] == tracker.trigger:
                c["iterations"] = tracker.iterations
                c["agents_spawned"] = tracker.agents_spawned
                c["status"] = tracker.status
                return

    async def _escalate(self, artifact_id: str, reason: str) -> None:
        """Escalate to META_ANALYZER + OVERSEER.

        This method performs its own I/O (spawning agents and publishing to
        the bus) **without** holding ``self._lock``. The lock is only acquired
        for the brief state mutation on ``active_corrections``.
        """
        logger.warning(
            "Escalating artifact %s to META_ANALYZER + OVERSEER: %s",
            artifact_id,
            reason,
        )

        instance_ids: list[str] = []
        try:
            meta_id = await self._lifecycle.spawn(
                "META_ANALYZER",
                objective=f"Escalated analysis for {artifact_id}: {reason}",
                context={
                    "artifact_id": artifact_id,
                    "reason": reason,
                    "escalation": True,
                },
                mission_id=f"escalation_{artifact_id}",
            )
            instance_ids.append(meta_id)
            logger.info(
                "AutoCorrection spawned META_ANALYZER | instance_id=%s artifact_id=%s",
                meta_id,
                artifact_id,
            )
        except Exception:
            logger.exception("Failed to spawn META_ANALYZER for %s", artifact_id)

        try:
            overseer_id = await self._lifecycle.spawn(
                "OVERSEER",
                objective=f"Oversee escalated fix for {artifact_id}: {reason}",
                context={
                    "artifact_id": artifact_id,
                    "reason": reason,
                    "escalation": True,
                },
                mission_id=f"escalation_{artifact_id}",
            )
            instance_ids.append(overseer_id)
            logger.info(
                "AutoCorrection spawned OVERSEER | instance_id=%s artifact_id=%s",
                overseer_id,
                artifact_id,
            )
        except Exception:
            logger.exception("Failed to spawn OVERSEER for %s", artifact_id)

        async with self._lock:
            self.active_corrections.setdefault(artifact_id, []).extend(instance_ids)

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
                    "spawned_agents": instance_ids,
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
# Singleton accessor
# ──────────────────────────────────────────────────────────────────────────────

_auto_correction_loop_instance: AutoCorrectionLoop | None = None


def get_auto_correction_loop(
    lifecycle_manager: AgentLifecycleManager | None = None,
) -> AutoCorrectionLoop:
    """Return the singleton :class:`AutoCorrectionLoop` instance.

    The first call creates the singleton.  Subsequent calls return the same
    object.  If a ``lifecycle_manager`` is provided it replaces any previously
    stored manager, which is how ``main.py`` wires the real runtime.
    """
    global _auto_correction_loop_instance
    if _auto_correction_loop_instance is None:
        _auto_correction_loop_instance = AutoCorrectionLoop(lifecycle_manager=lifecycle_manager)
    elif lifecycle_manager is not None:
        _auto_correction_loop_instance._lifecycle = lifecycle_manager
    return _auto_correction_loop_instance
