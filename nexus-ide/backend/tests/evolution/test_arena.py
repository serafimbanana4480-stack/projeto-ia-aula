"""Tests for the Arena (FASE 5) and its statistical decision rules (FASE 18)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.evolution.arena import (
    Arena,
    InMemoryBenchmarkRunner,
)
from backend.evolution.registry import (
    ChampionRegistry,
    ComponentVersion,
    ExperimentStatus,
)


@pytest.fixture
def temp_arena(tmp_path: Path) -> Arena:
    """Arena with temp registry."""
    registry = ChampionRegistry(db_path=tmp_path / "test_evolution.db")
    return Arena(registry, allow_simulation=True)


class _ScriptedRunner:
    """Returns canned per-task scores keyed by version string."""

    def __init__(self, scores_by_version: dict[str, list[float]], success: bool = True):
        self._scores = scores_by_version
        self._success = success
        self.call_count = 0

    def run(
        self,
        component_kind: str,
        version: ComponentVersion,
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self.call_count += 1
        scores = self._scores[version.version]
        return [
            {
                "task_id": t["task_id"],
                "success": self._success,
                "score": score,
                "metrics": {},
                "error": None,
            }
            for t, score in zip(tasks, scores, strict=True)
        ]


def _registry_with_versions(tmp_path: Path, name: str = "prompt") -> ChampionRegistry:
    registry = ChampionRegistry(db_path=tmp_path / f"{name}_evolution.db")
    registry.register_champion(name, "v1", {})
    registry.create_challenger(name, "v2", {}, "v1")
    return registry


class TestArenaSimulation:
    def test_simulate_without_runner(self, temp_arena: Arena) -> None:
        """Arena can simulate experiments without a real runner."""
        temp_arena._registry.register_champion("planner", "v1", {"prompt": "v1"})
        temp_arena._registry.create_challenger("planner", "v2", {"prompt": "v2"}, "v1")

        result = temp_arena.run_experiment("planner", "v2", ["task1", "task2"])
        assert result.status != ExperimentStatus.RUNNING  # should be completed or regression
        assert result.experiment_id.startswith("exp-")
        assert result.champion_version == "v1"
        assert result.challenger_version == "v2"
        assert result.metrics.get("simulated") is True

    def test_simulate_without_allow_simulation_raises(self, tmp_path: Path) -> None:
        """Arena without allow_simulation raises when no runner is set."""
        registry = ChampionRegistry(db_path=tmp_path / "test_evolution.db")
        arena = Arena(registry, allow_simulation=False)
        arena._registry.register_champion("planner", "v1", {"prompt": "v1"})
        arena._registry.create_challenger("planner", "v2", {"prompt": "v2"}, "v1")

        with pytest.raises(RuntimeError, match="No benchmark runner set"):
            arena.run_experiment("planner", "v2", ["task1"])

    def test_simulate_experiment_persisted(
        self, temp_arena: Arena, tmp_path: Path
    ) -> None:
        """Simulated experiments are persisted to the DB."""
        temp_arena._registry.register_champion("planner", "v1", {"prompt": "v1"})
        temp_arena._registry.create_challenger("planner", "v2", {"prompt": "v2"}, "v1")

        result = temp_arena.run_experiment("planner", "v2", ["task1"])
        assert temp_arena._persist_experiment  # exists

        # Reload from DB
        experiments = temp_arena.list_experiments("planner")
        assert any(e.experiment_id == result.experiment_id for e in experiments)

    def test_list_experiments_all_kinds(self, temp_arena: Arena) -> None:
        """list_experiments returns across all component kinds when None."""
        temp_arena._registry.register_champion("planner", "v1", {})
        temp_arena._registry.register_champion("coder", "v1", {})
        temp_arena._registry.create_challenger("planner", "v2", {}, "v1")
        temp_arena._registry.create_challenger("coder", "v2", {}, "v1")

        temp_arena.run_experiment("planner", "v2", ["t1"])
        temp_arena.run_experiment("coder", "v2", ["t2"])

        all_exps = temp_arena.list_experiments()
        assert len(all_exps) >= 2


class TestBenchmarkRunner:
    def test_arena_with_custom_runner(self, tmp_path: Path) -> None:
        """Arena works with a custom benchmark runner."""
        registry = ChampionRegistry(db_path=tmp_path / "test_evolution.db")

        class TestRunner:
            def __init__(self):
                self.call_count = 0

            def run(self, component_kind, version, tasks):
                self.call_count += 1
                results = []
                for t in tasks:
                    results.append({
                        "task_id": t["task_id"],
                        "success": True,
                        "score": 0.9 if version.version == "v2" else 0.7,
                        "metrics": {},
                        "error": None,
                    })
                return results

        runner = TestRunner()
        arena = Arena(registry)
        arena.set_runner(runner)

        registry.register_champion("prompt", "v1", {"prompt_text": "v1"})
        registry.create_challenger("prompt", "v2", {"prompt_text": "v2"}, "v1")

        tasks = [f"task_{i}" for i in range(6)]
        result = arena.run_experiment("prompt", "v2", tasks)
        assert result.winner == "challenger"
        assert runner.call_count == 2  # champion + challenger
        assert len(result.metrics["task_breakdown"]) == len(tasks)

    def test_arena_champion_wins(self, tmp_path: Path) -> None:
        """When champion has higher score, winner is 'champion'."""
        registry = ChampionRegistry(db_path=tmp_path / "test_evolution.db")

        class TestRunner:
            def run(self, component_kind, version, tasks):
                results = []
                for t in tasks:
                    results.append({
                        "task_id": t["task_id"],
                        "success": True,
                        "score": 0.6 if version.version == "v2" else 0.95,
                        "metrics": {},
                        "error": None,
                    })
                return results

        arena = Arena(registry)
        arena.set_runner(TestRunner())
        registry.register_champion("prompt", "v1", {})
        registry.create_challenger("prompt", "v2", {}, "v1")

        result = arena.run_experiment("prompt", "v2", [f"task_{i}" for i in range(6)])
        assert result.winner == "champion"

    def test_arena_detects_regression(self, tmp_path: Path) -> None:
        """Arena detects regression when challenger fails on champion-solved tasks.

        Regression overrides the min-samples guard (checked before it).
        """
        registry = ChampionRegistry(db_path=tmp_path / "test_evolution.db")

        class TestRunner:
            def run(self, component_kind, version, tasks):
                results = []
                for t in tasks:
                    if version.version == "v1":
                        # Champion succeeds on all
                        results.append({"task_id": t["task_id"], "success": True, "score": 0.9, "metrics": {}, "error": None})
                    else:
                        # Challenger fails on one
                        success = t["task_id"] != "fail_task"
                        results.append({
                            "task_id": t["task_id"],
                            "success": success,
                            "score": 0.5 if not success else 0.9,
                            "metrics": {},
                            "error": "failed" if not success else None,
                        })
                return results

        arena = Arena(registry)
        arena.set_runner(TestRunner())
        registry.register_champion("prompt", "v1", {})
        registry.create_challenger("prompt", "v2", {}, "v1")

        result = arena.run_experiment("prompt", "v2", ["ok_task", "fail_task"])
        assert result.regression_detected is True
        assert result.status == ExperimentStatus.REGRESSION


class TestStatisticalDecision:
    """FASE 18: win-rate decision with minimum sample size guard."""

    def test_inconclusive_below_min_samples(self, tmp_path: Path) -> None:
        """Fewer paired tasks than min_samples => INCONCLUSIVE, not win/lose."""
        registry = _registry_with_versions(tmp_path, "inconclusive")
        arena = Arena(registry)
        arena.set_runner(_ScriptedRunner({
            "v1": [0.4, 0.4, 0.4],
            "v2": [0.9, 0.9, 0.9],
        }))

        result = arena.run_experiment("inconclusive", "v2", ["t1", "t2", "t3"])
        assert result.status == ExperimentStatus.COMPLETED
        assert result.regression_detected is False
        assert result.winner == "inconclusive"
        assert result.metrics["inconclusive"] is True
        assert "INCONCLUSIVE" in result.log
        assert result.metrics["num_comparisons"] == 3
        assert result.metrics["min_samples"] == 5

    def test_challenger_win_at_exact_threshold(self, tmp_path: Path) -> None:
        """Challenger win-rate of exactly 0.6 (3/5) declares WIN; ties counted."""
        registry = _registry_with_versions(tmp_path, "threshold")
        arena = Arena(registry)
        arena.set_runner(_ScriptedRunner({
            "v1": [0.9, 0.9, 0.9, 0.9, 0.9],
            "v2": [0.95, 0.95, 0.95, 0.8, 0.8],
        }))

        result = arena.run_experiment("threshold", "v2", ["t1", "t2", "t3", "t4", "t5"])
        assert result.winner == "challenger"
        assert result.metrics["challenger_wins"] == 3
        assert result.metrics["champion_wins"] == 2
        assert result.metrics["ties"] == 0
        assert result.metrics["challenger_win_rate"] == pytest.approx(0.6)
        assert result.metrics["inconclusive"] is False

    def test_ties_counted_towards_denominator(self, tmp_path: Path) -> None:
        """A tie task counts in the denominator: 2W/2L/1T => no side reaches 0.6."""
        registry = _registry_with_versions(tmp_path, "ties")
        arena = Arena(registry)
        arena.set_runner(_ScriptedRunner({
            "v1": [0.9, 0.9, 0.9, 0.9, 0.9],
            "v2": [0.95, 0.95, 0.9, 0.85, 0.85],
        }))

        result = arena.run_experiment("ties", "v2", ["t1", "t2", "t3", "t4", "t5"])
        assert result.metrics["ties"] == 1
        assert result.metrics["challenger_win_rate"] == pytest.approx(0.4)
        assert result.metrics["champion_win_rate"] == pytest.approx(0.4)
        assert result.winner == "tie"
        assert "Tie" in result.log

    def test_champion_win_requires_threshold(self, tmp_path: Path) -> None:
        """Champion must also reach the win-rate threshold to be declared winner."""
        registry = _registry_with_versions(tmp_path, "champwin")
        arena = Arena(registry)
        arena.set_runner(_ScriptedRunner({
            "v1": [0.95, 0.95, 0.95, 0.95, 0.95],
            "v2": [0.9, 0.9, 0.8, 0.8, 0.9],
        }))

        result = arena.run_experiment("champwin", "v2", ["t1", "t2", "t3", "t4", "t5"])
        assert result.winner == "champion"
        assert result.metrics["champion_win_rate"] == pytest.approx(1.0)

    def test_min_samples_configurable(self, tmp_path: Path) -> None:
        """Lowering min_samples lets small experiments be decisive."""
        registry = _registry_with_versions(tmp_path, "smalln")
        arena = Arena(registry, min_samples=2)
        arena.set_runner(_ScriptedRunner({
            "v1": [0.4, 0.4],
            "v2": [0.9, 0.9],
        }))

        result = arena.run_experiment("smalln", "v2", ["t1", "t2"])
        assert result.metrics["min_samples"] == 2
        assert result.winner == "challenger"
        assert result.metrics["inconclusive"] is False

    def test_win_rate_threshold_configurable(self, tmp_path: Path) -> None:
        """Raising the threshold turns a 0.6 win-rate into a tie."""
        registry = _registry_with_versions(tmp_path, "strictthr")
        arena = Arena(registry, win_rate_threshold=0.8)
        arena.set_runner(_ScriptedRunner({
            "v1": [0.9, 0.9, 0.9, 0.9, 0.9],
            "v2": [0.95, 0.95, 0.95, 0.8, 0.8],
        }))

        result = arena.run_experiment("strictthr", "v2", ["t1", "t2", "t3", "t4", "t5"])
        assert result.metrics["win_rate_threshold"] == 0.8
        assert result.winner == "tie"


class TestScoreNormalization:
    """FASE 18: task scores are normalized to [0, 1] before aggregation."""

    def test_percentage_scores_auto_rescaled(self, tmp_path: Path) -> None:
        """All-raw scores above 1.0 are treated as 0-100 scale and divided by 100."""
        registry = _registry_with_versions(tmp_path, "pct")
        arena = Arena(registry)
        arena.set_runner(_ScriptedRunner({
            "v1": [70.0] * 5,
            "v2": [75.0] * 5,
        }))

        result = arena.run_experiment("pct", "v2", ["t1", "t2", "t3", "t4", "t5"])
        assert result.metrics["champion_score"] == pytest.approx(0.70)
        assert result.metrics["challenger_score"] == pytest.approx(0.75)
        assert result.winner == "challenger"
        assert all(0.0 <= r["score"] <= 1.0 for r in result.metrics["champion_results"])
        assert result.metrics["champion_results"][0]["raw_score"] == 70.0

    def test_score_max_hint_respected(self, tmp_path: Path) -> None:
        """An explicit per-result score_max hint divides raw values."""

        class HintedRunner:
            def run(self, component_kind, version, tasks):
                base = 7.0 if version.version == "v2" else 5.0
                return [
                    {
                        "task_id": t["task_id"],
                        "success": True,
                        "score": base + i * 0.1,
                        "score_max": 10.0,
                        "metrics": {},
                        "error": None,
                    }
                    for i, t in enumerate(tasks)
                ]

        registry = _registry_with_versions(tmp_path, "hinted")
        arena = Arena(registry)
        arena.set_runner(HintedRunner())

        result = arena.run_experiment("hinted", "v2", ["t1", "t2", "t3", "t4", "t5"])
        assert result.metrics["champion_score"] < 0.71
        assert result.metrics["champion_score"] > 0.49
        assert all(r["score"] <= 1.0 for r in result.metrics["challenger_results"])

    def test_out_of_range_scores_clamped(self, tmp_path: Path) -> None:
        """Mixed-scale batches are clamped into [0, 1] instead of rescaled."""

        class SloppyRunner:
            def run(self, component_kind, version, tasks):
                return [
                    {
                        "task_id": t["task_id"],
                        "success": True,
                        "score": [-1.0, 0.5, 2.5][i % 3],
                        "metrics": {},
                        "error": None,
                    }
                    for i, t in enumerate(tasks)
                ]

        registry = _registry_with_versions(tmp_path, "clamped")
        arena = Arena(registry)
        arena.set_runner(SloppyRunner())

        result = arena.run_experiment("clamped", "v2", ["t1", "t2", "t3"])
        scores = [r["score"] for r in result.metrics["champion_results"]]
        assert scores == [0.0, 0.5, 1.0]

    def test_non_numeric_scores_become_zero(self, tmp_path: Path) -> None:

        class BrokenRunner:
            def run(self, component_kind, version, tasks):
                return [
                    {
                        "task_id": t["task_id"],
                        "success": False,
                        "score": None,
                        "metrics": {},
                        "error": "boom",
                    }
                    for t in tasks
                ]

        registry = _registry_with_versions(tmp_path, "broken")
        arena = Arena(registry)
        arena.set_runner(BrokenRunner())

        result = arena.run_experiment("broken", "v2", ["t1", "t2", "t3", "t4", "t5"])
        assert result.metrics["champion_score"] == 0.0
        assert result.winner == "tie"


class TestInMemoryBenchmarkRunner:
    """FASE 18: fake-runner experiments without LLM/network."""

    def test_fake_runner_experiment_end_to_end(self, tmp_path: Path) -> None:
        """Full champion-vs-challenger experiment driven purely in memory."""
        registry = _registry_with_versions(tmp_path, "inmem")
        runner = InMemoryBenchmarkRunner(
            task_scores={
                f"t{i}": (lambda v: 0.9 if v.version == "v2" else 0.4) for i in range(6)
            },
        )
        arena = Arena(registry)
        arena.set_runner(runner)

        result = arena.run_experiment("inmem", "v2", [f"t{i}" for i in range(6)])

        assert result.status == ExperimentStatus.COMPLETED
        assert result.winner == "challenger"
        assert result.metrics.get("simulated") is not True
        assert result.metrics["num_comparisons"] == 6
        breakdown = result.metrics["task_breakdown"]
        assert len(breakdown) == 6
        assert all(b["winner"] == "challenger" for b in breakdown)
        assert {b["task_id"] for b in breakdown} == {f"t{i}" for i in range(6)}
        assert all(
            set(b) >= {
                "task_id",
                "champion_score",
                "challenger_score",
                "champion_success",
                "challenger_success",
                "winner",
            }
            for b in breakdown
        )
        # Persisted and reloadable
        stored = [e for e in arena.list_experiments("inmem") if e.experiment_id == result.experiment_id]
        assert len(stored) == 1
        assert stored[0].winner == "challenger"
        assert len(stored[0].metrics["task_breakdown"]) == 6

    def test_callable_entries_receive_version(self, tmp_path: Path) -> None:
        """Callable table entries get the ComponentVersion being scored."""
        seen: list[str] = []

        def entry(version: ComponentVersion) -> float:
            seen.append(version.version)
            return 1.0 if version.version == "v9" else 0.0

        runner = InMemoryBenchmarkRunner(task_scores={"only": entry})
        version = ComponentVersion(component_kind="prompt", version="v9")
        results = runner.run("prompt", version, [{"task_id": "only"}])

        assert seen == ["v9"]
        assert results[0]["score"] == 1.0
        assert results[0]["success"] is True

    def test_default_score_for_unknown_tasks(self) -> None:
        """Unknown task IDs fall back to default_score."""
        runner = InMemoryBenchmarkRunner(
            task_scores={"known": 1.0},
            default_score=0.2,
            success_threshold=0.65,
        )

        results = runner.run("prompt", ComponentVersion("prompt", "v1"), [
            {"task_id": "known"},
            {"task_id": "unknown"},
        ])

        assert results[0]["score"] == 1.0
        assert results[0]["error"] is None
        assert results[1]["score"] == 0.2
        assert results[1]["success"] is False
        assert results[1]["error"] is not None

    def test_inmemory_runner_is_deterministic(self, tmp_path: Path) -> None:
        """Repeated runs produce identical outcomes."""
        registry_a = _registry_with_versions(tmp_path, "determ_a")
        registry_b = _registry_with_versions(tmp_path, "determ_b")
        table = {f"t{i}": (lambda v: 0.8 if v.version == "v2" else 0.5) for i in range(5)}

        arena_a = Arena(registry_a)
        arena_a.set_runner(InMemoryBenchmarkRunner(task_scores=dict(table)))
        arena_b = Arena(registry_b)
        arena_b.set_runner(InMemoryBenchmarkRunner(task_scores=dict(table)))

        ra = arena_a.run_experiment("determ_a", "v2", [f"t{i}" for i in range(5)])
        rb = arena_b.run_experiment("determ_b", "v2", [f"t{i}" for i in range(5)])

        assert ra.winner == rb.winner == "challenger"
        assert ra.metrics["task_breakdown"] == rb.metrics["task_breakdown"]
