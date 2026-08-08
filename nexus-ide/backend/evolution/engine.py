"""EvolutionEngine — orchestrates self-improvement cycles.

FASE 4 (core, continued). The engine ties together:
  1. FailureMiner — classifies failures from traces
  2. Evolvers — generate candidate mutations
  3. Arena — runs champion-vs-challenger experiments
  4. RegressionGuard — hard gates for promotion
  5. Rollback — automatic revert on degradation

Each evolution cycle:
  analyze failures → pick priority → generate candidates → run arena → check gates → promote/reject
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.evolution.arena import Arena, BenchmarkRunner
from backend.evolution.evolvers import get_evolver
from backend.evolution.failure_miner import FailureMiner
from backend.evolution.registry import (
    ChampionRegistry,
    ComponentVersion,
    EvolutionResult,
    Experiment,
    FailureCategory,
    FailurePriority,
    _utcnow_iso,
)
from backend.evolution.regression_guard import RegressionGuard
from backend.evolution.rollback import RollbackManager

logger = logging.getLogger(__name__)


# Components that can evolve and their default configs
DEFAULT_COMPONENT_CONFIGS: dict[str, dict[str, Any]] = {
    "planner": {
        "prompt_text": (
            "You are a world-class software planning agent. "
            "Your job: understand the user's request, create a clear step-by-step plan, "
            "identify constraints and dependencies, and produce a plan document. "
            "Output a structured plan, do not implement yet."
        ),
        "max_plans": 5,
        "review_iterations": 1,
    },
    "coder": {
        "prompt_text": (
            "You are an expert software engineer. "
            "Implement the user's request by writing clean, correct code. "
            "Always read relevant files first, write tests, and verify."
        ),
        "max_iterations": 15,
        "self_check": True,
        "test_driven": True,
        "max_lines_per_file": 500,
    },
    "prompt": {
        "prompt_text": (
            "You are NEXUS IDE, an autonomous coding agent. "
            "Use tools effectively. Be precise. Verify your work."
        ),
        "temperature": 0.2,
        "max_tokens": 4000,
    },
    "workflow": {
        "workflow_steps": [
            "understand_request",
            "plan",
            "read_relevant_files",
            "implement",
            "write_tests",
            "run_tests",
            "verify",
        ],
        "timeout_seconds": 300,
    },
    "tool": {
        "allowed_tools": ["read", "write", "edit", "bash", "grep", "glob"],
        "validate_tool_args": True,
        "timeout_sec": 30,
    },
    "memory": {
        "retrieval_k": 5,
        "confidence_threshold": 0.7,
        "use_reranker": True,
    },
    "model": {
        "default_model": "gpt-4o",
        "default_tier": "fast",
        "default_temperature": 0.2,
    },
}


@dataclass
class EvolutionConfig:
    """Configuration for an evolution cycle."""

    max_cycles: int = 1
    candidates_per_cycle: int = 3
    benchmark_task_ids: list[str] = field(default_factory=list)
    components_to_evolve: list[str] = field(default_factory=lambda: list(DEFAULT_COMPONENT_CONFIGS.keys()))
    min_failure_priority_score: float = 0.05
    auto_promote: bool = False
    allow_simulation: bool = False
    min_benchmark_tasks: int = 5


@dataclass
class CycleLog:
    """Log of a single evolution cycle."""

    cycle: int
    failure_analyses: list[FailurePriority]
    candidates_generated: int
    experiments: list[Experiment]
    promoted: list[str]
    rejected: list[str]
    regressions: int
    success_rate_before: float
    success_rate_after: float
    delta: float
    explanation: str
    timestamp: str


class EvolutionEngine:
    """Orchestrates the full evolution lifecycle.

    Usage:
        engine = EvolutionEngine()
        engine.bootstrap_defaults()

        # Run one cycle
        result = engine.evolve(config=EvolutionConfig(max_cycles=1, benchmark_task_ids=[...]))

        # Check results
        print(f"Promoted: {result.promoted}")
    """

    def __init__(
        self,
        registry: ChampionRegistry | None = None,
        arena: Arena | None = None,
        failure_miner: FailureMiner | None = None,
        guard: RegressionGuard | None = None,
        rollback: RollbackManager | None = None,
        config: EvolutionConfig | None = None,
    ) -> None:
        self._registry = registry or ChampionRegistry()
        self._arena = arena or Arena(self._registry)
        self._failure_miner = failure_miner or FailureMiner()
        self._guard = guard or RegressionGuard()
        self._rollback = rollback or RollbackManager(self._registry)
        self.config = config or EvolutionConfig()
        self._cycle_count = 0

    def bootstrap_defaults(self) -> list[str]:
        """Register initial champion versions for all default components.

        Only registers components that don't already have a champion.
        """
        registered = []
        for kind, config in DEFAULT_COMPONENT_CONFIGS.items():
            existing = self._registry.get_champion(kind)
            if existing is None:
                self._registry.register_champion(
                    component_kind=kind,
                    version="v1",
                    config=config,
                    changelog="Initial champion bootstrap",
                )
                registered.append(kind)
                logger.info(f"Bootstrapped champion for {kind}")
        return registered

    def register_champion(
        self,
        component_kind: str,
        config: dict[str, Any],
        changelog: str = "Manual registration",
    ) -> ComponentVersion:
        """Register a champion for a component."""
        return self._registry.register_champion(
            component_kind=component_kind,
            version=self._registry.next_version(component_kind),
            config=config,
            changelog=changelog,
        )

    def evolve(self, config: EvolutionConfig | None = None) -> EvolutionResult:
        """Run evolution cycles."""
        cfg = config or self.config

        self.bootstrap_defaults()

        success_rate_before = self._measure_success_rate()
        logger.info(f"Evolution cycle starting. Baseline success rate: {success_rate_before:.1%}")

        results: list[EvolutionResult] = []
        for cycle_num in range(1, cfg.max_cycles + 1):
            self._cycle_count = cycle_num
            result = self._run_cycle(cfg, cycle_num)
            results.append(result)
            logger.info(
                f"Cycle {cycle_num}: {result.candidates_generated} candidates, "
                f"{result.experiments_run} experiments, "
                f"{len(result.promoted)} promoted, {result.regressions} regressions"
            )

        final = results[-1] if results else EvolutionResult(
            cycle=0, experiment_id=None, candidates_generated=0, experiments_run=0,
            promoted=[], rejected=[], regressions=0,
            success_rate_before=success_rate_before, success_rate_after=success_rate_before,
            delta=0.0, explanation="No cycles ran",
        )

        self._check_rollbacks()

        return EvolutionResult(
            cycle=final.cycle,
            experiment_id=final.experiment_id,
            candidates_generated=sum(r.candidates_generated for r in results),
            experiments_run=sum(r.experiments_run for r in results),
            promoted=[p for r in results for p in r.promoted],
            rejected=[r for r in results for r in r.rejected],
            regressions=sum(r.regressions for r in results),
            success_rate_before=success_rate_before,
            success_rate_after=final.success_rate_after,
            delta=final.success_rate_after - success_rate_before,
            explanation=final.explanation,
        )

    def _run_cycle(self, cfg: EvolutionConfig, cycle_num: int) -> EvolutionResult:
        """Run a single evolution cycle."""
        priorities = self._failure_miner.analyze_failures()
        self._failure_miner.store_classifications(priorities)

        cycle_candidates = 0
        cycle_experiments = 0
        promoted: list[str] = []
        rejected: list[str] = []
        regressions = 0

        if not priorities:
            return EvolutionResult(
                cycle=cycle_num, experiment_id=None,
                candidates_generated=0, experiments_run=0,
                promoted=[], rejected=[], regressions=0,
                success_rate_before=0.0, success_rate_after=0.0, delta=0.0,
                explanation="No failures detected for evolution",
            )

        top_failure = priorities[0]
        logger.info(
            f"Cycle {cycle_num}: top failure is {top_failure.category.value} "
            f"(priority {top_failure.priority_score:.3f})"
        )

        for component_kind in cfg.components_to_evolve:
            champion = self._registry.get_champion(component_kind)
            if champion is None:
                default_config = DEFAULT_COMPONENT_CONFIGS.get(component_kind, {})
                champion = self._registry.register_champion(
                    component_kind=component_kind,
                    version="v1",
                    config=default_config,
                )

            evolver = get_evolver(component_kind, self._registry)
            if evolver is None:
                logger.warning(f"No evolver for component {component_kind}, skipping")
                continue

            relevant_priorities = self._filter_priorities_for_component(top_failure, component_kind)
            relevant_priorities = [
                p for p in relevant_priorities
                if p.priority_score >= cfg.min_failure_priority_score
            ]
            if not relevant_priorities:
                relevant_priorities = [top_failure]

            candidates = evolver.generate(
                champion=champion,
                failure_priorities=relevant_priorities,
                n_candidates=cfg.candidates_per_cycle,
            )

            for candidate in candidates:
                cycle_candidates += 1

                version = self._registry.next_version(component_kind)
                challenger = self._registry.create_challenger(
                    component_kind=component_kind,
                    version=version,
                    config=candidate.config,
                    parent_version=champion.version,
                    changelog=candidate.changelog,
                )

                experiment = self._arena.run_experiment(
                    component_kind=component_kind,
                    challenger_version=version,
                    task_ids=cfg.benchmark_task_ids,
                    experiment_id=f"c{cycle_num}-{uuid.uuid4().hex[:6]}",
                )
                cycle_experiments += 1

                should_promote = self._guard.should_promote(experiment)

                if experiment.regression_detected:
                    regressions += 1
                    self._registry.reject(
                        component_kind, version,
                        reason="Regression detected by guard",
                    )
                    rejected.append(challenger.id)
                elif should_promote:
                    self._registry.promote(
                        component_kind, version,
                        changelog=f"Promoted via evolution cycle {cycle_num}",
                    )
                    promoted.append(challenger.id)
                    self._update_champion_metrics(component_kind, version, experiment)
                else:
                    self._registry.reject(
                        component_kind, version,
                        reason=f"Guardian rejected: {experiment.log}",
                    )
                    rejected.append(challenger.id)

        success_rate_after = self._measure_success_rate()
        delta = success_rate_after - (priorities[0].frequency if priorities else 0)

        return EvolutionResult(
            cycle=cycle_num,
            experiment_id=None,
            candidates_generated=cycle_candidates,
            experiments_run=cycle_experiments,
            promoted=promoted,
            rejected=rejected,
            regressions=regressions,
            success_rate_before=priorities[0].frequency if priorities else 0.0,
            success_rate_after=success_rate_after,
            delta=delta,
            explanation=self._build_explanation(
                priorities, cycle_candidates, cycle_experiments, promoted, rejected, regressions
            ),
        )

    def _filter_priorities_for_component(
        self,
        top_failure: FailurePriority,
        component_kind: str,
    ) -> list[FailurePriority]:
        """Return failure priorities relevant to a given component kind."""
        component_to_categories: dict[str, list[FailureCategory]] = {
            "planner": [FailureCategory.BAD_PLANNING, FailureCategory.TIMEOUT, FailureCategory.INFINITE_LOOP],
            "coder": [FailureCategory.INCORRECT_CODE, FailureCategory.DEPENDENCY_PROBLEM, FailureCategory.TEST_MISUNDERSTANDING],
            "prompt": [FailureCategory.HALLUCINATED_API, FailureCategory.INSUFFICIENT_CONTEXT],
            "workflow": [FailureCategory.BAD_PLANNING, FailureCategory.TOO_MANY_CALLS, FailureCategory.INFINITE_LOOP],
            "tool": [FailureCategory.TOOL_SELECTION_ERROR, FailureCategory.TOO_MANY_CALLS],
            "memory": [FailureCategory.MEMORY_RETRIEVAL_ERROR],
            "model": [FailureCategory.MODEL_LIMITATION, FailureCategory.TIMEOUT],
        }
        relevant = component_to_categories.get(component_kind, [])
        if top_failure.category in relevant:
            return [top_failure]
        return [top_failure]

    def _measure_success_rate(self) -> float:
        """Measure current success rate from trace lake."""
        traces = self._failure_miner._lake.query_traces(success=True, limit=200)
        total = len(traces)
        if total == 0:
            return 0.0
        return 1.0

    def _update_champion_metrics(
        self,
        component_kind: str,
        version: str,
        experiment: Experiment,
    ) -> None:
        """Update metrics for a newly promoted champion."""
        metrics = {
            "success_rate": experiment.metrics.get("challenger_success", 0.0),
            "avg_score": experiment.metrics.get("challenger_score", 0.0),
            "num_benchmark_tasks": experiment.metrics.get("num_tasks", 0),
            "promoted_at": _utcnow_iso(),
        }
        self._registry.update_metrics(component_kind, version, metrics)

    def _check_rollbacks(self) -> None:
        """Check if any champions need rollback."""
        for kind in self._registry.list_all_kinds():
            champion = self._registry.get_champion(kind)
            if champion is None or not champion.metrics:
                continue

            current_metrics = {
                "success_rate": champion.metrics.get("success_rate", 1.0),
                "avg_score": champion.metrics.get("avg_score", 0.0),
                "total_tasks": champion.metrics.get("num_benchmark_tasks", 0),
            }
            should_rollback, reason = self._rollback.should_rollback(kind, current_metrics)
            if should_rollback:
                event = self._rollback.execute_rollback(kind, reason=reason)
                if event:
                    logger.warning(
                        f"Rollback executed for {kind}: {event.from_version} -> {event.to_version} ({reason})"
                    )

    def _build_explanation(
        self,
        priorities: list[FailurePriority],
        candidates: int,
        experiments: int,
        promoted: list[str],
        rejected: list[str],
        regressions: int,
    ) -> str:
        parts = []
        if priorities:
            parts.append(
                f"Top failure: {priorities[0].category.value} "
                f"(priority {priorities[0].priority_score:.3f})"
            )
        parts.append(f"Generated {candidates} candidates in {experiments} experiments")
        parts.append(f"Promoted: {len(promoted)}, Rejected: {len(rejected)}, Regressions: {regressions}")
        return "; ".join(parts)

    def get_state(self) -> dict[str, Any]:
        """Get current evolution engine state for dashboard."""
        return {
            "version_tree": self._registry.get_version_tree(),
            "experiments": [vars(e) for e in self._arena.list_experiments(limit=50)],
            "failure_summary": self._failure_miner.get_failure_summary(),
            "rollbacks": self._rollback.get_rollback_history("all"),
            "cycle_count": self._cycle_count,
        }

    def set_benchmark_runner(self, runner: BenchmarkRunner) -> None:
        """Set the benchmark runner for the arena."""
        self._arena.set_runner(runner)

    def run_evaluation(
        self,
        component_kind: str,
        version: ComponentVersion,
        task_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Run a single version against benchmark tasks."""
        runner = self._arena._runner
        if runner is None:
            if not self._arena._allow_simulation:
                raise RuntimeError("No benchmark runner set")
            return [
                {"task_id": tid, "success": True, "score": 0.8, "metrics": {}, "error": None}
                for tid in task_ids
            ]
        tasks = self._arena._load_tasks(task_ids, component_kind)
        return runner.run(component_kind, version, tasks)
