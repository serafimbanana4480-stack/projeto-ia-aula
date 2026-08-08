"""Tests for the FailureMiner (FASE 7)."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.evolution.failure_miner import FailureMiner
from backend.evolution.registry import FailureCategory
from backend.experience.lake import TraceLake
from backend.experience.models import (
    ComponentKind,
    ExperienceTrace,
    ModelInfo,
    TaskCategory,
    TraceResult,
)


@pytest.fixture
def temp_lake(tmp_path: Path) -> TraceLake:
    """Fresh TraceLake on a temp SQLite file."""
    return TraceLake(tmp_path / "test_lake.db")


@pytest.fixture
def failure_miner(temp_lake: TraceLake, tmp_path: Path) -> FailureMiner:
    """FailureMiner with a temp lake and temp db."""
    return FailureMiner(lake=temp_lake, db_path=tmp_path / "test_evolution.db")


def _make_trace(
    prompt: str = "Write code",
    task_type: str = "coding",
    success: bool = True,
    error: str | None = None,
    output: str | None = None,
    component_kind: str = "coder",
    score: float = 0.8,
    **kw,
) -> ExperienceTrace:
    """Build a sample trace for testing."""
    return ExperienceTrace(
        prompt=prompt,
        task_type=task_type,
        difficulty=kw.get("difficulty", 0.5),
        category=kw.get("category", TaskCategory.CODING),
        session_id=kw.get("session_id", "sess-1"),
        model=ModelInfo(name="deepseek-chat", version="v4", temperature=0.0, tier="fast"),
        agents=kw.get("agents", ["CODER"]),
        tags=kw.get("tags", ["python"]),
        result=TraceResult(success=success, score=score, error=error, output=output),
        component_kind=ComponentKind(component_kind) if component_kind else None,
        component_version=kw.get("component_version", "v1"),
    )


class TestClassification:
    def test_classify_syntax_error(self, failure_miner: FailureMiner) -> None:
        """SyntaxError maps to INCORRECT_CODE."""
        cat = failure_miner.classify_error("SyntaxError: invalid syntax", {})
        assert cat == FailureCategory.INCORRECT_CODE

    def test_classify_hallucination(self, failure_miner: FailureMiner) -> None:
        """Hallucinated API detected."""
        cat = failure_miner.classify_error("I'll call the nonexistent foo_bar function", {})
        assert cat == FailureCategory.HALLUCINATED_API

    def test_classify_timeout(self, failure_miner: FailureMiner) -> None:
        """Timeout detected."""
        cat = failure_miner.classify_error("Request timed out after 30s", {})
        assert cat == FailureCategory.TIMEOUT

    def test_classify_tool_error(self, failure_miner: FailureMiner) -> None:
        """Tool selection error detected."""
        cat = failure_miner.classify_error("No such tool: invalid_tool", {})
        assert cat == FailureCategory.TOOL_SELECTION_ERROR

    def test_classify_dependency_error(self, failure_miner: FailureMiner) -> None:
        """Dependency problem detected."""
        cat = failure_miner.classify_error("ModuleNotFoundError: no module named X", {})
        assert cat == FailureCategory.DEPENDENCY_PROBLEM

    def test_classify_regression(self, failure_miner: FailureMiner) -> None:
        """Regression detected."""
        cat = failure_miner.classify_error("This used to work in v1 but now broke", {})
        assert cat == FailureCategory.REGRESSION

    def test_classify_structural_planning(self, failure_miner: FailureMiner) -> None:
        """Structural classification uses component_kind."""
        cat = failure_miner.classify_error("unknown error", {"component_kind": "planner"})
        assert cat == FailureCategory.BAD_PLANNING

    def test_classify_structural_memory(self, failure_miner: FailureMiner) -> None:
        """Structural classification uses component_kind for memory."""
        cat = failure_miner.classify_error("unknown error", {"component_kind": "memory"})
        assert cat == FailureCategory.MEMORY_RETRIEVAL_ERROR

    def test_classify_unknown_fallback(self, failure_miner: FailureMiner) -> None:
        """Unclassifiable error returns UNKNOWN."""
        cat = failure_miner.classify_error("something totally unexpected", {})
        assert cat == FailureCategory.UNKNOWN


class TestAnalyzeFailures:
    def test_analyze_with_no_failures(self, failure_miner: FailureMiner, temp_lake: TraceLake) -> None:
        """Empty lake returns empty priorities."""
        priorities = failure_miner.analyze_failures()
        assert priorities == []

    def test_analyze_classifies_failures(
        self, failure_miner: FailureMiner, temp_lake: TraceLake
    ) -> None:
        """Failed traces are classified into categories."""
        # Store some failed traces
        for _ in range(3):
            trace = _make_trace(success=False, error="Syntax error in code", component_kind="coder")
            temp_lake.store_trace(trace)

        trace = _make_trace(success=False, error="timed out", component_kind="planner")
        temp_lake.store_trace(trace)

        priorities = failure_miner.analyze_failures(component_kind="coder")
        assert len(priorities) >= 1
        assert priorities[0].category == FailureCategory.INCORRECT_CODE
        # 3 failures out of 3 coder traces = 100% frequency
        assert priorities[0].frequency == 1.0

    def test_analyze_priority_scoring(
        self, failure_miner: FailureMiner, temp_lake: TraceLake
    ) -> None:
        """Priority score = frequency * impact * repairability."""
        # Store 5 failed traces with syntax errors
        for _ in range(5):
            trace = _make_trace(success=False, error="SyntaxError: bad", component_kind="coder")
            temp_lake.store_trace(trace)

        priorities = failure_miner.analyze_failures()
        syntax = next(p for p in priorities if p.category == FailureCategory.INCORRECT_CODE)

        # frequency=0.2 (5 failures / 5 traces... but only failed traces are returned)
        # Actually analyze_failures queries for success=False, so all 5 are returned
        assert syntax.frequency == 1.0
        assert syntax.priority_score == pytest.approx(
            syntax.frequency * syntax.impact * syntax.repairability
        )

    def test_analyze_sorted_by_priority(
        self, failure_miner: FailureMiner, temp_lake: TraceLake
    ) -> None:
        """Results are sorted by priority_score descending."""
        # Store failures: 1 regression (high impact), 5 timeouts (lower)
        temp_lake.store_trace(_make_trace(success=False, error="regression", category=TaskCategory.CODING))
        temp_lake.store_trace(_make_trace(success=False, error="regression", category=TaskCategory.CODING))
        for _ in range(5):
            temp_lake.store_trace(_make_trace(success=False, error="timed out"))

        priorities = failure_miner.analyze_failures()
        assert len(priorities) >= 2
        for i in range(len(priorities) - 1):
            assert priorities[i].priority_score >= priorities[i + 1].priority_score

    def test_store_and_retrieve_classifications(
        self, failure_miner: FailureMiner, temp_lake: TraceLake
    ) -> None:
        """store_classifications persists to DB and get_failure_summary retrieves."""
        # Manually create a priority
        from backend.evolution.registry import FailurePriority
        p = FailurePriority(
            category=FailureCategory.TIMEOUT,
            frequency=0.3,
            impact=0.6,
            repairability=0.3,
            priority_score=0.054,
            affected_tasks=["t1", "t2"],
            evidence="test",
        )
        failure_miner.store_classifications([p])

        summary = failure_miner.get_failure_summary()
        assert summary["total_classified"] >= 1
        assert any(c["category"] == "timeout" for c in summary["classifications"])
