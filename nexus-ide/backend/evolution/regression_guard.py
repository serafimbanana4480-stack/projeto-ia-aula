"""RegressionGuard — hard gates that block promotion if quality degrades.

FASE 8. Before a challenger can be promoted to champion, the
RegressionGuard validates that the challenger maintains (or improves) key
quality metrics relative to the champion. If ANY gate fails, promotion is
blocked and the challenger is rejected.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from backend.evolution.registry import Experiment, ExperimentStatus

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    """Result of a single regression gate check."""

    gate_name: str
    passed: bool
    champion_value: float
    challenger_value: float
    threshold: float
    message: str = ""


@dataclass
class GateReport:
    """Aggregate report of all gate checks for an experiment."""

    experiment_id: str
    overall_passed: bool
    gates: list[GateResult] = field(default_factory=list)
    explanation: str = ""


class RegressionGuard:
    """Hard gates that prevent champion degradation during promotion.

    Gates are evaluated after an arena experiment completes. Each gate
    compares champion vs. challenger metrics and blocks promotion if the
    challenger falls below the threshold.

    Usage:
        guard = RegressionGuard()
        report = guard.evaluate(experiment)
        if report.overall_passed:
            registry.promote("planner", experiment.challenger_version)
    """

    # Default gate thresholds (configurable per instantiation)
    DEFAULT_GATES: dict[str, dict[str, Any]] = {
        # Challenger must achieve at least this fraction of champion's success rate
        "success_rate": {
            "threshold": 1.0,     # challenger_success >= champion_success * threshold
            "strict": True,       # cannot be below champion at all
        },
        # No new task regressions: champion-solved tasks must remain solved
        "no_new_regressions": {
            "threshold": 0.0,     # zero new regressions allowed
            "strict": True,
        },
        # Challenger score must not drop below this fraction of champion
        "score_floor": {
            "threshold": 0.95,    # challenger_score >= champion_score * 0.95
            "strict": False,      # can degrade up to 5% for better exploration
        },
        # Challenger must succeed on at least N% of tasks the champion solved
        "champion_retention": {
            "threshold": 1.0,     # 100% retention — all champion-wins must stay
            "strict": True,
        },
        # Token/efficiency degradation allowed up to 15%
        "efficiency_budget": {
            "threshold": 1.15,    # challenger_tokens <= champion_tokens * 1.15
            "strict": False,
        },
    }

    def __init__(self, gates: dict[str, dict[str, Any]] | None = None) -> None:
        self.gates = gates if gates is not None else self.DEFAULT_GATES

    def evaluate(self, experiment: Experiment) -> GateReport:
        """Evaluate all gates for an experiment.

        Args:
            experiment: The completed experiment with metrics.

        Returns:
            GateReport with per-gate results and overall pass/fail.
        """
        metrics = experiment.metrics
        champion_results: list[dict[str, Any]] = metrics.get("champion_results", [])
        challenger_results: list[dict[str, Any]] = metrics.get("challenger_results", [])

        champion_success = metrics.get("champion_success", 0.0)
        challenger_success = metrics.get("challenger_success", 0.0)
        champion_score = metrics.get("champion_score", 0.0)
        challenger_score = metrics.get("challenger_score", 0.0)

        champion_tokens = self._avg_tokens(champion_results)
        challenger_tokens = self._avg_tokens(challenger_results)

        report = GateReport(
            experiment_id=experiment.experiment_id,
            overall_passed=True,
            explanation="All gates passed",
        )

        # Gate 1: Success rate floor
        gate = self.gates["success_rate"]
        threshold = gate["threshold"]
        passed = champion_success == 0 or challenger_success >= champion_success * threshold
        result = GateResult(
            gate_name="success_rate",
            passed=passed,
            champion_value=champion_success,
            challenger_value=challenger_success,
            threshold=threshold,
            message=(
                f"Champion success: {champion_success:.1%}, "
                f"Challenger success: {challenger_success:.1%}, "
                f"required >= {champion_success * threshold:.1%}"
            ),
        )
        report.gates.append(result)
        if not passed:
            report.overall_passed = False
            report.explanation = f"Failed gate: success_rate ({result.message})"

        # Gate 2: No new regressions (champion wins that challenger loses)
        gate = self.gates["no_new_regressions"]
        new_regressions = self._count_new_regressions(champion_results, challenger_results)
        passed = new_regressions <= gate["threshold"]
        result = GateResult(
            gate_name="no_new_regressions",
            passed=passed,
            champion_value=float(new_regressions),
            challenger_value=0.0,
            threshold=gate["threshold"],
            message=f"{new_regressions} new task regressions detected (max allowed: {gate['threshold']})",
        )
        report.gates.append(result)
        if not passed:
            report.overall_passed = False
            if report.explanation == "All gates passed":
                report.explanation = f"Failed gate: no_new_regressions ({result.message})"

        # Gate 3: Score floor
        gate = self.gates["score_floor"]
        threshold = gate["threshold"]
        passed = champion_score == 0 or challenger_score >= champion_score * threshold
        result = GateResult(
            gate_name="score_floor",
            passed=passed,
            champion_value=champion_score,
            challenger_value=challenger_score,
            threshold=threshold,
            message=(
                f"Champion score: {champion_score:.3f}, "
                f"Challenger score: {challenger_score:.3f}, "
                f"required >= {champion_score * threshold:.3f}"
            ),
        )
        report.gates.append(result)
        if not passed:
            report.overall_passed = False
            if report.explanation == "All gates passed":
                report.explanation = f"Failed gate: score_floor ({result.message})"

        # Gate 4: Champion retention
        gate = self.gates["champion_retention"]
        threshold = gate["threshold"]
        retained = self._champion_retention_rate(champion_results, challenger_results)
        passed = retained >= threshold
        result = GateResult(
            gate_name="champion_retention",
            passed=passed,
            champion_value=1.0,
            challenger_value=retained,
            threshold=threshold,
            message=f"{retained:.1%} of champion-solved tasks retained (>= {threshold:.0%} required)",
        )
        report.gates.append(result)
        if not passed:
            report.overall_passed = False
            if report.explanation == "All gates passed":
                report.explanation = f"Failed gate: champion_retention ({result.message})"

        # Gate 5: Efficiency budget
        gate = self.gates["efficiency_budget"]
        threshold = gate["threshold"]
        if champion_tokens > 0:
            ratio = challenger_tokens / champion_tokens
            passed = ratio <= threshold
        else:
            passed = True
            ratio = 1.0
        result = GateResult(
            gate_name="efficiency_budget",
            passed=passed,
            champion_value=champion_tokens,
            challenger_value=challenger_tokens,
            threshold=threshold,
            message=f"Token ratio: {ratio:.2f} (max {threshold:.2f})",
        )
        report.gates.append(result)
        if not passed:
            report.overall_passed = False
            if report.explanation == "All gates passed":
                report.explanation = f"Failed gate: efficiency_budget ({result.message})"

        return report

    def _avg_tokens(self, results: list[dict[str, Any]]) -> float:
        """Compute average token usage from results."""
        token_values = [
            r.get("tokens_input", 0) + r.get("tokens_output", 0)
            for r in results
            if isinstance(r, dict)
        ]
        if not token_values:
            return 0.0
        return sum(token_values) / len(token_values)

    def _count_new_regressions(
        self,
        champion_results: list[dict[str, Any]],
        challenger_results: list[dict[str, Any]],
    ) -> int:
        """Count tasks where champion succeeded but challenger failed."""
        champion_by_id = {
            r["task_id"]: r for r in champion_results if "task_id" in r
        }
        count = 0
        for r in challenger_results:
            tid = r.get("task_id")
            if tid is None:
                continue
            champ = champion_by_id.get(tid)
            if champ is None:
                continue
            if champ.get("success") and not r.get("success"):
                count += 1
        return count

    def _champion_retention_rate(
        self,
        champion_results: list[dict[str, Any]],
        challenger_results: list[dict[str, Any]],
    ) -> float:
        """Fraction of champion-solved tasks that challenger also solves."""
        champion_wins = {
            r["task_id"] for r in champion_results
            if "task_id" in r and r.get("success", False)
        }
        if not champion_wins:
            return 1.0
        retained = {
            r.get("task_id") for r in challenger_results
            if r.get("success", False)
        }
        retained_wins = champion_wins & retained
        return len(retained_wins) / len(champion_wins)

    def should_promote(self, experiment: Experiment) -> bool:
        """Quick check: should the champion be promoted based on gates + winner?

        Refuses promotion if the experiment used simulated (non-real) results.
        """
        if experiment.metrics.get("simulated", False):
            logger.warning(
                f"Experiment {experiment.experiment_id} used simulated results; "
                f"promotion blocked"
            )
            return False
        if experiment.status == ExperimentStatus.REGRESSION:
            return False
        if experiment.winner != "challenger":
            return False
        report = self.evaluate(experiment)
        return report.overall_passed

    def evaluate_candidate(
        self,
        experiment: Experiment,
        candidate_config: dict[str, Any] | None = None,
    ) -> GateReport:
        """Evaluate all gates plus the forbidden-patterns content gate.

        Runs the standard metric gates via :meth:`evaluate` and prepends a
        ``forbidden_patterns`` gate that scans the candidate config for
        destructive shell/SQL patterns (e.g. ``rm -rf``, ``drop table``).
        A single dangerous pattern blocks promotion regardless of metrics.
        """
        report = self.evaluate(experiment)
        if candidate_config:
            forbidden = self._find_forbidden_patterns(candidate_config)
            gate = GateResult(
                gate_name="forbidden_patterns",
                passed=not forbidden,
                champion_value=0.0,
                challenger_value=float(len(forbidden)),
                threshold=0.0,
                message=(
                    f"Forbidden patterns found in candidate config: {', '.join(forbidden)}"
                    if forbidden
                    else "No forbidden patterns in candidate config"
                ),
            )
            report.gates.insert(0, gate)
            if forbidden:
                report.overall_passed = False
                report.explanation = (
                    f"Failed gate: forbidden_patterns ({gate.message})"
                )
        return report

    # Destructive patterns that must never ship inside a candidate config.
    _FORBIDDEN_PATTERNS: tuple[str, ...] = (
        "rm -rf",
        "rm -fr",
        "del /f /s /q",
        "rmdir /s /q",
        "format c:",
        "rd /s /q",
        "drop table",
        "drop database",
        "truncate table",
        "mkfs",
        "dd if=",
        ":(){:|:&};:",
        "shutdown -h",
        "> /dev/sda",
        "git push --force",
        "chmod -r 777 /",
    )

    def _find_forbidden_patterns(self, candidate_config: dict[str, Any]) -> list[str]:
        """Return forbidden patterns present (case-insensitive) in the config."""
        blob = json.dumps(candidate_config, default=str).lower()
        return [pattern for pattern in self._FORBIDDEN_PATTERNS if pattern in blob]
