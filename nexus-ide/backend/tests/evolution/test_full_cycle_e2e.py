"""Full self-evolution cycle e2e proof (test-only, fully deterministic).

Runs EvolutionEngine.evolve() across 2 cycles with a scripted evolver that
emits exactly one good candidate (cycle 1) and one bad candidate (cycle 2),
plus a deterministic fake BenchmarkRunner scoring by config marker.

Asserts:
  - journal lines are appended and readable via engine.read_journal
  - only the good candidate becomes champion (gates respected; the bad one
    regresses and is rejected; forbidden_patterns gate rejects its config)
  - a rollback snapshot is created on the regression scenario and restores
    the previous champion state (SnapshotManager + RollbackManager)
  - registry history is chronological and status-consistent
  - skill proposals are written when write_skill_proposals=True (base path
    redirected to tmp via monkeypatched SkillWriter.DEFAULT_PROPOSALS_DIR)

No network, no real LLM.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import backend.evolution.engine as engine_module
import backend.evolution.skill_writer as skill_writer_module
from backend.evolution.arena import Arena
from backend.evolution.engine import (
    EvolutionConfig,
    EvolutionEngine,
    read_journal,
)
from backend.evolution.evolvers import Candidate
from backend.evolution.failure_miner import FailureMiner
from backend.evolution.registry import (
    ChampionRegistry,
    ComponentStatus,
)
from backend.evolution.regression_guard import RegressionGuard
from backend.evolution.rollback import RollbackManager, SnapshotManager
from backend.experience.lake import TraceLake
from backend.experience.models import (
    ExperienceTrace,
    TaskCategory,
    TraceMetrics,
    TraceResult,
)

GOOD_CONFIG = {
    "prompt_text": "You are an expert engineer. Verify every output step by step.",
    "improved": "good",
}
BAD_CONFIG = {
    "prompt_text": "Quick fix: run rm -rf on the cache dir before every retry.",
    "improved": "bad",
}


def _make_trace(
    task_id: str,
    success: bool,
    error_text: str | None = None,
    with_skill_trajectory: bool = False,
) -> ExperienceTrace:
    trace = ExperienceTrace(
        task_id=task_id,
        prompt=f"Task: {task_id}",
        category=TaskCategory.CODING,
        difficulty=0.5,
    )
    if with_skill_trajectory:
        trace.add_trajectory_entry(
            agent="CODER", action="read", tool="read_file", observation="file read"
        )
        trace.add_trajectory_entry(
            agent="CODER", action="write", tool="write_file", observation="file written"
        )
        trace.add_trajectory_entry(
            agent="CODER", action="verify", tool="run_tests", observation="tests green"
        )
    else:
        trace.add_trajectory_entry(
            agent="PLANNER", action="plan_task", tool="none", observation="planned"
        )
    if success:
        trace.result = TraceResult(success=True, score=0.95)
    else:
        trace.result = TraceResult(success=False, score=0.3, error=error_text)
    trace.metrics = TraceMetrics(
        latency_ms=1000,
        tokens_input=100,
        tokens_output=100,
        tool_calls=3,
    )
    return trace


class ScriptedEvolver:
    """Fake evolver popping pre-scripted candidate batches, one per generate()."""

    def __init__(self, batches: list[list[Candidate]]) -> None:
        self._batches = [list(batch) for batch in batches]
        self.calls = 0

    def generate(
        self,
        champion: Any,
        failure_priorities: list[Any],
        n_candidates: int = 3,
    ) -> list[Candidate]:
        self.calls += 1
        if not self._batches:
            return []
        return self._batches.pop(0)[:n_candidates]


class MarkedRunner:
    """Deterministic fake BenchmarkRunner scoring by the ``improved`` marker.

    marker "good" -> 0.9 (success), "bad" -> 0.4 (failure),
    absent (bootstrap champions) -> 0.7 (success). Threshold 0.65.
    """

    def __init__(self) -> None:
        self.runs: list[tuple[str, str]] = []

    def run(
        self,
        component_kind: str,
        version: Any,
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self.runs.append((component_kind, getattr(version, "id", "?")))
        config = version.config if isinstance(version.config, dict) else {}
        score = {"good": 0.9, "bad": 0.4}.get(config.get("improved"), 0.7)
        success = score >= 0.65
        return [
            {
                "task_id": t["task_id"],
                "success": success,
                "score": score,
                "metrics": {},
                "error": None,
            }
            for t in tasks
        ]


def _build_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> EvolutionEngine:
    """Engine wired to temp DBs/lake/journal, seeded with failures + successes."""
    import backend.experience.lake as lake_module

    lake = TraceLake(tmp_path / "trace_lake.db")
    monkeypatch.setattr(lake_module, "_lake", lake)

    registry = ChampionRegistry(db_path=tmp_path / "registry.db", lake=lake)
    miner = FailureMiner(lake=lake, db_path=tmp_path / "registry.db")
    eng = EvolutionEngine(
        registry=registry,
        arena=Arena(registry),
        failure_miner=miner,
        rollback=RollbackManager(registry),
        journal_path=tmp_path / "nested" / "evolution_journal.jsonl",
    )

    lake.store_trace(_make_trace("fail_1", False, "Error: wrong tool used for this task"))
    lake.store_trace(_make_trace("fail_2", False, "Error: timeout after 30s"))
    lake.store_trace(_make_trace("fail_3", False, "Error: hallucinated API call"))
    for i in (1, 2, 3):
        lake.store_trace(
            _make_trace(f"succ_{i}", True, with_skill_trajectory=True)
        )

    runner = MarkedRunner()
    eng.set_benchmark_runner(runner)
    return eng


def _two_cycle_config(**overrides: Any) -> EvolutionConfig:
    params: dict[str, Any] = {
        "max_cycles": 2,
        "benchmark_task_ids": [f"bench_{i}" for i in range(6)],
        "components_to_evolve": ["prompt"],
        "candidates_per_cycle": 1,
    }
    params.update(overrides)
    return EvolutionConfig(**params)


def test_full_self_evolution_cycle_e2e(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Good candidate promoted in cycle 1, bad rejected in cycle 2; full proof."""
    engine = _build_engine(tmp_path, monkeypatch)
    journal_path = engine.journal_path

    proposals_dir = tmp_path / "skills"
    monkeypatch.setattr(
        skill_writer_module, "DEFAULT_PROPOSALS_DIR", proposals_dir
    )
    evolver = ScriptedEvolver(
        [
            [
                Candidate(
                    component_kind="prompt",
                    config=dict(GOOD_CONFIG),
                    changelog="good: adds verification constraint",
                    rationale="beats champion deterministically",
                    mutation_type="prompt_add_constraint",
                    targets=["tool_selection_error"],
                )
            ],
            [
                Candidate(
                    component_kind="prompt",
                    config=dict(BAD_CONFIG),
                    changelog="bad: dangerous shortcut",
                    rationale="regresses on all tasks",
                    mutation_type="prompt_add_constraint",
                    targets=["timeout"],
                )
            ],
        ]
    )
    monkeypatch.setattr(engine_module, "get_evolver", lambda kind, registry: evolver)

    result = engine.evolve(config=_two_cycle_config(write_skill_proposals=True))

    assert result.candidates_generated == 2
    assert result.experiments_run == 2
    assert result.promoted == ["prompt:v2"]
    assert result.rejected == ["prompt:v3"]
    assert result.regressions == 1

    registry = engine._registry
    champion = registry.get_champion("prompt")
    assert champion is not None and champion.version == "v2"

    v3 = registry.get_version("prompt", "v3")
    assert v3 is not None
    assert v3.status is ComponentStatus.REJECTED
    v1 = registry.get_version("prompt", "v1")
    assert v1 is not None
    assert v1.status is ComponentStatus.ARCHIVED

    history = registry.history("prompt")
    assert [h.version for h in history] == ["v1", "v2", "v3"]
    created = [h.created_at for h in history]
    assert created == sorted(created)
    assert history[1].parent_version == "v1"
    assert history[2].parent_version == "v2"

    records = read_journal(journal_path)
    assert len(records) == 2

    first, second = records
    assert first["type"] == "cycle_summary"
    assert first["cycle"] == 1
    assert first["candidates_generated"] == 1
    assert first["experiments_run"] == 1
    assert first["promoted"] == ["prompt:v2"]
    assert first["rejected"] == []
    assert first["regressions"] == 0
    assert first["cancelled"] is False
    assert first["experiment_verdicts"][0]["winner"] == "challenger"
    assert first["experiment_verdicts"][0]["regression_detected"] is False
    assert first["started_at"] and first["timestamp"]

    assert second["cycle"] == 2
    assert second["promoted"] == []
    assert second["rejected"] == ["prompt:v3"]
    assert second["regressions"] == 1
    assert second["cancelled"] is False
    assert second["experiment_verdicts"][0]["regression_detected"] is True

    bad_experiment = next(
        e
        for e in engine._arena.list_experiments(component_kind="prompt")
        if e.challenger_version == "v3"
    )
    guard = RegressionGuard()
    report = guard.evaluate_candidate(bad_experiment, candidate_config=dict(BAD_CONFIG))
    assert report.overall_passed is False
    forbidden = [g for g in report.gates if g.gate_name == "forbidden_patterns"]
    assert forbidden and forbidden[0].passed is False
    assert "rm -rf" in forbidden[0].message
    assert guard.should_promote(bad_experiment) is False

    proposal_files = sorted(proposals_dir.rglob("SKILL.md"))
    assert len(proposal_files) >= 1
    content = proposal_files[0].read_text(encoding="utf-8")
    assert content.startswith("---")
    assert "# " in content

    assert evolver.calls == 2


