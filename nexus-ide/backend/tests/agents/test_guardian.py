"""Tests for NexusGuardianAgent."""

from __future__ import annotations

import pytest

from backend.agents.guardian import NexusGuardianAgent, Suggestion


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
