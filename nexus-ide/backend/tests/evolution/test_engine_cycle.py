"""Tests for EvolutionEngine operability: JSONL journal, cancellation, guard rails.

Uses fake evolvers and a fake benchmark runner (no network, no real LLMs).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import backend.evolution.engine as engine_module
from backend.evolution.arena import Arena
from backend.evolution.engine import (
    DEFAULT_JOURNAL_PATH,
    EvolutionConfig,
    EvolutionEngine,
    read_journal,
)
from backend.evolution.evolvers import Candidate
from backend.evolution.failure_miner import FailureMiner
from backend.evolution.registry import ChampionRegistry
from backend.evolution.rollback import RollbackManager
from backend.experience.lake import TraceLake
from backend.experience.models import (
    ExperienceTrace,
    TaskCategory,
    TraceMetrics,
    TraceResult,
)


def _make_trace(
    task_id: str,
    success: bool,
    error_text: str | None = None,
) -> ExperienceTrace:
    """Create a trace with optional failure error."""
    trace = ExperienceTrace(
        task_id=task_id,
        prompt=f"Task: {task_id}",
        category=TaskCategory.CODING,
        difficulty=0.5,
    )
    trace.add_trajectory_entry(
        agent="PLANNER",
        action="plan_task",
        tool="none",
        observation="planning complete",
    )
    if success:
        trace.result = TraceResult(success=True, score=0.9)
    else:
        trace.result = TraceResult(success=False, score=0.3, error=error_text)
    trace.metrics = TraceMetrics(
        latency_ms=1000,
        tokens_input=100,
        tokens_output=100,
        tool_calls=2,
    )
    return trace


def _candidate(kind: str = "prompt") -> Candidate:
    """Deterministic candidate that beats the champion under ScriptedRunner."""
    return Candidate(
        component_kind=kind,
        config={"prompt_text": "evolved prompt", "improved": True},
        changelog="test mutation",
        rationale="test",
        mutation_type="test_mutation",
        targets=["bad_planning"],
    )


class ScriptedEvolver:
    """Fake evolver returning deterministic candidates (or raising)."""

    def __init__(
        self,
        candidates: list[Candidate] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._candidates = candidates if candidates is not None else []
        self._error = error
        self.generate_calls = 0

    def generate(
        self,
        champion: Any,
        failure_priorities: list[Any],
        n_candidates: int = 3,
    ) -> list[Candidate]:
        self.generate_calls += 1
        if self._error is not None:
            raise self._error
        return self._candidates[:n_candidates]


class ScriptedRunner:
    """Fake BenchmarkRunner scoring by config marker; no network.

    Champion (default config) scores 0.5; challengers with ``improved`` in
    their config score 0.9, so promotion is deterministic.
    """

    def __init__(self, engine_to_cancel: EvolutionEngine | None = None) -> None:
        self.calls = 0
        self._engine_to_cancel = engine_to_cancel

    def run(
        self,
        component_kind: str,
        version: Any,
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self.calls += 1
        if self._engine_to_cancel is not None:
            self._engine_to_cancel.cancel()
            self._engine_to_cancel = None
        improved = bool(version.config.get("improved"))
        return [
            {
                "task_id": t["task_id"],
                "success": improved,
                "score": 0.9 if improved else 0.5,
                "metrics": {},
                "error": None,
            }
            for t in tasks
        ]


@pytest.fixture
def journal_path(tmp_path: Path) -> Path:
    # Nested dir on purpose: _append_journal must create parents.
    return tmp_path / "nested" / "evolution_journal.jsonl"


@pytest.fixture
def engine(
    tmp_path: Path,
    journal_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> EvolutionEngine:
    """Engine wired to temp DBs and a temp lake singleton; seeds failures."""
    import backend.experience.lake as lake_module

    lake = TraceLake(tmp_path / "trace_lake.db")
    monkeypatch.setattr(lake_module, "_lake", lake)

    registry = ChampionRegistry(db_path=tmp_path / "registry.db")
    miner = FailureMiner(lake=lake, db_path=tmp_path / "registry.db")
    eng = EvolutionEngine(
        registry=registry,
        arena=Arena(registry),
        failure_miner=miner,
        rollback=RollbackManager(registry),
        journal_path=journal_path,
    )

    lake.store_trace(_make_trace("seed_0", False, "Error: timeout after 30s"))
    lake.store_trace(_make_trace("seed_1", False, "Error: hallucinated API call"))
    lake.store_trace(_make_trace("seed_2", True))
    return eng


def _cycle_config(max_cycles: int = 1, candidates: int = 2) -> EvolutionConfig:
    # >= 5 paired tasks so the arena's significance check yields a real winner.
    return EvolutionConfig(
        max_cycles=max_cycles,
        benchmark_task_ids=[f"bench_{i}" for i in range(6)],
        components_to_evolve=["prompt"],
        candidates_per_cycle=candidates,
    )


class TestCycleJournal:
    def test_full_mini_cycle_writes_journal_line(
        self,
        engine: EvolutionEngine,
        journal_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A full mini-cycle appends one complete summary line to the journal."""
        fake = ScriptedEvolver(candidates=[_candidate(), _candidate()])
        monkeypatch.setattr(engine_module, "get_evolver", lambda kind, registry: fake)
        engine.set_benchmark_runner(ScriptedRunner())

        result = engine.evolve(config=_cycle_config())

        assert result.candidates_generated == 2
        assert result.experiments_run == 2
        # Candidate 1 beats the old champion and is promoted; candidate 2 then
        # ties against the newly promoted champion and is rejected.
        assert len(result.promoted) == 1
        assert len(result.rejected) == 1

        assert journal_path.exists()
        records = read_journal(journal_path)
        assert len(records) == 1

        record = records[0]
        assert record["type"] == "cycle_summary"
        assert record["cycle"] == 1
        assert record["failure_count"] >= 1
        assert record["candidates_generated"] == 2
        assert record["experiments_run"] == 2
        assert len(record["experiment_verdicts"]) == 2
        assert record["experiment_verdicts"][0]["winner"] == "challenger"
        for verdict in record["experiment_verdicts"]:
            assert verdict["component_kind"] == "prompt"
            assert verdict["experiment_id"]
            assert verdict["status"]
            assert verdict["regression_detected"] is False
        assert record["promoted"] == result.promoted
        assert record["rejected"] == result.rejected
        assert record["cancelled"] is False
        assert record["skipped_components"] == []
        assert record["started_at"]
        assert record["timestamp"]

    def test_journal_is_append_only_across_runs(
        self,
        engine: EvolutionEngine,
        journal_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Each evolve() run appends; earlier lines are preserved verbatim."""
        monkeypatch.setattr(
            engine_module,
            "get_evolver",
            lambda kind, registry: ScriptedEvolver(candidates=[_candidate()]),
        )
        engine.set_benchmark_runner(ScriptedRunner())

        engine.evolve(config=_cycle_config())
        first_pass = read_journal(journal_path)
        assert len(first_pass) == 1

        engine.evolve(config=_cycle_config())
        records = read_journal(journal_path)
        assert len(records) == 2
        assert records[0] == first_pass[0]

    def test_read_journal_tolerates_corrupt_lines(self, tmp_path: Path) -> None:
        """Corrupt/partial lines are skipped; valid records still parse."""
        path = tmp_path / "journal.jsonl"
        path.write_text(
            json.dumps({"type": "cycle_summary", "cycle": 1}) + "\n"
            "{not valid json\n"
            "\n"
            + json.dumps({"type": "cycle_summary", "cycle": 2}) + "\n"
            '["truncated",\n',
            encoding="utf-8",
        )

        records = read_journal(path)
        assert [r["cycle"] for r in records] == [1, 2]

    def test_read_journal_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert read_journal(tmp_path / "does_not_exist.jsonl") == []

    def test_default_journal_path_targets_backend_data(self) -> None:
        assert DEFAULT_JOURNAL_PATH.name == "evolution_journal.jsonl"
        assert DEFAULT_JOURNAL_PATH.parent.name == "data"


class TestLastCycleSummary:
    def test_none_before_any_cycle(self, engine: EvolutionEngine) -> None:
        assert engine.last_cycle_summary() is None

    def test_returns_latest_after_cycle(
        self,
        engine: EvolutionEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            engine_module,
            "get_evolver",
            lambda kind, registry: ScriptedEvolver(candidates=[_candidate()]),
        )
        engine.set_benchmark_runner(ScriptedRunner())

        engine.evolve(config=_cycle_config())
        summary = engine.last_cycle_summary()

        assert summary is not None
        assert summary["cycle"] == 1
        disk_records = read_journal(engine.journal_path)
        assert summary == disk_records[-1]

    def test_falls_back_to_disk_for_fresh_engine(
        self,
        engine: EvolutionEngine,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An engine that never ran reads the last record from the journal."""
        monkeypatch.setattr(
            engine_module,
            "get_evolver",
            lambda kind, registry: ScriptedEvolver(candidates=[_candidate()]),
        )
        engine.set_benchmark_runner(ScriptedRunner())
        engine.evolve(config=_cycle_config())

        fresh = EvolutionEngine(
            registry=ChampionRegistry(db_path=tmp_path / "other_registry.db"),
            arena=Arena(ChampionRegistry(db_path=tmp_path / "other_registry.db")),
            failure_miner=FailureMiner(lake=None, db_path=tmp_path / "other_registry.db"),
            rollback=RollbackManager(ChampionRegistry(db_path=tmp_path / "other_registry.db")),
            journal_path=engine.journal_path,
        )

        summary = fresh.last_cycle_summary()
        assert summary is not None
        assert summary["cycle"] == 1


class TestCancellation:
    def test_cancel_stops_before_next_phase(
        self,
        engine: EvolutionEngine,
        journal_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cancel mid-arena stops before further arena runs and cycles."""
        fake = ScriptedEvolver(candidates=[_candidate(), _candidate(), _candidate()])
        monkeypatch.setattr(engine_module, "get_evolver", lambda kind, registry: fake)
        engine.set_benchmark_runner(ScriptedRunner(engine_to_cancel=engine))

        result = engine.evolve(config=_cycle_config(max_cycles=3, candidates=3))

        assert engine.is_cancelled()
        # Stopped cleanly after cycle 1, before its remaining arena runs and
        # before cycles 2 and 3.
        assert result.cycle == 1
        assert result.experiments_run == 1
        assert result.candidates_generated == 1

        records = read_journal(journal_path)
        assert len(records) == 1
        assert records[0]["cancelled"] is True
        assert records[0]["experiments_run"] == 1

        summary = engine.last_cycle_summary()
        assert summary is not None
        assert summary["cancelled"] is True

    def test_reset_cancel_reuses_engine(
        self,
        engine: EvolutionEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            engine_module,
            "get_evolver",
            lambda kind, registry: ScriptedEvolver(candidates=[_candidate()]),
        )
        engine.set_benchmark_runner(ScriptedRunner(engine_to_cancel=engine))

        engine.evolve(config=_cycle_config())
        assert engine.is_cancelled()

        engine.reset_cancel()
        assert not engine.is_cancelled()

        result = engine.evolve(config=_cycle_config())
        assert result.experiments_run == 1


class TestFailingEvolverGuard:
    def test_failing_evolver_does_not_kill_cycle(
        self,
        engine: EvolutionEngine,
        journal_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A raising evolver skips only its component; the cycle continues."""

        def factory(kind: str, registry: Any) -> ScriptedEvolver:
            if kind == "prompt":
                return ScriptedEvolver(error=RuntimeError("evolver exploded"))
            return ScriptedEvolver(candidates=[_candidate(kind)])

        monkeypatch.setattr(engine_module, "get_evolver", factory)
        engine.set_benchmark_runner(ScriptedRunner())

        config = _cycle_config()
        config.components_to_evolve = ["prompt", "coder"]
        result = engine.evolve(config=config)

        # Cycle completed: coder still generated and ran an experiment.
        assert result.candidates_generated == 1
        assert result.experiments_run == 1
        assert len(result.promoted) == 1

        records = read_journal(journal_path)
        assert records[0]["skipped_components"] == ["prompt"]
        assert [v["component_kind"] for v in records[0]["experiment_verdicts"]] == ["coder"]
        assert "Generated 1 candidates" in records[0]["explanation"]

        # No orphan challenger left behind for the failed component.
        versions = engine._registry.list_versions("prompt")
        assert len(versions) == 1
        assert versions[0].version == "v1"

    def test_all_evolvers_failing_still_journals(
        self,
        engine: EvolutionEngine,
        journal_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Every component failing still ends the cycle with a journal line."""
        monkeypatch.setattr(
            engine_module,
            "get_evolver",
            lambda kind, registry: ScriptedEvolver(error=ValueError("always broken")),
        )
        engine.set_benchmark_runner(ScriptedRunner())

        config = _cycle_config()
        config.components_to_evolve = ["prompt", "coder"]
        result = engine.evolve(config=config)

        assert result.candidates_generated == 0
        assert result.experiments_run == 0

        records = read_journal(journal_path)
        assert len(records) == 1
        assert sorted(records[0]["skipped_components"]) == ["coder", "prompt"]
