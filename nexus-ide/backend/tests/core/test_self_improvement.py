"""Tests for backend.core.self_improvement."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.core.self_improvement import (
    ImprovementProposal,
    SelfImprovementAnalyzer,
    SelfImprovementReport,
    EVOLUTION_LOG_PATH,
    REPORT_PATH,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect evolution log and report to temp paths."""
    monkeypatch.setattr(
        "backend.core.self_improvement.EVOLUTION_LOG_PATH", tmp_path / "evolution_log.md"
    )
    monkeypatch.setattr(
        "backend.core.self_improvement.REPORT_PATH", tmp_path / "report.json"
    )


# ---------------------------------------------------------------------------
# Report model
# ---------------------------------------------------------------------------


class TestModels:
    def test_improvement_proposal_defaults(self) -> None:
        p = ImprovementProposal(
            category="prompt",
            target="CODER",
            problem="Low success rate",
            proposed_change="Add examples",
            expected_impact="Better accuracy",
            confidence=0.7,
        )
        assert p.approved is False
        assert p.approved_by == ""
        assert p.id.startswith("prop_")

    def test_self_improvement_report_serialization(self) -> None:
        r = SelfImprovementReport(
            summary="Test",
            proposals=[
                ImprovementProposal(
                    category="tool",
                    target="system",
                    problem="x",
                    proposed_change="y",
                    expected_impact="z",
                    confidence=0.5,
                )
            ],
        )
        data = r.model_dump(mode="json")
        assert data["summary"] == "Test"
        assert len(data["proposals"]) == 1


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class TestSelfImprovementAnalyzer:
    async def test_run_analysis_produces_report(self) -> None:
        analyzer = SelfImprovementAnalyzer()
        report = await analyzer.run_analysis()
        assert isinstance(report, SelfImprovementReport)
        assert report.generated_at
        assert report.summary
        assert isinstance(report.proposals, list)

    async def test_report_persisted_to_disk(self, tmp_path: Path) -> None:
        analyzer = SelfImprovementAnalyzer()
        await analyzer.run_analysis()
        assert (tmp_path / "report.json").exists()

    async def test_get_last_report_loads_from_disk(self, tmp_path: Path) -> None:
        analyzer = SelfImprovementAnalyzer()
        await analyzer.run_analysis()
        loaded = analyzer.get_last_report()
        assert loaded is not None
        assert loaded.generated_at

    async def test_evolution_log_appended(self, tmp_path: Path) -> None:
        analyzer = SelfImprovementAnalyzer()
        report = await analyzer.run_analysis()
        log_path = tmp_path / "evolution_log.md"
        if report.proposals:
            assert log_path.exists()
            text = log_path.read_text(encoding="utf-8")
            assert "NEXUS IDE Evolution Log" in text

    async def test_propose_prompt_refinements(self) -> None:
        analyzer = SelfImprovementAnalyzer()
        rates = {
            "CODER": {
                "total_runs": 10,
                "success_count": 5,
                "error_count": 5,
                "success_rate": 0.5,
                "avg_elapsed_seconds": 30.0,
            }
        }
        proposals = analyzer._propose_prompt_refinements(rates)
        assert any(p.target == "CODER" for p in proposals)

    async def test_propose_new_tools(self) -> None:
        analyzer = SelfImprovementAnalyzer()
        tools = {"consult_agent": 50, "search_codebase": 40}
        proposals = analyzer._propose_new_tools(tools, {})
        assert any(p.category == "tool" for p in proposals)

    async def test_propose_budget_adjustments(self) -> None:
        analyzer = SelfImprovementAnalyzer()
        missions = {"avg_duration_seconds": 400}
        proposals = analyzer._propose_budget_adjustments({}, missions)
        assert any(p.category == "budget" for p in proposals)

    async def test_propose_architecture_changes(self) -> None:
        analyzer = SelfImprovementAnalyzer()
        missions = {"total_missions": 10, "failed": 4, "aborted": 1, "completed": 5}
        proposals = analyzer._propose_architecture_changes({}, missions)
        assert any(p.category == "architecture" for p in proposals)

    async def test_read_evolution_log(self, tmp_path: Path) -> None:
        log = tmp_path / "evolution_log.md"
        log.write_text(
            "# NEXUS IDE Evolution Log\n\n---\n\n## Entry 1\n\nBody here.\n",
            encoding="utf-8",
        )
        analyzer = SelfImprovementAnalyzer()
        entries = analyzer._read_evolution_log()
        assert len(entries) >= 1
        assert any("Entry 1" in e["title"] for e in entries)

    async def test_compare_to_baseline(self) -> None:
        from backend.core.background_workers import PerformanceWatcher
        watcher = PerformanceWatcher(interval_seconds=0.05)
        baseline = {"custom": {"elapsed_ms": 100}}
        results = {"custom": {"elapsed_ms": 120}}
        comp = watcher._compare_to_baseline(results, baseline)
        assert comp["regressed"] is True

    async def test_save_and_load_report(self, tmp_path: Path) -> None:
        analyzer = SelfImprovementAnalyzer()
        report = SelfImprovementReport(summary="Test save/load")
        analyzer._save_report(report)
        loaded = analyzer.get_last_report()
        assert loaded is not None
        assert loaded.summary == "Test save/load"
