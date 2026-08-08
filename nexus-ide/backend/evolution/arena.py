"""Arena — runs champion-vs-challenger experiments.

FASE 5. The Arena executes side-by-side comparisons of a champion version
against a challenger version, on a set of benchmark tasks sampled from
real traces in the TraceLake or an evaluation harness. Results feed into
the RegressionGuard.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from backend.evolution.registry import (
    ChampionRegistry,
    ComponentVersion,
    Experiment,
    ExperimentStatus,
    _connect,
    _safe_json,
)

logger = logging.getLogger(__name__)


class BenchmarkRunner(Protocol):
    """Protocol for running benchmark tasks against a component version."""

    def run(
        self,
        component_kind: str,
        version: ComponentVersion,
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Run tasks with the given version; return list of results.

        Each result dict should contain at least:
            - task_id: str
            - success: bool
            - score: float (0-1)
            - metrics: dict
            - error: str | None
        """
        ...


class Arena:
    """Runs champion-vs-challenger arena experiments.

    Usage:
        arena = Arena(registry)
        arena.set_runner(my_runner)
        result = arena.run_experiment("planner", "v3", ["task:abc", "task:def"])
    """

    def __init__(
        self,
        registry: ChampionRegistry,
        allow_simulation: bool = False,
    ) -> None:
        self._registry = registry
        self._runner: BenchmarkRunner | None = None
        self._allow_simulation = allow_simulation

    def set_runner(self, runner: BenchmarkRunner) -> None:
        """Set the benchmark runner used to evaluate versions."""
        self._runner = runner

    def run_experiment(
        self,
        component_kind: str,
        challenger_version: str,
        task_ids: list[str],
        experiment_id: str | None = None,
    ) -> Experiment:
        """Run a champion-vs-challenger experiment.

        Args:
            component_kind: Which component (e.g., "planner", "coder", "prompt").
            challenger_version: The version string of the challenger.
            task_ids: List of benchmark task IDs to evaluate.
            experiment_id: Optional explicit experiment ID.

        Returns:
            Experiment with results filled in.
        """
        exp_id = experiment_id or f"exp-{uuid.uuid4().hex[:8]}"
        champion = self._registry.get_champion(component_kind)
        challenger = self._registry.get_version(component_kind, challenger_version)

        if champion is None:
            raise ValueError(f"No champion registered for {component_kind}")
        if challenger is None:
            raise ValueError(f"No version {challenger_version} found for {component_kind}")

        experiment = Experiment(
            experiment_id=exp_id,
            component_kind=component_kind,
            champion_version=champion.version,
            challenger_version=challenger_version,
            status=ExperimentStatus.RUNNING,
            started_at=datetime.now(UTC).isoformat(),
        )

        if self._runner is None:
            if self._allow_simulation:
                logger.warning("No benchmark runner set; using simulated results (opt-in)")
                return self._simulate_experiment(experiment, champion, challenger, task_ids)
            raise RuntimeError(
                "No benchmark runner set for Arena. "
                "Call set_runner() with a BenchmarkRunner, "
                "or pass allow_simulation=True to Arena for testing."
            )

        # Build task specs from trace lake
        tasks = self._load_tasks(task_ids, component_kind)
        if not tasks:
            experiment.status = ExperimentStatus.PENDING
            experiment.log = "No benchmark tasks available"
            return experiment

        # Run champion
        champion_results = self._runner.run(component_kind, champion, tasks)
        challenger_results = self._runner.run(component_kind, challenger, tasks)

        # Compare
        champion_score = self._compute_score(champion_results)
        challenger_score = self._compute_score(challenger_results)
        champion_success = self._compute_success_rate(champion_results)
        challenger_success = self._compute_success_rate(challenger_results)

        # Detect regressions
        reg = self._detect_regression(champion_results, challenger_results)

        experiment.completed_at = datetime.now(UTC).isoformat()
        experiment.regression_detected = reg
        experiment.metrics = {
            "champion_score": champion_score,
            "challenger_score": challenger_score,
            "champion_success": champion_success,
            "challenger_success": challenger_success,
            "num_tasks": len(task_ids),
            "champion_results": champion_results,
            "challenger_results": challenger_results,
        }

        if reg:
            experiment.status = ExperimentStatus.REGRESSION
            experiment.winner = "champion" if champion_score >= challenger_score else "unknown"
            experiment.log = "Regression detected: challenger degraded performance on some tasks"
        elif challenger_score > champion_score:
            experiment.status = ExperimentStatus.COMPLETED
            experiment.winner = "challenger"
            experiment.log = "Challenger outperformed champion"
        elif challenger_score < champion_score:
            experiment.status = ExperimentStatus.COMPLETED
            experiment.winner = "champion"
            experiment.log = "Champion outperformed challenger"
        else:
            experiment.status = ExperimentStatus.COMPLETED
            experiment.winner = "tie"
            experiment.log = "Champion and challenger performed equally"

        self._persist_experiment(experiment)
        return experiment

    def _load_tasks(
        self,
        task_ids: list[str],
        component_kind: str,
    ) -> list[dict[str, Any]]:
        """Load task specs from the trace lake by task_id.

        Uses get_trace() which returns full ExperienceTrace objects
        with all fields including trajectory and result.
        """
        from backend.experience.lake import get_trace_lake

        tasks: list[dict[str, Any]] = []
        trace_lake = get_trace_lake()

        for tid in task_ids:
            trace = trace_lake.get_trace(tid)
            if trace is None:
                tasks.append({
                    "task_id": tid,
                    "prompt": "",
                    "inputs": {},
                    "expected_output": "",
                    "component_kind": component_kind,
                    "task_type": "",
                    "category": "",
                    "trajectory": [],
                })
                continue
            tasks.append({
                "task_id": trace.task_id,
                "prompt": trace.prompt,
                "inputs": trace.to_dict(),
                "expected_output": trace.result.output if trace.result else "",
                "component_kind": str(trace.component_kind) if trace.component_kind else component_kind,
                "task_type": trace.task_type,
                "category": str(trace.category) if trace.category else "",
                "trajectory": [e.model_dump() for e in trace.trajectory],
            })
        return tasks

    def _compute_score(self, results: list[dict[str, Any]]) -> float:
        """Compute average score from results."""
        if not results:
            return 0.0
        return sum(r.get("score", 0.0) for r in results) / len(results)

    def _compute_success_rate(self, results: list[dict[str, Any]]) -> float:
        """Compute success rate from results."""
        if not results:
            return 0.0
        return sum(1 for r in results if r.get("success", False)) / len(results)

    def _detect_regression(
        self,
        champion_results: list[dict[str, Any]],
        challenger_results: list[dict[str, Any]],
    ) -> bool:
        """Check if the challenger regresses on any task the champion solved."""
        champion_by_id = {
            r["task_id"]: r for r in champion_results if "task_id" in r
        }
        for r in challenger_results:
            tid = r.get("task_id")
            if tid is None:
                continue
            champ = champion_by_id.get(tid)
            if champ is None:
                continue
            # Regression: champion succeeded but challenger failed
            if champ.get("success") and not r.get("success"):
                return True
            # Or challenger score significantly lower
            champ_score = champ.get("score", 0)
            chall_score = r.get("score", 0)
            if champ_score > 0 and chall_score < champ_score * 0.5:
                return True
        return False

    def _simulate_experiment(
        self,
        experiment: Experiment,
        champion: ComponentVersion,
        challenger: ComponentVersion,
        task_ids: list[str],
    ) -> Experiment:
        """Generate simulated results for testing without a real benchmark runner."""
        import random as _random

        # Seed with component version for reproducibility
        seed = hash(challenger.id + challenger.version) % (2**32)
        rng = _random.Random(seed)

        num_tasks = len(task_ids) if task_ids else 10
        champion_score = 0.75 + rng.uniform(-0.05, 0.05)
        challenger_score = 0.72 + rng.uniform(-0.10, 0.10)

        champion_results = [
            {"task_id": str(i), "success": rng.random() < champion_score, "score": champion_score}
            for i in range(num_tasks)
        ]
        challenger_results = [
            {"task_id": str(i), "success": rng.random() < challenger_score, "score": challenger_score}
            for i in range(num_tasks)
        ]

        champion_success = sum(1 for r in champion_results if r["success"]) / num_tasks
        challenger_success = sum(1 for r in challenger_results if r["success"]) / num_tasks
        reg = self._detect_regression(champion_results, challenger_results)

        experiment.completed_at = datetime.now(UTC).isoformat()
        experiment.regression_detected = reg
        experiment.metrics = {
            "champion_score": champion_score,
            "challenger_score": challenger_score,
            "champion_success": champion_success,
            "challenger_success": challenger_success,
            "num_tasks": num_tasks,
            "simulated": True,
            "champion_results": champion_results,
            "challenger_results": challenger_results,
        }

        if reg:
            experiment.status = ExperimentStatus.REGRESSION
            experiment.winner = "champion"
            experiment.log = "Simulated: regression detected"
        elif challenger_score > champion_score:
            experiment.status = ExperimentStatus.COMPLETED
            experiment.winner = "challenger"
            experiment.log = "Simulated: challenger outperformed champion"
        elif challenger_score < champion_score:
            experiment.status = ExperimentStatus.COMPLETED
            experiment.winner = "champion"
            experiment.log = "Simulated: champion outperformed challenger"
        else:
            experiment.status = ExperimentStatus.COMPLETED
            experiment.winner = "tie"
            experiment.log = "Simulated: tie"

        self._persist_experiment(experiment)
        return experiment

    def _persist_experiment(self, experiment: Experiment) -> None:
        """Persist experiment to the registry database."""
        conn = _connect(self._registry.db_path)
        try:
            conn.execute("BEGIN")
            conn.execute(
                "INSERT OR REPLACE INTO evolution_experiments "
                "(id, component_kind, champion_version, challenger_version, status, "
                " started_at, completed_at, winner, regression_detected, metrics_json, log) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    experiment.experiment_id,
                    experiment.component_kind,
                    experiment.champion_version,
                    experiment.challenger_version,
                    experiment.status.value,
                    experiment.started_at,
                    experiment.completed_at,
                    experiment.winner,
                    1 if experiment.regression_detected else 0,
                    json.dumps(experiment.metrics),
                    experiment.log,
                ),
            )
            conn.execute(
                "INSERT INTO evolution_log "
                "(id, experiment_id, event_type, component_kind, version, message, metrics_json, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"log-{uuid.uuid4().hex[:8]}",
                    experiment.experiment_id,
                    "experiment_completed",
                    experiment.component_kind,
                    experiment.challenger_version,
                    experiment.log,
                    json.dumps({"winner": experiment.winner, "regression": experiment.regression_detected}),
                    experiment.completed_at or datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def list_experiments(
        self,
        component_kind: str | None = None,
        limit: int = 50,
    ) -> list[Experiment]:
        """List recent experiments from the database."""
        conn = _connect(self._registry.db_path)
        try:
            if component_kind:
                rows = conn.execute(
                    "SELECT * FROM evolution_experiments WHERE component_kind = ? "
                    "ORDER BY started_at DESC LIMIT ?",
                    (component_kind, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM evolution_experiments "
                    "ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        finally:
            conn.close()

        experiments = []
        for row in rows:
            metrics = _safe_json(row["metrics_json"])
            exp = Experiment(
                experiment_id=row["id"],
                component_kind=row["component_kind"],
                champion_version=row["champion_version"],
                challenger_version=row["challenger_version"],
                status=ExperimentStatus(row["status"]),
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                winner=row["winner"],
                regression_detected=bool(row["regression_detected"]),
                metrics=metrics,
                log=row["log"] or "",
            )
            experiments.append(exp)
        return experiments