def test_regression_scenario_creates_restorable_snapshot_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Degraded promotion triggers rollback; pre-promotion snapshot restores v1."""
    engine = _build_engine(tmp_path, monkeypatch)
    registry = engine._registry
    engine.bootstrap_defaults()

    snapshots = SnapshotManager(tmp_path / "snapshots")
    v1 = registry.get_champion("prompt")
    assert v1 is not None
    original_config_json = json.dumps(v1.config, sort_keys=True)
    manifest = snapshots.create_snapshot(
        {"components/prompt_v1.json": original_config_json},
        reason="pre-promotion safety net",
        metadata={"component_kind": "prompt", "version": v1.version},
    )
    sid = manifest.snapshot_id
    assert snapshots.verify_snapshot(sid) == []

    registry.create_challenger(
        component_kind="prompt",
        version="v2",
        config={**v1.config, "improved": "bad"},
        parent_version=v1.version,
        changelog="degraded challenger that slipped through",
    )
    registry.promote("prompt", "v2")
    registry.update_metrics(
        "prompt",
        "v2",
        {"success_rate": 0.9, "avg_score": 0.88, "num_benchmark_tasks": 12},
    )
    assert registry.get_champion("prompt").version == "v2"

    rollback = RollbackManager(registry)
    observed_production = {
        "success_rate": 0.40,
        "avg_score": 0.35,
        "total_tasks": 12,
    }
    should, reason = rollback.should_rollback("prompt", observed_production)
    assert should is True
    assert "Success rate dropped" in reason

    event = rollback.execute_rollback("prompt", reason=reason)
    assert event is not None
    assert event.from_version == "v2"
    assert event.to_version == "v1"

    champion = registry.get_champion("prompt")
    assert champion is not None and champion.version == "v1"
    v2_after = registry.get_version("prompt", "v2")
    assert v2_after is not None
    assert v2_after.status is ComponentStatus.ARCHIVED

    history_rows = rollback.get_rollback_history("prompt")
    assert len(history_rows) == 1
    assert history_rows[0]["event_type"] == "rolled_back"
    assert history_rows[0]["component_kind"] == "prompt"

    restore_dir = tmp_path / "restored"
    snapshots.restore_snapshot(sid, restore_dir)
    restored = (restore_dir / "components" / "prompt_v1.json").read_text(
        encoding="utf-8"
    )
    assert restored == original_config_json

    assert snapshots.restore_snapshot(sid, restore_dir) == restore_dir
    assert snapshots.verify_snapshot(sid) == []


def test_journal_is_append_only_across_separate_evolve_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _build_engine(tmp_path, monkeypatch)
    journal_path = engine.journal_path
    evolver = ScriptedEvolver(
        [
            [
                Candidate(
                    component_kind="prompt",
                    config=dict(GOOD_CONFIG),
                    changelog="good",
                    rationale="r",
                    mutation_type="m",
                    targets=[],
                )
            ]
        ]
    )
    monkeypatch.setattr(engine_module, "get_evolver", lambda kind, registry: evolver)

    engine.evolve(config=_two_cycle_config(max_cycles=1))
    first_pass = read_journal(journal_path)
    assert len(first_pass) == 1

    engine.evolve(config=_two_cycle_config(max_cycles=1))
    records = read_journal(journal_path)
    assert len(records) == 2
    assert records[0] == first_pass[0]
