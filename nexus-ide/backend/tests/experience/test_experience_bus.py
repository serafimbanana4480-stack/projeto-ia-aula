"""Tests for the Experience Bus and Trace Lake (FASE 2-3)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.experience.bus import ExperienceBus, get_experience_bus
from backend.experience.lake import TraceLake
from backend.experience.models import (
    ComponentKind,
    ExperienceTrace,
    ModelInfo,
    TaskCategory,
    TraceEvaluation,
    TraceMetrics,
    TraceResult,
)


@pytest.fixture
def temp_lake(tmp_path: Path) -> TraceLake:
    """Fresh TraceLake on a temp SQLite file."""
    return TraceLake(tmp_path / "test_trace_lake.db")


@pytest.fixture
def temp_bus(temp_lake: TraceLake) -> ExperienceBus:
    return ExperienceBus(lake=temp_lake, event_bus=None)


def _make_trace(**kw) -> ExperienceTrace:
    """Build a sample trace for testing."""
    return ExperienceTrace(
        prompt=kw.get("prompt", "Write a Python function to add two numbers"),
        task_type=kw.get("task_type", "coding"),
        difficulty=kw.get("difficulty", 0.5),
        category=kw.get("category", TaskCategory.CODING),
        session_id=kw.get("session_id", "sess-1"),
        model=ModelInfo(name="deepseek-chat", version="v4-flash", temperature=0.0, tier="fast"),
        agents=kw.get("agents", ["CODER"]),
        tags=kw.get("tags", ["python"]),
        experiment_id=kw.get("experiment_id"),
        component_kind=kw.get("component_kind", ComponentKind.CODER),
        component_version=kw.get("component_version", "v1"),
    )


# ── Models ───────────────────────────────────────────────────────────────────

class TestExperienceTrace:
    def test_default_task_id_generated(self) -> None:
        trace = ExperienceTrace()
        assert trace.task_id.startswith("task_")
        assert len(trace.task_id) > 10

    def test_default_timestamp_is_iso(self) -> None:
        trace = ExperienceTrace()
        # Should be parseable as ISO datetime
        from datetime import datetime
        datetime.fromisoformat(trace.timestamp)

    def test_add_trajectory_entry(self) -> None:
        trace = _make_trace()
        entry = trace.add_trajectory_entry(
            agent="CODER",
            action="write_file",
            tool="write_file",
            observation="created main.py",
            duration_ms=150,
        )
        assert entry.agent == "CODER"
        assert entry.action == "write_file"
        assert trace.trajectory[-1] is entry
        assert len(trace.trajectory) == 1

    def test_to_dict_serializable(self) -> None:
        trace = _make_trace()
        d = trace.to_dict()
        assert "task_id" in d
        assert "trajectory" in d
        assert "metrics" in d
        # Should be JSON-serializable
        json.dumps(d)

    def test_tags_coerced_from_dict(self) -> None:
        trace = ExperienceTrace(tags={"a": 1, "b": 2})
        assert trace.tags == ["a", "b"]

    def test_difficulty_range(self) -> None:
        trace = ExperienceTrace(difficulty=0.0)
        assert trace.difficulty == 0.0
        trace2 = ExperienceTrace(difficulty=1.0)
        assert trace2.difficulty == 1.0

    def test_category_default(self) -> None:
        trace = ExperienceTrace()
        assert trace.category == TaskCategory.UNKNOWN


# ── TraceLake ────────────────────────────────────────────────────────────────

class TestTraceLake:
    def test_store_and_retrieve(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        trace = _make_trace()
        temp_bus.record_trace(trace)
        retrieved = temp_lake.get_trace(trace.task_id)
        assert retrieved is not None
        assert retrieved.task_id == trace.task_id
        assert retrieved.prompt == trace.prompt
        assert retrieved.task_type == trace.task_type
        assert retrieved.result.success == trace.result.success

    def test_trace_count(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        assert temp_lake.trace_count() == 0
        temp_bus.record_trace(_make_trace())
        temp_bus.record_trace(_make_trace())
        assert temp_lake.trace_count() == 2

    def test_clear(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        temp_bus.record_trace(_make_trace())
        temp_bus.record_trace(_make_trace())
        assert temp_lake.trace_count() == 2
        temp_lake.clear()
        assert temp_lake.trace_count() == 0

    def test_store_trace_returns_task_id(self, temp_lake: TraceLake) -> None:
        trace = _make_trace()
        task_id = temp_lake.store_trace(trace)
        assert task_id == trace.task_id

    def test_store_trace_preserves_trajectory(self, temp_lake: TraceLake) -> None:
        trace = _make_trace()
        trace.add_trajectory_entry(agent="CODER", action="plan", duration_ms=10)
        trace.add_trajectory_entry(agent="CODER", action="execute", tool="write_file", duration_ms=50, success=False, error="syntax error")
        task_id = temp_lake.store_trace(trace)
        retrieved = temp_lake.get_trace(task_id)
        assert len(retrieved.trajectory) == 2
        assert retrieved.trajectory[1].error == "syntax error"


# ── TraceLake Querying ───────────────────────────────────────────────────────

class TestTraceLakeQuery:
    def _seed(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> list[ExperienceTrace]:
        traces = [
            _make_trace(prompt="Fix failing test in auth.py", task_type="coding", difficulty=0.3,
                        tags=["python"], component_version="v1",
                        category=TaskCategory.CODING, agents=["CODER"]),
            _make_trace(prompt="Add React state to SearchBar component", task_type="react_coding", difficulty=0.6,
                        tags=["react"], component_version="v2",
                        category=TaskCategory.CODING, agents=["CODER"]),
            _make_trace(prompt="Explain auth architecture", task_type="architecture", difficulty=0.7,
                        tags=["analysis"], component_version="v1",
                        category=TaskCategory.ARCHITECTURE, agents=["ARCHITECT"]),
            _make_trace(prompt="Debug segfault in worker", task_type="debugging", difficulty=0.8,
                        tags=["debugging"], component_version="v1",
                        category=TaskCategory.DEBUGGING, agents=["DEBUGGER"]),
        ]
        for t in traces:
            temp_bus.record_trace(t)
        return traces

    def test_query_by_task_type(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        self._seed(temp_lake, temp_bus)
        results = temp_lake.query_traces(task_type="coding")
        assert len(results) == 1
        assert results[0]["task_type"] == "coding"

    def test_query_by_category(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        self._seed(temp_lake, temp_bus)
        results = temp_lake.query_traces(category="architecture")
        assert len(results) == 1
        assert results[0]["category"] == "architecture"

    def test_query_by_difficulty_range(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        self._seed(temp_lake, temp_bus)
        results = temp_lake.query_traces(min_difficulty=0.5, max_difficulty=1.0)
        assert len(results) == 3  # react(0.6), arch(0.7), debug(0.8)

    def test_query_by_model(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        self._seed(temp_lake, temp_bus)
        results = temp_lake.query_traces(model_name="deepseek-chat")
        assert len(results) == 4  # all seeded traces use same model

    def test_query_by_tags(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        self._seed(temp_lake, temp_bus)
        results = temp_lake.query_traces(tags=["react"])
        assert len(results) == 1
        assert results[0]["task_type"] == "react_coding"

    def test_query_ordering(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        self._seed(temp_lake, temp_bus)
        results = temp_lake.query_traces(limit=10)
        # Results should be ordered by timestamp DESC
        timestamps = [r["timestamp"] for r in results]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_query_limit(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        self._seed(temp_lake, temp_bus)
        results = temp_lake.query_traces(limit=2)
        assert len(results) == 2

    def test_empty_query_returns_all(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        self._seed(temp_lake, temp_bus)
        results = temp_lake.query_traces()
        assert len(results) == 4


# ── TraceLake Analytics ─────────────────────────────────────────────────────

class TestTraceLakeAnalytics:
    def test_get_stats(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        t = _make_trace()
        t.result = TraceResult(success=True, score=0.9)
        t.metrics = TraceMetrics(latency_ms=1000, tokens_input=500, tokens_output=200, tool_calls=5, cost_usd=0.01)
        temp_bus.record_trace(t)
        stats = temp_lake.get_stats()
        assert stats["total"] >= 1
        assert stats["successes"] >= 1

    def test_get_failure_analysis(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        t1 = _make_trace(task_type="react_coding")
        t1.result = TraceResult(success=False, score=0.2, error="type error")
        t1.evaluation = TraceEvaluation(correctness=0.3)
        temp_bus.record_trace(t1)

        t2 = _make_trace(task_type="react_coding")
        t2.result = TraceResult(success=False, score=0.1, error="runtime error")
        temp_bus.record_trace(t2)

        analysis = temp_lake.get_failure_analysis()
        assert len(analysis) >= 1
        assert analysis[0]["task_type"] == "react_coding"
        assert analysis[0]["failure_count"] == 2

    def test_get_tool_error_analysis(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        trace = _make_trace()
        trace.add_trajectory_entry(
            agent="CODER", action="read_file", tool="read_file",
            success=False, error="file not found", duration_ms=10
        )
        trace.add_trajectory_entry(
            agent="CODER", action="write_file", tool="write_file",
            success=True, observation="created file", duration_ms=20
        )
        temp_bus.record_trace(trace)
        errors = temp_lake.get_tool_error_analysis()
        assert len(errors) == 1
        assert errors[0]["tool"] == "read_file"
        assert errors[0]["error_count"] == 1

    def test_get_component_performance(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        for version in ["v1", "v2", "v2"]:
            t = _make_trace(component_version=version, component_kind=ComponentKind.CODER)
            t.result = TraceResult(success=True, score=float(version == "v2") * 0.8)
            t.metrics = TraceMetrics(latency_ms=100)
            temp_bus.record_trace(t)
        perf = temp_lake.get_component_performance("coder")
        assert len(perf) == 2  # v1 and v2

    def test_get_model_performance(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        t = _make_trace()
        t.model = ModelInfo(name="gpt-4", tier="coder")
        t.result = TraceResult(success=True, score=0.9)
        t.metrics = TraceMetrics(latency_ms=200, tokens_input=300, tokens_output=100)
        temp_bus.record_trace(t)
        perf = temp_lake.get_model_performance()
        assert len(perf) >= 1
        assert any(p["model_name"] == "gpt-4" for p in perf)

    def test_get_token_waste_analysis(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        t = _make_trace(task_type="react_coding")
        t.metrics = TraceMetrics(tokens_input=5000, tokens_output=3000)
        t.result = TraceResult(success=False)
        temp_bus.record_trace(t)
        waste = temp_lake.get_token_waste_analysis()
        assert len(waste) >= 1
        assert waste[0]["avg_total_tokens"] > 0


# ── ExperienceBus ────────────────────────────────────────────────────────────

class TestExperienceBus:
    def test_start_trace(self, temp_bus: ExperienceBus) -> None:
        trace = temp_bus.start_trace(prompt="test prompt", task_type="coding")
        assert trace.prompt == "test prompt"
        assert trace.task_type == "coding"
        assert trace.task_id in temp_bus._active

    def test_record_trajectory(self, temp_bus: ExperienceBus) -> None:
        trace = temp_bus.start_trace(prompt="test", task_type="coding")
        temp_bus.record_trajectory(
            trace, agent="CODER", action="plan", tool="read_file",
            observation="found source", duration_ms=200
        )
        assert len(trace.trajectory) == 1
        assert trace.trajectory[0].agent == "CODER"
        assert trace.metrics.tool_calls == 1
        assert trace.metrics.latency_ms == 200

    def test_complete_records_and_clears(self, temp_bus: ExperienceBus) -> None:
        trace = temp_bus.start_trace(prompt="test", task_type="coding")
        temp_bus.complete(trace, success=True, score=0.9, latency_ms=1500)
        assert trace.task_id not in temp_bus._active
        assert temp_bus.get_trace(trace.task_id) is not None

    def test_complete_sets_metrics(self, temp_bus: ExperienceBus) -> None:
        trace = temp_bus.start_trace(prompt="test", task_type="coding")
        temp_bus.complete(
            trace, success=True, score=0.85,
            latency_ms=500, tokens_input=300, tokens_output=120,
            tool_calls=4, retries=1, cost_usd=0.005,
        )
        retrieved = temp_bus.get_trace(trace.task_id)
        assert retrieved.metrics.latency_ms == 500
        assert retrieved.metrics.tokens_input == 300
        assert retrieved.metrics.tool_calls == 4

    def test_cancel_trace(self, temp_bus: ExperienceBus) -> None:
        trace = temp_bus.start_trace(prompt="test", task_type="coding")
        temp_bus.cancel(trace.task_id, reason="user cancelled")
        assert trace.result.success is False
        assert "cancelled" in (trace.result.error or "").lower()

    def test_record_trace_persists(self, temp_bus: ExperienceBus) -> None:
        trace = _make_trace()
        task_id = temp_bus.record_trace(trace)
        assert task_id == trace.task_id
        assert temp_bus.get_trace(task_id) is not None

    def test_reconcile_metrics_from_trajectory(self, temp_bus: ExperienceBus) -> None:
        trace = _make_trace()
        trace.add_trajectory_entry(agent="CODER", action="plan", duration_ms=100, tokens_used=50)
        trace.add_trajectory_entry(agent="CODER", action="execute", duration_ms=200, tokens_used=30)
        temp_bus.record_trace(trace)
        retrieved = temp_bus.get_trace(trace.task_id)
        # Metrics should be reconciled from trajectory
        assert retrieved.metrics.tool_calls == 2
        assert retrieved.metrics.latency_ms == 300

    def test_singleton_bus(self) -> None:
        bus1 = get_experience_bus()
        bus2 = get_experience_bus()
        assert bus1 is bus2


# ── Search ───────────────────────────────────────────────────────────────────

class TestTraceLakeSearch:
    def test_search_prompts(self, temp_lake: TraceLake, temp_bus: ExperienceBus) -> None:
        traces = [
            _make_trace(prompt="Fix the failing test in pytest"),
            _make_trace(prompt="Add a button to React"),
            _make_trace(prompt="Debug memory leak in Python"),
        ]
        for t in traces:
            temp_bus.record_trace(t)

        results = temp_lake.search_prompts("test")
        assert len(results) >= 1
        assert any("test" in r["snippet"].lower() for r in results)

    def test_search_no_results(self, temp_lake: TraceLake) -> None:
        # Empty lake, no crash
        results = temp_lake.search_prompts("nonexistent")
        assert len(results) == 0


# ── Full trace lifecycle integration ─────────────────────────────────────────

class TestFullTraceLifecycle:
    def test_complete_lifecycle(self, temp_bus: ExperienceBus) -> None:
        """Test the full trace capture → persist → query cycle."""
        trace = temp_bus.start_trace(
            prompt="Build a REST API with FastAPI",
            task_type="coding",
            difficulty=0.6,
            category=TaskCategory.CODING,
            session_id="sess-abc",
            model=ModelInfo(name="deepseek-v4", version="v4-flash", tier="coder"),
            agents=["ROUTER", "CODER", "VERIFIER"],
            tags=["fastapi", "python"],
            experiment_id="exp-001",
            component_kind=ComponentKind.PLANNER,
            component_version="v2",
        )

        temp_bus.record_trajectory(
            trace, agent="ROUTER", action="classify", tool=None,
            observation="Intent: coding", duration_ms=50,
        )
        temp_bus.record_trajectory(
            trace, agent="CODER", action="write_code", tool="write_file",
            observation="created api.py", duration_ms=200,
        )
        temp_bus.record_trajectory(
            trace, agent="VERIFIER", action="run_test", tool="execute_code",
            observation="3 tests passed", duration_ms=150,
        )

        temp_bus.complete(
            trace,
            success=True, score=0.9,
            latency_ms=400, tokens_input=800, tokens_output=300,
            tool_calls=3, retries=0, cost_usd=0.002,
            memory_retrieved=["mem-1"],
            files_modified=["api.py"],
            tests_executed=["test_api.py"],
            correctness=0.95, efficiency=0.9, quality=0.88,
        )

        # Verify persistence
        retrieved = temp_bus.get_trace(trace.task_id)
        assert retrieved is not None
        assert retrieved.result.success is True
        assert retrieved.result.score == 0.9
        assert retrieved.evaluation.correctness == 0.95
        assert len(retrieved.trajectory) == 3
        assert retrieved.files_modified == ["api.py"]
        assert retrieved.tests_executed == ["test_api.py"]
        assert retrieved.experiment_id == "exp-001"

        # Verify queryability
        lake = temp_bus._lake
        stats = lake.get_stats()
        assert stats["total"] >= 1
        assert stats["successes"] >= 1
