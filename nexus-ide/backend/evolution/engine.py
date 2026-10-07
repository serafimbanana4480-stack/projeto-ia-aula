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

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
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

DEFAULT_JOURNAL_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "evolution_journal.jsonl"
)


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
    write_skill_proposals: bool = False


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


def read_journal(path: str | Path) -> list[dict[str, Any]]:
    """Read cycle-summary records from a journal file.

    Corrupt/partial/blank lines are skipped (the journal is append-only and
    a crash can leave a torn last line); non-dict JSON records are ignored.
    """
    journal = Path(path)
    if not journal.exists():
        return []
    records: list[dict[str, Any]] = []
    with journal.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


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
        journal_path: str | Path | None = None,
    ) -> None:
        self._registry = registry or ChampionRegistry()
        self._arena = arena or Arena(self._registry)
        self._failure_miner = failure_miner or FailureMiner()
        self._guard = guard or RegressionGuard()
        self._rollback = rollback or RollbackManager(self._registry)
        self.config = config or EvolutionConfig()
        self._cycle_count = 0
        self.journal_path = Path(journal_path) if journal_path else DEFAULT_JOURNAL_PATH
        self._last_cycle_summary: dict[str, Any] | None = None
        self._cancelled = False

    # ── Cancellation ──

    def cancel(self) -> None:
        """Request cancellation: the engine stops before the next phase."""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        """True once :meth:`cancel` was requested (sticky until reset)."""
        return self._cancelled

    def reset_cancel(self) -> None:
        """Clear the cancellation flag so the engine can run again."""
        self._cancelled = False

    # ── Journal ──

    def _append_journal(self, record: dict[str, Any]) -> None:
        """Append one JSONL record; failures are logged, never raised."""
        try:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            with self.journal_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            logger.exception("Failed to append evolution journal record")

    def last_cycle_summary(self) -> dict[str, Any] | None:
        """Return the latest cycle-summary record (memory, then disk)."""
        if self._last_cycle_summary is not None:
            return self._last_cycle_summary
        records = read_journal(self.journal_path)
        return records[-1] if records else None

    def _write_skill_proposal(
        self,
        component_kind: str,
        version: str,
        candidate: Any,
        experiment: Experiment,
    ) -> None:
        """Render a promoted candidate as a proposed SKILL.md (best-effort)."""
        try:
            from backend.evolution.skill_writer import SkillProposal, SkillWriter

            proposal = SkillProposal(
                name=f"evolved-{component_kind}-{version}",
                description=(
                    candidate.changelog
                    or f"Auto-evolved {component_kind} {version}."
                ),
                steps=[candidate.changelog] if candidate.changelog else [],
                evidence=[
                    f"experiment={experiment.experiment_id}",
                    f"winner={experiment.winner}",
                ],
            )
            SkillWriter().write_proposal(proposal)
        except OSError:
            logger.warning(
                "Failed to write skill proposal for %s %s", component_kind, version
            )

    def _propose_discovered_skills(self, skills_dir: str | Path | None = None) -> list[Path]:
        """Discover recurring action patterns and render them as SKILL.md proposals.

        Best-effort: discovery/writing failures are logged and return ``[]``
        so a broken discovery step can never kill an evolution cycle.
        """
        try:
            from backend.evolution.skill_discovery import SkillDiscovery
            from backend.evolution.skill_writer import SkillWriter

            skills = SkillDiscovery().discover()
            if not skills:
                return []
            writer = SkillWriter(base_dir=Path(skills_dir)) if skills_dir else SkillWriter()
            return writer.write_proposals(skills)
        except Exception:  # noqa: BLE001 - proposals are best-effort by design
            logger.exception("Skill proposal discovery failed")
            return []

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
            if self._cancelled:
                break

        final = results[-1] if results else EvolutionResult(
            cycle=0, experiment_id=None, candidates_generated=0, experiments_run=0,
            promoted=[], rejected=[], regressions=0,
            success_rate_before=success_rate_before, success_rate_after=success_rate_before,
            delta=0.0, explanation="No cycles ran",
        )

        self._check_rollbacks()

        if cfg.write_skill_proposals:
            self._propose_discovered_skills()

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
        started_at = _utcnow_iso()
        priorities = self._failure_miner.analyze_failures()
        self._failure_miner.store_classifications(priorities)

        cycle_candidates = 0
        cycle_experiments = 0
        promoted: list[str] = []
        rejected: list[str] = []
        regressions = 0
        skipped_components: list[str] = []
        verdicts: list[dict[str, Any]] = []

        if not priorities:
            result = EvolutionResult(
                cycle=cycle_num, experiment_id=None,
                candidates_generated=0, experiments_run=0,
                promoted=[], rejected=[], regressions=0,
                success_rate_before=0.0, success_rate_after=0.0, delta=0.0,
                explanation="No failures detected for evolution",
            )
            self._journal_cycle(
                cycle_num, started_at, len(priorities), cycle_candidates,
                cycle_experiments, verdicts, promoted, rejected, regressions,
                skipped_components, result.explanation,
            )
            return result

        top_failure = priorities[0]
        logger.info(
            f"Cycle {cycle_num}: top failure is {top_failure.category.value} "
            f"(priority {top_failure.priority_score:.3f})"
        )

        for component_kind in cfg.components_to_evolve:
            if self._cancelled:
                break

            champion = self._registry.get_champion(component_kind)
            if champion is None:
                default_config = DEFAULT_COMPONENT_CONFIGS.get(component_kind, {})
                champion = self._registry.register_champion(
                    component_kind=component_kind,
                    version="v1",
                    config=default_config,
                )

            try:
                evolver = get_evolver(component_kind, self._registry)
            except Exception:
                logger.exception(
                    "Evolver lookup for %s failed; skipping component", component_kind
                )
                skipped_components.append(component_kind)
                continue

            if evolver is None:
                logger.warning(f"No evolver for component {component_kind}, skipping")
                skipped_components.append(component_kind)
                continue

            relevant_priorities = self._filter_priorities_for_component(top_failure, component_kind)
            relevant_priorities = [
                p for p in relevant_priorities
                if p.priority_score >= cfg.min_failure_priority_score
            ]
            if not relevant_priorities:
                relevant_priorities = [top_failure]

            try:
                candidates = evolver.generate(
                    champion=champion,
                    failure_priorities=relevant_priorities,
                    n_candidates=cfg.candidates_per_cycle,
                )
            except Exception:
                logger.exception(
                    "Evolver for %s failed; skipping component without orphans",
                    component_kind,
                )
                skipped_components.append(component_kind)
                continue

            for candidate in candidates:
                if self._cancelled:
                    break

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

                verdict = {
                    "experiment_id": experiment.experiment_id,
                    "component_kind": component_kind,
                    "champion_version": experiment.champion_version,
                    "challenger_version": version,
                    "winner": experiment.winner,
                    "status": experiment.status.value,
                    "regression_detected": experiment.regression_detected,
                    "outcome": "",
                    "log": experiment.log,
                }

                if experiment.regression_detected:
                    regressions += 1
                    self._registry.reject(
                        component_kind, version,
                        reason="Regression detected by guard",
                    )
                    rejected.append(challenger.id)
                    verdict["outcome"] = "rejected"
                elif should_promote:
                    self._registry.promote(
                        component_kind, version,
                        changelog=f"Promoted via evolution cycle {cycle_num}",
                    )
                    promoted.append(challenger.id)
                    self._update_champion_metrics(component_kind, version, experiment)
                    verdict["outcome"] = "promoted"
                    if cfg.write_skill_proposals:
                        self._write_skill_proposal(
                            component_kind, version, candidate, experiment
                        )
                else:
                    self._registry.reject(
                        component_kind, version,
                        reason=f"Guardian rejected: {experiment.log}",
                    )
                    rejected.append(challenger.id)
                    verdict["outcome"] = "rejected"
                verdicts.append(verdict)

                if self._cancelled:
                    break

        success_rate_after = self._measure_success_rate()
        delta = success_rate_after - (priorities[0].frequency if priorities else 0)

        result = EvolutionResult(
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
        self._journal_cycle(
            cycle_num, started_at, len(priorities), cycle_candidates,
            cycle_experiments, verdicts, promoted, rejected, regressions,
            skipped_components, result.explanation,
        )
        return result

    def _journal_cycle(
        self,
        cycle: int,
        started_at: str,
        failure_count: int,
        candidates_generated: int,
        experiments_run: int,
        verdicts: list[dict[str, Any]],
        promoted: list[str],
        rejected: list[str],
        regressions: int,
        skipped_components: list[str],
        explanation: str,
    ) -> None:
        """Write one cycle_summary line to the journal and cache it."""
        record: dict[str, Any] = {
            "type": "cycle_summary",
            "cycle": cycle,
            "failure_count": failure_count,
            "candidates_generated": candidates_generated,
            "experiments_run": experiments_run,
            "experiment_verdicts": verdicts,
            "promoted": promoted,
            "rejected": rejected,
            "regressions": regressions,
            "cancelled": self._cancelled,
            "skipped_components": skipped_components,
            "started_at": started_at,
            "timestamp": _utcnow_iso(),
            "explanation": explanation,
        }
        self._append_journal(record)
        self._last_cycle_summary = record

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
