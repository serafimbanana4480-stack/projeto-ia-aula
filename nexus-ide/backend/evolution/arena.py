"""Arena — runs champion-vs-challenger experiments.

FASE 5. The Arena executes side-by-side comparisons of a champion version
against a challenger version, on a set of benchmark tasks sampled from
real traces in the TraceLake or an evaluation harness. Results feed into
the RegressionGuard.

FASE 18 statistical rules:
- Task scores are normalized to [0, 1] before aggregation.
- The decision uses per-task win rate with a minimum sample size guard
  (``min_samples``, default 5): fewer paired tasks => INCONCLUSIVE.
- Declaring a WIN requires a win rate >= 0.6 (configurable); ties are
  counted in the denominator. A per-task breakdown is exposed under
  ``experiment.metrics["task_breakdown"]``.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
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

DEFAULT_MIN_SAMPLES = 5
DEFAULT_WIN_RATE_THRESHOLD = 0.6


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
            - score: float (normalized to [0, 1] by the Arena before use)
            - metrics: dict
            - error: str | None

        Optional keys per result:
            - score_max / scale: positive number declaring the raw score's
              scale (e.g. 100 for percentages); the Arena divides by it.
        """
        ...


@dataclass
class InMemoryBenchmarkRunner:
    """Deterministic in-memory ``BenchmarkRunner`` — no LLM or network required.

    Maps ``task_id`` to a score entry applied for every evaluated version.
    Entries may be:

    - a plain ``float`` (same score regardless of version), or
    - a callable ``(version) -> float`` so one table can encode per-version
      behaviour, e.g. ``{"t1": lambda v: 0.9 if v.version == "v2" else 0.5}``.

    Scores are clamped to [0, 1]; ``success`` is ``score >= success_threshold``.
    Unknown task IDs fall back to ``default_score``. Intended for tests and
    offline experiments via ``Arena.set_runner(InMemoryBenchmarkRunner(...))``.
    """

    task_scores: dict[str, float | Callable[[ComponentVersion], float]] = field(
        default_factory=dict,
    )
    default_score: float = 0.0
    success_threshold: float = 0.65

    def run(
        self,
        component_kind: str,
        version: ComponentVersion,
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Score each task from the in-memory table."""
        results: list[dict[str, Any]] = []
        for task in tasks:
            task_id = str(task.get("task_id"))
            entry = self.task_scores.get(task_id, self.default_score)
            raw = entry(version) if callable(entry) else entry
            score = min(1.0, max(0.0, _coerce_score(raw)))
            success = score >= self.success_threshold
            results.append({
                "task_id": task_id,
                "success": success,
                "score": score,
                "metrics": {},
                "error": None if success else f"score {score:.2f} below success threshold",
            })
        return results


def _coerce_score(raw: Any) -> float:
    """Coerce a raw score value to float; non-numeric values become 0.0."""
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _normalize_scores(
    results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """Return copies of *results* with ``score`` normalized to [0, 1].

    A per-result ``score_max``/``scale`` hint (if present and positive) divides
    the raw value. Otherwise, when every raw score in the batch exceeds 1.0,
    scores are assumed percentage-like (0-100) and divided by 100. Remaining
    values are clamped into [0, 1]. The original raw value is preserved under
    ``raw_score``. Returns ``(normalized_copies, rescaled_flag)``.
    """
    raws = [_coerce_score(r.get("score")) for r in results]
    rescale = bool(raws) and all(raw > 1.0 for raw in raws)
    normalized: list[dict[str, Any]] = []
    for result, raw in zip(results, raws, strict=True):
        item = dict(result)
        item["raw_score"] = raw
        hint = result.get("score_max") or result.get("scale")
        if isinstance(hint, (int, float)) and not isinstance(hint, bool) and hint > 0:
            value = raw / float(hint)
        elif rescale:
            value = raw / 100.0
        else:
            value = raw
        item["score"] = min(1.0, max(0.0, value))
        normalized.append(item)
    return normalized, rescale


def _build_task_breakdown(
    champion_results: list[dict[str, Any]],
    challenger_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pair results by task_id into a per-task win/loss/tie breakdown.

    Tasks present on only one side count as a win for the side that ran them
    (the other side is scored 0.0). Exact score equality counts as a tie.
    """
    champ_by_id = {
        r["task_id"]: r for r in champion_results if r.get("task_id") is not None
    }
    chall_by_id = {
        r["task_id"]: r for r in challenger_results if r.get("task_id") is not None
    }
    ordered_ids: list[Any] = []
    seen: set[Any] = set()
    for r in (*champion_results, *challenger_results):
        tid = r.get("task_id")
        if tid is not None and tid not in seen:
            seen.add(tid)
            ordered_ids.append(tid)

    breakdown: list[dict[str, Any]] = []
    for tid in ordered_ids:
        champ = champ_by_id.get(tid)
        chall = chall_by_id.get(tid)
        champ_score = float(champ["score"]) if champ else 0.0
        chall_score = float(chall["score"]) if chall else 0.0
        if chall_score > champ_score:
            task_winner = "challenger"
        elif chall_score < champ_score:
            task_winner = "champion"
        else:
            task_winner = "tie"
        breakdown.append({
            "task_id": tid,
            "champion_score": champ_score,
            "challenger_score": chall_score,
            "champion_success": bool(champ.get("success")) if champ else False,
            "challenger_success": bool(chall.get("success")) if chall else False,
            "winner": task_winner,
        })
    return breakdown


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
        min_samples: int = DEFAULT_MIN_SAMPLES,
        win_rate_threshold: float = DEFAULT_WIN_RATE_THRESHOLD,
    ) -> None:
        self._registry = registry
        self._runner: BenchmarkRunner | None = None
        self._allow_simulation = allow_simulation
        self._min_samples = max(1, int(min_samples))
        self._win_rate_threshold = min(1.0, max(0.0, float(win_rate_threshold)))

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

        return self._finalize(experiment, champion_results, challenger_results)

    def _finalize(
        self,
        experiment: Experiment,
        champion_results: list[dict[str, Any]],
        challenger_results: list[dict[str, Any]],
        *,
        simulated: bool = False,
    ) -> Experiment:
        """Normalize scores, build the per-task breakdown and decide the outcome.

        Decision rules (in order):
        1. Regression detected => status REGRESSION (champion kept).
        2. Fewer than ``min_samples`` paired tasks => INCONCLUSIVE.
        3. Win rate >= ``win_rate_threshold`` (ties counted) declares a winner;
           otherwise the outcome is a tie.
        """
        champ_norm, _champ_rescaled = _normalize_scores(champion_results)
        chall_norm, _chall_rescaled = _normalize_scores(challenger_results)
        breakdown = _build_task_breakdown(champ_norm, chall_norm)

        total = len(breakdown)
        challenger_wins = sum(1 for b in breakdown if b["winner"] == "challenger")
        champion_wins = sum(1 for b in breakdown if b["winner"] == "champion")
        ties = total - challenger_wins - champion_wins
        challenger_win_rate = challenger_wins / total if total else 0.0
        champion_win_rate = champion_wins / total if total else 0.0

        champion_score = self._compute_score(champ_norm)
        challenger_score = self._compute_score(chall_norm)
        champion_success = self._compute_success_rate(champ_norm)
        challenger_success = self._compute_success_rate(chall_norm)

        reg = self._detect_regression(champ_norm, chall_norm)
        prefix = "Simulated: " if simulated else ""

        experiment.completed_at = datetime.now(UTC).isoformat()
        experiment.regression_detected = reg
        experiment.metrics = {
            "champion_score": champion_score,
            "challenger_score": challenger_score,
            "champion_success": champion_success,
            "challenger_success": challenger_success,
            "num_tasks": len(champ_norm),
            "num_comparisons": total,
            "challenger_wins": challenger_wins,
            "champion_wins": champion_wins,
            "ties": ties,
            "challenger_win_rate": challenger_win_rate,
            "champion_win_rate": champion_win_rate,
            "min_samples": self._min_samples,
            "win_rate_threshold": self._win_rate_threshold,
            "task_breakdown": breakdown,
            "champion_results": champ_norm,
            "challenger_results": chall_norm,
        }
        if simulated:
            experiment.metrics["simulated"] = True

        inconclusive = not reg and total < self._min_samples
        experiment.metrics["inconclusive"] = inconclusive

        if reg:
            experiment.status = ExperimentStatus.REGRESSION
            experiment.winner = "champion" if champion_score >= challenger_score else "unknown"
            experiment.log = f"{prefix}Regression detected: challenger degraded performance on some tasks"
        elif total < self._min_samples:
            experiment.status = ExperimentStatus.COMPLETED
            experiment.winner = "inconclusive"
            experiment.log = (
                f"{prefix}INCONCLUSIVE: {total} paired task(s) "
                f"below min_samples={self._min_samples}"
            )
        elif challenger_win_rate >= self._win_rate_threshold:
            experiment.status = ExperimentStatus.COMPLETED
            experiment.winner = "challenger"
            experiment.log = (
                f"{prefix}Challenger win-rate {challenger_win_rate:.2f} >= "
                f"{self._win_rate_threshold:.2f} ({challenger_wins}W/{champion_wins}L/{ties}T)"
            )
        elif champion_win_rate >= self._win_rate_threshold:
            experiment.status = ExperimentStatus.COMPLETED
            experiment.winner = "champion"
            experiment.log = (
                f"{prefix}Champion win-rate {champion_win_rate:.2f} >= "
                f"{self._win_rate_threshold:.2f} ({challenger_wins}W/{champion_wins}L/{ties}T)"
            )
        else:
            experiment.status = ExperimentStatus.COMPLETED
            experiment.winner = "tie"
            experiment.log = (
                f"{prefix}Tie: no side reached win-rate "
                f"{self._win_rate_threshold:.2f} ({challenger_wins}W/{champion_wins}L/{ties}T)"
            )

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
        """Generate simulated results for testing without a real benchmark runner.

        Delegates to the same statistical pipeline as real runs (normalized
        scores, per-task breakdown, min-samples guard, win-rate decision).
        """
        import random as _random

        # Seed with component version for reproducibility
        seed = hash(challenger.id + challenger.version) % (2**32)
        rng = _random.Random(seed)

        num_tasks = len(task_ids) if task_ids else 10
        champion_base = 0.75 + rng.uniform(-0.05, 0.05)
        challenger_base = 0.72 + rng.uniform(-0.10, 0.10)
        jitter = 0.06

        def _sim_results(base: float) -> list[dict[str, Any]]:
            return [
                {
                    "task_id": str(i),
                    "success": rng.random() < base,
                    "score": min(1.0, max(0.0, base + rng.uniform(-jitter, jitter))),
                }
                for i in range(num_tasks)
            ]

        champion_results = _sim_results(champion_base)
        challenger_results = _sim_results(challenger_base)

        return self._finalize(
            experiment,
            champion_results,
            challenger_results,
            simulated=True,
        )

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
