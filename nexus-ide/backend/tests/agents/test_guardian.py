"""Tests for NexusGuardianAgent."""

from __future__ import annotations

import asyncio

import pytest

from backend.agents.guardian import NexusGuardianAgent


@pytest.fixture
def guardian():
    return NexusGuardianAgent()


class TestGuardianStatus:
    def test_get_status_initial(self, guardian):
        status = guardian.get_status()
        assert status["running"] is False
        assert status["suggestion_count"] == 0

    def test_add_and_get_suggestions(self, guardian):
        guardian._add_suggestion(
            category="performance",
            priority="high",
            title="High CPU",
            description="CPU is high",
            action="Check CPU",
            auto_fixable=False,
        )
        suggestions = guardian.get_suggestions()
        assert len(suggestions) == 1
        assert suggestions[0]["title"] == "High CPU"

    def test_deduplicate_suggestions(self, guardian):
        for _ in range(3):
            guardian._add_suggestion(
                category="test",
                priority="low",
                title="Same",
                description="d",
                action="a",
                auto_fixable=False,
            )
        suggestions = guardian.get_suggestions()
        assert len(suggestions) == 1

    def test_apply_suggestion(self, guardian):
        guardian._add_suggestion(
            category="test",
            priority="low",
            title="ToApply",
            description="d",
            action="a",
            auto_fixable=False,
        )
        sugg_id = guardian.get_suggestions()[0]["id"]
        result = guardian.apply_suggestion(sugg_id)
        assert result["success"] is True
        assert guardian.get_suggestions(pending_only=True) == []

    def test_health_trend_empty(self, guardian):
        assert guardian.get_health_trend() == []


@pytest.mark.asyncio
async def test_start_marks_guardian_running_and_returns_its_monitor_task(
    guardian, monkeypatch: pytest.MonkeyPatch
):
    started = asyncio.Event()
    blocked = asyncio.Event()

    async def monitor_loop() -> None:
        started.set()
        await blocked.wait()

    monkeypatch.setattr(guardian, "monitor_loop", monitor_loop)

    task = await guardian.start()
    await started.wait()

    assert guardian.get_status()["running"] is True
    assert await guardian.start() is task

    await guardian.stop()
    assert task.cancelled()
