"""Autonomous Improvement Orchestrator — unified meta-loop coordinator.

This is the SINGLE entry point that unifies all improvement activities:
- AutoCorrectionLoop (reactive: test failures, critical errors)
- ContinuousImprovementLoop (proactive: periodic analysis)
- SelfHealingEngine (active: applies improvements with quality gates)
- SwarmOrchestrator (parallel execution for complex improvements)
- SelfImprovementLoop (metrics-driven optimization)

Meta-loop: ANALYZE -> PLAN -> EXECUTE -> VERIFY -> LEARN
Priority: critical fixes > performance > refactoring > exploration
NO cross-system budget enforcement — relies on AgentLifecycleManager limits.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.core.agent_bus import BusMessage, get_agent_bus
from backend.core.auto_correction import get_auto_correction_loop
from backend.core.continuous_improvement import get_continuous_improvement_loop
from backend.core.self_healing_engine import SelfHealingEngine
from backend.orchestrator.auto_rollback import AutoRollback
from backend.orchestrator.cycle_checkpoint import CycleCheckpoint, CycleCheckpointStore
from backend.orchestrator.diff_validator import DiffValidator
from backend.orchestrator.events import EventBus
from backend.orchestrator.sandbox_executor import SandboxExecutor
from backend.orchestrator.self_improvement_loop import SelfImprovementLoop
from backend.orchestrator.subagent_checkpoint import SubagentCheckpointStore
from backend.orchestrator.subagent_manager import SubagentManager

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class CycleResult:
    """Persisted result of one improvement cycle."""
    cycle_id: str
    started_at: datetime
    completed_at: datetime | None = None
    proposals_generated: int = 0
    proposals_approved: int = 0
    proposals_applied: int = 0
    proposals_verified: int = 0
    proposals_rejected: int = 0
    regressions_introduced: int = 0
    skills_created: int = 0
    skills_evolved: int = 0
    failures_diagnosed: int = 0
    total_tokens: int = 0
    wall_time_seconds: float = 0.0
    meta_learning_updates: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ImprovementProposal:
    """A proposed improvement with priority and confidence."""
    proposal_id: str
    category: str
    priority: str
    target: str
    problem: str
    proposed_change: str
    confidence: float
    source: str
    estimated_effort: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class AutonomousImprovementOrchestrator:
    """Single coordinator for all autonomous improvement activities.

    Unifies:
    - AutoCorrectionLoop (reactive)
    - ContinuousImprovementLoop (proactive)
    - SelfHealingEngine (active)
    - SwarmOrchestrator (parallel execution)
    - SelfImprovementLoop (metrics)

    Meta-loop: ANALYZE -> PLAN -> EXECUTE -> VERIFY -> LEARN
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        lifecycle_manager: Any | None = None,
        llm_client: Any | None = None,
        registry: dict[str, Any] | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.config = config or {}
        self.lifecycle = lifecycle_manager
        self.llm_client = llm_client
        self.registry = registry or {}
        self.event_bus = event_bus

        self._running = False
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._cycle_history: list[CycleResult] = []
        self._consecutive_failures = 0
        self._last_cycle_started_at: float = 0.0

        self.correction_loop = get_auto_correction_loop(lifecycle_manager=lifecycle_manager)
        self.continuous_loop = get_continuous_improvement_loop()
        self.improvement_loop = SelfImprovementLoop(
            target_metrics=["response_time", "accuracy", "throughput", "success_rate"]
        )

        self_healing_auto_apply = self.config.get("auto_apply", False)
        self.healer = SelfHealingEngine(
            auto_apply=self_healing_auto_apply,
            dry_run=False,
            min_confidence=float(self.config.get("auto_apply_threshold", 0.85)),
            analysis_interval=int(self.config.get("cycle_interval_minutes", 30)) * 60,
        )

        try:
            from backend.orchestrator.swarm import SwarmOrchestrator
            self.swarm = SwarmOrchestrator(
                llm_client=llm_client,
                registry=registry or {},
                event_bus=event_bus,
                max_agents=5,
            )
        except Exception:
            logger.warning("SwarmOrchestrator unavailable; swarm improvements disabled")
            self.swarm = None

        self.knowledge_base: Any | None = None
        self.failure_analyzer: Any | None = None
        self.recovery_strategies: Any | None = None

        try:
            from backend.core.knowledge_base import KnowledgeBase
            self.knowledge_base = KnowledgeBase.get_instance()
        except Exception:
            logger.debug("KnowledgeBase not yet available")

        try:
            from backend.orchestrator.swarm_failure_analyzer import SwarmFailureAnalyzer
            self.failure_analyzer = SwarmFailureAnalyzer()
        except Exception:
            logger.debug("SwarmFailureAnalyzer not yet available")

        try:
            from backend.orchestrator.swarm_recovery import SwarmRecoveryStrategies
            self.recovery_strategies = SwarmRecoveryStrategies()
        except Exception:
            logger.debug("SwarmRecoveryStrategies not yet available")

        self.checkpoint_store = CycleCheckpointStore()
        self.auto_rollback = AutoRollback()
        self.diff_validator = DiffValidator()
        self.sandbox_executor = SandboxExecutor()
        # SubagentRunner was removed: it duplicated SubagentManager with a
        # divergent SubagentResult and was instantiated here but never called.
        # SubagentManager is the single subagent entry point. It now fails
        # fast on a null lifecycle, so when the caller did not inject one we
        # build a real AgentLifecycleManager from the client's dependencies
        # instead of letting phases run against a null LLM client.
        if lifecycle_manager is None:
            from backend.core.agent_lifecycle import AgentLifecycleManager
            lifecycle_manager = AgentLifecycleManager(registry=registry, llm_client=llm_client)
            self.lifecycle = lifecycle_manager
        self.subagent_manager = SubagentManager(
            lifecycle=lifecycle_manager,
            checkpoint_store=SubagentCheckpointStore(),
        )
        self._checkpoint_id: str | None = None

    async def start(self) -> None:
        if self._running:
            logger.warning("AutonomousImprovementOrchestrator already running")
            return
        self._running = True
        self._stop_event.clear()

        await self.correction_loop.start_monitoring()
        await self.continuous_loop.start()
        await self.healer.start()

        self._task = asyncio.create_task(self._run_forever(), name="autonomous-improvement-orchestrator")
        logger.info(
            "AutonomousImprovementOrchestrator started (interval=%sm)",
            self.config.get("cycle_interval_minutes", 30),
        )

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()

        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

        await self.correction_loop.stop_monitoring()
        await self.continuous_loop.stop()
        await self.healer.stop()
        logger.info("AutonomousImprovementOrchestrator stopped")

    async def _run_forever(self) -> None:
        interval_s = int(self.config.get("cycle_interval_minutes", 30)) * 60
        max_concurrent = int(self.config.get("max_concurrent_improvements", 3))

        while self._running:
            try:
                if self._circuit_open():
                    logger.warning("Circuit breaker open; skipping cycle")
                    await asyncio.sleep(60)
                    continue

                async with self._concurrency_semaphore(max_concurrent):
                    await self.run_cycle()
                self._consecutive_failures = 0
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Autonomous improvement cycle failed: %s", exc)
                self._consecutive_failures += 1

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval_s)
                break
            except TimeoutError:
                continue

    def _concurrency_semaphore(self, max_concurrent: int) -> asyncio.Semaphore:
        return asyncio.Semaphore(max(1, max_concurrent))

    async def run_cycle(self) -> CycleResult:
        cycle_id = f"cycle-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        started_at = datetime.now(UTC)
        self._last_cycle_started_at = time.time()
        logger.info("Cycle started | cycle_id=%s", cycle_id)

        await self._emit("improvement.cycle.started", cycle_id, {"cycle_id": cycle_id})

        self._checkpoint_id = None
        checkpoint = self.checkpoint_store.get_latest(cycle_id)
        if checkpoint and not checkpoint.completed:
            logger.info("Resuming from checkpoint | step=%s", checkpoint.step)
            self._checkpoint_id = checkpoint.checkpoint_id
            result = CycleResult(
                cycle_id=cycle_id,
                started_at=started_at,
                proposals_generated=checkpoint.state.get("proposals_generated", 0),
                proposals_approved=checkpoint.state.get("proposals_approved", 0),
                proposals_applied=checkpoint.state.get("proposals_applied", 0),
                proposals_verified=checkpoint.state.get("proposals_verified", 0),
                proposals_rejected=checkpoint.state.get("proposals_rejected", 0),
                regressions_introduced=checkpoint.state.get("regressions_introduced", 0),
                skills_created=checkpoint.state.get("skills_created", 0),
                skills_evolved=checkpoint.state.get("skills_evolved", 0),
                failures_diagnosed=checkpoint.state.get("failures_diagnosed", 0),
                total_tokens=checkpoint.state.get("total_tokens", 0),
                wall_time_seconds=checkpoint.state.get("wall_time_seconds", 0.0),
                meta_learning_updates=checkpoint.state.get("meta_learning_updates", {}),
                error=checkpoint.state.get("error"),
            )
            if result.error:
                result.error = None
                result.completed_at = None
        else:
            result = CycleResult(cycle_id=cycle_id, started_at=started_at)

        try:
            # Plan exactly once per cycle. The previous version re-invoked
            # `_plan()` inside the `approved` expression, which both doubled
            # the cost of planning and referenced `proposals` before
            # assignment whenever an incomplete checkpoint existed (NameError).
            proposals = await self._plan()
            result.proposals_generated = len(proposals)
            self._save_checkpoint(cycle_id, "planned", result)

            approved = [
                p
                for p in proposals
                if p.confidence >= float(self.config.get("auto_apply_threshold", 0.85))
            ]
            result.proposals_approved = len(approved)
            self._save_checkpoint(cycle_id, "approved", result)

            applied = await self._execute(approved)
            result.proposals_applied = len(applied)
            self._save_checkpoint(cycle_id, "executed", result)

            verified = await self._verify(applied)
            result.proposals_verified = len(verified)
            self._save_checkpoint(cycle_id, "verified", result)

            rejected = len(proposals) - len(approved)
            result.proposals_rejected = rejected
            self._save_checkpoint(cycle_id, "learned", result)

            await self._learn(proposals, applied, verified)
        except Exception as exc:
            logger.exception("Cycle %s failed: %s", cycle_id, exc)
            result.error = str(exc)
            self._save_checkpoint(cycle_id, "error", result)

        result.completed_at = datetime.now(UTC)
        result.wall_time_seconds = (result.completed_at - started_at).total_seconds()
        self._cycle_history.append(result)
        self._save_checkpoint(cycle_id, "completed", result, completed=True)
        await self._emit("improvement.cycle.completed", cycle_id, result.__dict__)
        return result

    async def _analyze(self) -> dict[str, Any]:
        analysis: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "correction_status": self.correction_loop.get_status(),
            "improvement_stats": self.continuous_loop.stats.to_dict(),
            "healer_stats": self.healer.status(),
            "loop_stats": self.improvement_loop.stats(),
        }

        if self.knowledge_base:
            try:
                analysis["knowledge_base"] = {
                    "total_patterns": len(getattr(self.knowledge_base, "patterns", {})),
                    "total_signatures": len(getattr(self.knowledge_base, "signatures", {})),
                }
            except Exception:
                pass

        return analysis

    async def _plan(self) -> list[ImprovementProposal]:
        proposals: list[ImprovementProposal] = []

        try:
            report = await self.continuous_loop.run_once(force=True)
            raw = report.get("stats", {})
            last_proposals = raw.get("last_proposals", [])
            for p in last_proposals:
                proposals.append(ImprovementProposal(
                    proposal_id=p.get("id", uuid.uuid4().hex[:12]),
                    category=p.get("category", "unknown"),
                    priority=self._priority_for_category(p.get("category", "")),
                    target=p.get("target", ""),
                    problem=p.get("problem", ""),
                    proposed_change=p.get("proposed_change", ""),
                    confidence=float(p.get("confidence", 0.5)),
                    source="continuous_improvement",
                    estimated_effort="medium",
                ))
        except Exception:
            logger.debug("Continuous improvement proposals unavailable", exc_info=True)

        return self._deduplicate_and_sort(proposals)

    def _priority_for_category(self, category: str) -> str:
        mapping = {
            "bug_fix": "critical",
            "security": "critical",
            "performance": "high",
            "prompt": "medium",
            "tool": "medium",
            "refactor": "low",
            "exploration": "low",
        }
        return mapping.get(category, "medium")

    def _deduplicate_and_sort(self, proposals: list[ImprovementProposal]) -> list[ImprovementProposal]:
        seen: set[str] = set()
        unique: list[ImprovementProposal] = []
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for p in sorted(proposals, key=lambda p: (priority_order.get(p.priority, 99), -p.confidence)):
            key = (p.category, p.target, p.problem)
            if key in seen:
                continue
            seen.add(key)
            unique.append(p)
        return unique

    async def _execute(self, proposals: list[ImprovementProposal]) -> list[ImprovementProposal]:
        applied: list[ImprovementProposal] = []
        checkpoint = self.auto_rollback.create_checkpoint(f"auto: pre-{len(proposals)}-proposals cycle")
        use_subagents = bool(self.config.get("use_subagents", True))
        for proposal in proposals:
            try:
                sandbox_passed = await self.sandbox_executor.run_tests()
                if not sandbox_passed.passed:
                    logger.warning("Sandbox pre-check failed for %s: %s", proposal.proposal_id, sandbox_passed.error)
                    continue

                if use_subagents:
                    result = await self._execute_via_subagents(proposal)
                elif self.swarm and proposal.category in {"refactor", "architecture"}:
                    result = await self._execute_via_swarm(proposal)
                else:
                    result = await self._execute_via_healer(proposal)
                if result:
                    applied.append(proposal)
            except Exception as exc:
                logger.warning("Failed to execute proposal %s: %s", proposal.proposal_id, exc)
                if checkpoint:
                    self.auto_rollback.rollback_to(checkpoint)
        return applied

    async def _execute_via_subagents(self, proposal: ImprovementProposal) -> bool:
        """Run a proposal through the RESEARCH → DESIGN → BUILD → VERIFY phase
        pipeline on the SubagentManager.

        This is the call path that makes the subagent subsystem real: every
        phase gets the registry's token/time budgets, transient-failure
        retries, crash-safe checkpoints, and AgentBus lifecycle events
        (`subagent.<phase>.complete/failed`) that the dashboard consumes.

        Each phase's work is supplied as `fn`, so the manager handles
        budgeting/retries/observability while the actual execution reuses the
        existing swarm/healer machinery.
        """
        mission_id = f"improve-{proposal.proposal_id}"

        research = await self.subagent_manager.run_phase(
            "RESEARCH",
            f"Gather context for improving '{proposal.target}': {proposal.problem}",
            context={"proposal": proposal.__dict__},
            mission_id=mission_id,
            fn=lambda: self._phase_research(proposal),
        )
        if not research.success:
            logger.warning("RESEARCH phase failed for %s: %s", proposal.proposal_id, research.error)
            return False

        design = await self.subagent_manager.run_phase(
            "DESIGN",
            f"Design the change for '{proposal.target}': {proposal.proposed_change}",
            context={"research": research.output},
            mission_id=mission_id,
            fn=lambda: self._phase_design(proposal, research.output),
        )
        if not design.success:
            logger.warning("DESIGN phase failed for %s: %s", proposal.proposal_id, design.error)
            return False

        build = await self.subagent_manager.run_phase(
            "BUILD",
            f"Apply the approved change to '{proposal.target}'",
            context={"design": design.output},
            mission_id=mission_id,
            fn=lambda: self._phase_build(proposal),
        )
        if not build.success:
            logger.warning("BUILD phase failed for %s: %s", proposal.proposal_id, build.error)
            return False

        verify = await self.subagent_manager.run_phase(
            "VERIFY",
            f"Verify the change to '{proposal.target}' against quality gates",
            context={"build": str(build.output)[:2000]},
            mission_id=mission_id,
            fn=self._phase_verify,
        )
        return bool(verify.success and verify.output)

    async def _phase_research(self, proposal: ImprovementProposal) -> dict[str, Any]:
        """Collect the facts a BUILD phase needs: target existence, current
        diff state, and recent failures touching the same target."""
        context: dict[str, Any] = {"target": proposal.target, "problem": proposal.problem}
        target_path = REPO_ROOT / proposal.target if proposal.target else None
        context["target_exists"] = bool(target_path and target_path.exists())
        context["changed_files"] = [str(p) for p in self._get_changed_files()]
        if self.knowledge_base is not None:
            try:
                patterns = getattr(self.knowledge_base, "patterns", {})
                context["related_patterns"] = [
                    pid for pid, pat in list(patterns.items())[:200]
                    if proposal.target and proposal.target in str(pat)
                ][:10]
            except Exception:
                context["related_patterns"] = []
        return context

    async def _phase_design(self, proposal: ImprovementProposal, research: Any) -> dict[str, Any]:
        """Produce the execution plan the BUILD phase will follow."""
        return {
            "change": proposal.proposed_change,
            "category": proposal.category,
            "executor": "swarm" if (self.swarm and proposal.category in {"refactor", "architecture"}) else "healer",
            "research": research,
        }

    async def _phase_build(self, proposal: ImprovementProposal) -> bool:
        if self.swarm and proposal.category in {"refactor", "architecture"}:
            return await self._execute_via_swarm(proposal)
        return await self._execute_via_healer(proposal)

    async def _phase_verify(self) -> bool:
        passed = await self.healer._run_quality_gate()
        if not passed:
            return False
        diff_report = self.diff_validator.validate_files(self._get_changed_files())
        if not diff_report.passed:
            await self.auto_rollback.rollback_last()
            return False
        return True

    async def _execute_via_swarm(self, proposal: ImprovementProposal) -> bool:
        if not self.swarm:
            return False
        try:
            await self.swarm.execute_swarm(
                objective=proposal.proposed_change,
                session_id=f"improve-{proposal.proposal_id}",
                strategy="divide",
            )
            return True
        except Exception:
            logger.debug("Swarm execution failed for %s", proposal.proposal_id, exc_info=True)
            return False

    async def _execute_via_healer(self, proposal: ImprovementProposal) -> bool:
        try:
            from backend.core.self_improvement import ImprovementProposal as SIProposal
            si_proposal = SIProposal(
                id=proposal.proposal_id,
                category=proposal.category,
                target=proposal.target,
                problem=proposal.problem,
                proposed_change=proposal.proposed_change,
                expected_impact="autonomous improvement",
                confidence=proposal.confidence,
            )
            return await self.healer._apply_proposal(si_proposal)
        except Exception:
            logger.debug("Healer execution failed for %s", proposal.proposal_id, exc_info=True)
            return False

    async def _verify(self, proposals: list[ImprovementProposal]) -> list[ImprovementProposal]:
        verified: list[ImprovementProposal] = []
        for proposal in proposals:
            try:
                passed = await self.healer._run_quality_gate()
                if passed:
                    diff_report = self.diff_validator.validate_files(self._get_changed_files())
                    if not diff_report.passed:
                        logger.warning("Diff validation failed for %s: %d issues", proposal.proposal_id, len(diff_report.issues))
                        await self.auto_rollback.rollback_last()
                        continue
                    verified.append(proposal)
                    await self._emit("improvement.verification.passed", proposal.proposal_id, {
                        "proposal_id": proposal.proposal_id,
                    })
                else:
                    await self._emit("improvement.verification.failed", proposal.proposal_id, {
                        "proposal_id": proposal.proposal_id,
                    })
            except Exception:
                logger.debug("Verification failed for %s", proposal.proposal_id, exc_info=True)
        return verified

    def _get_changed_files(self) -> list[Any]:
        try:
            import subprocess
            result = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "diff", "--name-only"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return [Path(REPO_ROOT / f) for f in result.stdout.strip().splitlines() if f]
        except Exception:
            logger.debug("Failed to get changed files", exc_info=True)
        return []

    async def _learn(
        self,
        proposals: list[ImprovementProposal],
        applied: list[ImprovementProposal],
        verified: list[ImprovementProposal],
    ) -> None:
        for proposal in applied:
            try:
                if self.knowledge_base and hasattr(self.knowledge_base, "store_pattern"):
                    self.knowledge_base.store_pattern(
                        pattern_id=proposal.proposal_id,
                        category=proposal.category,
                        trigger_conditions={"target": proposal.target, "problem": proposal.problem},
                        solution_steps=[proposal.proposed_change],
                        confidence=proposal.confidence,
                    )
            except Exception:
                logger.debug("KnowledgeBase learning failed for %s", proposal.proposal_id, exc_info=True)

        if applied:
            try:
                from backend.core.knowledge_base import SkillEvolutionEngine
                engine = SkillEvolutionEngine.get_instance()
                await engine.evolve_skills(applied)
            except Exception:
                logger.debug("Skill evolution failed", exc_info=True)

    def _save_checkpoint(self, cycle_id: str, step: str, result: CycleResult, completed: bool = False) -> None:
        if not self._checkpoint_id:
            checkpoint = CycleCheckpoint(
                checkpoint_id=f"ckpt-{cycle_id}-{step}",
                cycle_id=cycle_id,
                step=step,
                state={
                    "proposals_generated": result.proposals_generated,
                    "proposals_approved": result.proposals_approved,
                    "proposals_applied": result.proposals_applied,
                    "proposals_verified": result.proposals_verified,
                    "proposals_rejected": result.proposals_rejected,
                    "regressions_introduced": result.regressions_introduced,
                    "skills_created": result.skills_created,
                    "skills_evolved": result.skills_evolved,
                    "failures_diagnosed": result.failures_diagnosed,
                    "total_tokens": result.total_tokens,
                    "wall_time_seconds": result.wall_time_seconds,
                    "meta_learning_updates": result.meta_learning_updates,
                    "error": result.error,
                },
                completed=completed,
            )
            self._checkpoint_id = checkpoint.checkpoint_id
        else:
            checkpoint = CycleCheckpoint(
                checkpoint_id=self._checkpoint_id,
                cycle_id=cycle_id,
                step=step,
                state={
                    "proposals_generated": result.proposals_generated,
                    "proposals_approved": result.proposals_approved,
                    "proposals_applied": result.proposals_applied,
                    "proposals_verified": result.proposals_verified,
                    "proposals_rejected": result.proposals_rejected,
                    "regressions_introduced": result.regressions_introduced,
                    "skills_created": result.skills_created,
                    "skills_evolved": result.skills_evolved,
                    "failures_diagnosed": result.failures_diagnosed,
                    "total_tokens": result.total_tokens,
                    "wall_time_seconds": result.wall_time_seconds,
                    "meta_learning_updates": result.meta_learning_updates,
                    "error": result.error,
                },
                completed=completed,
            )
        try:
            self.checkpoint_store.save(checkpoint)
            if completed:
                self.checkpoint_store.mark_completed(checkpoint.checkpoint_id)
        except Exception:
            logger.debug("Checkpoint save failed", exc_info=True)

    def _circuit_open(self) -> bool:
        max_failures = int(self.config.get("circuit_breaker", {}).get("max_failures_per_hour", 5))
        return self._consecutive_failures >= max_failures

    async def _emit(self, topic: str, cycle_id: str, data: dict[str, Any]) -> None:
        try:
            bus = get_agent_bus()
            await bus.publish(
                topic,
                BusMessage(
                    message_id=f"auto-{uuid.uuid4().hex[:12]}",
                    source_agent="AUTONOMOUS_IMPROVEMENT",
                    payload={"cycle_id": cycle_id, **data},
                ),
            )
        except Exception:
            logger.debug("Event emission failed for topic=%s", topic, exc_info=True)

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "total_cycles": len(self._cycle_history),
            "consecutive_failures": self._consecutive_failures,
            "circuit_open": self._circuit_open(),
            "last_cycle_started_at": self._last_cycle_started_at,
            "subagents": self.subagent_manager.get_stats(),
        }


_autonomous_improvement_instance: AutonomousImprovementOrchestrator | None = None


def get_autonomous_improvement_orchestrator(
    config: dict[str, Any] | None = None,
    lifecycle_manager: Any | None = None,
    llm_client: Any | None = None,
    registry: dict[str, Any] | None = None,
    event_bus: EventBus | None = None,
) -> AutonomousImprovementOrchestrator:
    global _autonomous_improvement_instance
    if _autonomous_improvement_instance is None:
        _autonomous_improvement_instance = AutonomousImprovementOrchestrator(
            config=config,
            lifecycle_manager=lifecycle_manager,
            llm_client=llm_client,
            registry=registry,
            event_bus=event_bus,
        )
    return _autonomous_improvement_instance
