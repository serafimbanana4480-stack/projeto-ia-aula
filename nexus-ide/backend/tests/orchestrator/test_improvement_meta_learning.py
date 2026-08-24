"""Tests for the improvement orchestrator's LEARN phase.

Covers the meta-learning loop that used to be a stub: per-category success
rates (EMA), bounded confidence bias for future planning, and durable cycle
history in data/improvement_cycles.json.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.orchestrator.autonomous_improvement_orchestrator import (
    AutonomousImprovementOrchestrator,
    CycleResult,
    ImprovementProposal,
)


def _proposal(category: str, pid: str, confidence: float = 0.9) -> ImprovementProposal:
    return ImprovementProposal(
        proposal_id=pid,
        category=category,
        priority="high",
        target="backend/x.py",
        problem="problem",
        proposed_change="change",
        confidence=confidence,
        source="test",
        estimated_effort="low",
    )


@pytest.fixture
def orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AutonomousImprovementOrchestrator:
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path / "data"))
    orch = AutonomousImprovementOrchestrator(config={"use_subagents": False})
    # Redirect the history file into the tmp dir (property reads REPO_ROOT).
    monkeypatch.setattr(
        AutonomousImprovementOrchestrator,
        "_cycle_history_path",
        property(lambda self: tmp_path / "data" / "improvement_cycles.json"),
    )
    return orch


def _result(cycle_id: str) -> CycleResult:
    return CycleResult(
        cycle_id=cycle_id,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )


async def test_learn_persists_category_stats_and_history(
    orchestrator: AutonomousImprovementOrchestrator,
) -> None:
    proposals = [_proposal("performance", "p1"), _proposal("refactor", "p2")]
    verified = [_proposal("performance", "p1")]
    result = _result("c1")

    await orchestrator._learn(proposals, [], verified, result)

    data = json.loads(orchestrator._cycle_history_path.read_text(encoding="utf-8"))
    assert len(data["cycles"]) == 1
    cycle = data["cycles"][0]
    assert cycle["cycle_id"] == "c1"
    assert cycle["verified"] == 1

    stats = data["category_stats"]
    # performance verified -> EMA moves up; refactor not -> moves down.
    assert stats["performance"]["success_ema"] > 0.5
    assert stats["refactor"]["success_ema"] < 0.5
    assert stats["performance"]["samples"] == 1
    # The result object carries the updates for the checkpoint too.
    assert "performance" in result.meta_learning_updates


async def test_confidence_bias_is_bounded_and_requires_samples(
    orchestrator: AutonomousImprovementOrchestrator,
) -> None:
    # No history -> no bias.
    assert orchestrator._category_confidence_bias("performance") == 0.0

    # Feed 3 verified cycles for the same category.
    for i in range(3):
        result = _result(f"c{i}")
        await orchestrator._learn(
            [_proposal("performance", f"p{i}")],
            [],
            [_proposal("performance", f"p{i}")],
            result,
        )

    bias = orchestrator._category_confidence_bias("performance")
    assert bias > 0.0
    assert bias <= 0.1

    # A failing category gets a negative bias, also bounded.
    for i in range(3):
        result = _result(f"f{i}")
        await orchestrator._learn(
            [_proposal("exploration", f"e{i}")],
            [],
            [],
            result,
        )
    negative = orchestrator._category_confidence_bias("exploration")
    assert negative < 0.0
    assert negative >= -0.1


async def test_cycle_history_is_capped(
    orchestrator: AutonomousImprovementOrchestrator,
) -> None:
    for i in range(7):
        orchestrator._persist_cycle(_result(f"c{i}"), keep_last=5)
    data = json.loads(orchestrator._cycle_history_path.read_text(encoding="utf-8"))
    assert len(data["cycles"]) == 5
    assert data["cycles"][-1]["cycle_id"] == "c6"
