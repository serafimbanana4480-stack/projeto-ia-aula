"""Tests for the Auto-Correction Loop."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from backend.core.agent_bus import BusMessage, get_agent_bus
from backend.core.agent_lifecycle import AgentInstanceStatus
from backend.core.auto_correction import AutoCorrectionLoop, get_auto_correction_loop


@pytest.fixture
def fresh_loop() -> AutoCorrectionLoop:
    """Return a fresh AutoCorrectionLoop instance."""
    return AutoCorrectionLoop()


@pytest.fixture
def bus(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Provide a fresh AgentBus backed by a temp DB."""
    monkeypatch.setattr("backend.core.agent_bus.DB_PATH", tmp_path / "agent_bus.db")
    from backend.core.agent_bus import AgentBus

    monkeypatch.setattr(AgentBus, "_instance", None)
    return get_agent_bus()


class FakeInstance:
    """Fake agent instance for mocking lifecycle manager."""

    def __init__(
        self, instance_id: str, agent_type: str, status: str = AgentInstanceStatus.RUNNING.value
    ):
        self.instance_id = instance_id
        self.agent_type = agent_type
        self.status = status
        self.context: dict[str, Any] = {}

    def is_terminal(self) -> bool:
        return self.status in {
            AgentInstanceStatus.COMPLETED.value,
            AgentInstanceStatus.FAILED.value,
            AgentInstanceStatus.ABORTED.value,
        }


class MockLifecycleManager:
    """Mock lifecycle manager that records spawn calls and simulates agent completion."""

    def __init__(self, outputs: dict[str, str] | None = None):
        self.spawn_calls: list[tuple[str, str]] = []  # (agent_type, objective)
        self._instances: dict[str, FakeInstance] = {}
        self._counter = 0
        self._outputs = outputs or {}

    async def spawn(self, agent_type: str, objective: str, **kwargs: Any) -> str:
        self.spawn_calls.append((agent_type, objective))
        self._counter += 1
        instance_id = f"fake_{agent_type.lower()}_{self._counter}"
        instance = FakeInstance(instance_id, agent_type)
        self._instances[instance_id] = instance
        # Simulate immediate completion in background
        asyncio.create_task(self._complete_later(instance_id, agent_type))
        return instance_id

    async def _complete_later(self, instance_id: str, agent_type: str) -> None:
        await asyncio.sleep(0.05)
        instance = self._instances[instance_id]
        instance.status = AgentInstanceStatus.COMPLETED.value
        instance.context["output"] = self._outputs.get(agent_type, f"{agent_type} done")

    def get_status(self, instance_id: str) -> FakeInstance | None:
        return self._instances.get(instance_id)

    async def abort(self, instance_id: str, reason: str = "") -> None:
        instance = self._instances.get(instance_id)
        if instance:
            instance.status = AgentInstanceStatus.ABORTED.value


class TestAutoCorrection:
    @pytest.mark.asyncio
    async def test_start_stop_monitoring(self, bus, fresh_loop):
        loop = fresh_loop
        await loop.start_monitoring()
        assert loop.get_status()["monitoring"] is True
        await loop.stop_monitoring()
        assert loop.get_status()["monitoring"] is False

    @pytest.mark.asyncio
    async def test_test_failure_handler_spawns_debugger_then_coder_then_test_runner(
        self, bus, fresh_loop
    ):
        """Verify the closed loop spawns DEBUGGER → CODER → TEST_RUNNER_UNIT sequentially."""
        mock_lifecycle = MockLifecycleManager(
            outputs={"TEST_RUNNER_UNIT": "All tests passed\n0 failed"}
        )
        loop = fresh_loop
        loop._lifecycle = mock_lifecycle
        await loop.start_monitoring()

        await bus.publish(
            "test.results",
            BusMessage(
                message_id="msg1",
                source_agent="TEST_RUNNER_UNIT",
                payload={"failures": 3, "artifact_id": "calc.py"},
            ),
        )
        # Give the mock agents time to "complete"
        await asyncio.sleep(0.3)

        status = loop.get_status()
        assert len(status["corrections"]) == 1
        assert status["corrections"][0]["trigger"] == "test_failure"

        # Verify spawn order
        spawned_types = [call[0] for call in mock_lifecycle.spawn_calls]
        assert spawned_types == ["DEBUGGER", "CODER", "TEST_RUNNER_UNIT"]

        await loop.stop_monitoring()

    @pytest.mark.asyncio
    async def test_test_failure_loops_until_passed(self, bus, fresh_loop):
        """Verify the loop iterates when tests still fail and stops when they pass."""
        # First two TEST_RUNNER_UNIT outputs indicate failure, third indicates pass
        mock_lifecycle = MockLifecycleManager(
            outputs={
                "TEST_RUNNER_UNIT": "3 tests failed\nAssertionError",
            }
        )
        loop = fresh_loop
        loop._lifecycle = mock_lifecycle
        await loop.start_monitoring()

        # Publish test failure
        await bus.publish(
            "test.results",
            BusMessage(
                message_id="msg1",
                source_agent="TEST_RUNNER_UNIT",
                payload={"failures": 3, "artifact_id": "loop.py"},
            ),
        )
        await asyncio.sleep(0.5)

        status = loop.get_status()
        loop_corr = [c for c in status["corrections"] if c["artifact_id"] == "loop.py"]
        assert loop_corr
        # Should have looped until max iterations or until the test output changed.
        # Because our mock always returns "3 tests failed", it should hit max iter.
        assert loop_corr[0]["iterations"] == 5
        assert loop_corr[0]["status"] == "active"  # escalation doesn't change tracker status

        # Verify escalation agents were spawned
        spawned_types = [call[0] for call in mock_lifecycle.spawn_calls]
        assert "META_ANALYZER" in spawned_types
        assert "OVERSEER" in spawned_types

        await loop.stop_monitoring()

    @pytest.mark.asyncio
    async def test_test_failure_stops_when_tests_pass(self, bus, fresh_loop):
        """Verify the loop stops after one iteration when tests pass."""
        mock_lifecycle = MockLifecycleManager(
            outputs={
                "TEST_RUNNER_UNIT": "All tests passed\n0 failed",
            }
        )
        loop = fresh_loop
        loop._lifecycle = mock_lifecycle
        await loop.start_monitoring()

        await bus.publish(
            "test.results",
            BusMessage(
                message_id="msg1",
                source_agent="TEST_RUNNER_UNIT",
                payload={"failures": 1, "artifact_id": "pass.py"},
            ),
        )
        await asyncio.sleep(0.3)

        status = loop.get_status()
        loop_corr = [c for c in status["corrections"] if c["artifact_id"] == "pass.py"]
        assert loop_corr
        assert loop_corr[0]["iterations"] == 1
        assert loop_corr[0]["status"] == "completed"

        spawned_types = [call[0] for call in mock_lifecycle.spawn_calls]
        assert spawned_types == ["DEBUGGER", "CODER", "TEST_RUNNER_UNIT"]

        await loop.stop_monitoring()

    @pytest.mark.asyncio
    async def test_critical_error_handler_spawns_coder_then_overseer(self, bus, fresh_loop):
        mock_lifecycle = MockLifecycleManager(
            outputs={"CODER": "Fixed the null pointer exception. Bug resolved."}
        )
        loop = fresh_loop
        loop._lifecycle = mock_lifecycle
        await loop.start_monitoring()

        await bus.publish(
            "errors.found",
            BusMessage(
                message_id="msg2",
                source_agent="BUG_HUNTER_RUNTIME",
                payload={"severity": "CRITICAL", "artifact_id": "auth.py"},
            ),
        )
        await asyncio.sleep(0.3)

        status = loop.get_status()
        assert any(c["trigger"] == "critical_error" for c in status["corrections"])

        spawned_types = [call[0] for call in mock_lifecycle.spawn_calls]
        assert spawned_types == ["CODER", "OVERSEER"]

        await loop.stop_monitoring()

    @pytest.mark.asyncio
    async def test_critical_error_loops_when_not_fixed(self, bus, fresh_loop):
        """If CODER output doesn't claim a fix, the loop should iterate."""
        mock_lifecycle = MockLifecycleManager(
            outputs={"CODER": "I looked at the code but could not determine the issue."}
        )
        loop = fresh_loop
        loop._lifecycle = mock_lifecycle
        await loop.start_monitoring()

        await bus.publish(
            "errors.found",
            BusMessage(
                message_id="msg2",
                source_agent="BUG_HUNTER_RUNTIME",
                payload={"severity": "CRITICAL", "artifact_id": "retry.py"},
            ),
        )
        await asyncio.sleep(0.5)

        status = loop.get_status()
        loop_corr = [c for c in status["corrections"] if c["artifact_id"] == "retry.py"]
        assert loop_corr
        assert loop_corr[0]["iterations"] == 5

        spawned_types = [call[0] for call in mock_lifecycle.spawn_calls]
        assert "META_ANALYZER" in spawned_types
        assert "OVERSEER" in spawned_types

        await loop.stop_monitoring()

    @pytest.mark.asyncio
    async def test_max_iterations_escalation(self, bus, fresh_loop):
        mock_lifecycle = MockLifecycleManager()
        loop = fresh_loop
        loop._lifecycle = mock_lifecycle
        await loop.start_monitoring()

        for i in range(6):
            await bus.publish(
                "test.results",
                BusMessage(
                    message_id=f"msg{i}",
                    source_agent="TEST_RUNNER_UNIT",
                    payload={"failures": 1, "artifact_id": "loop.py"},
                ),
            )
            await asyncio.sleep(0.1)

        status = loop.get_status()
        loop_corr = [c for c in status["corrections"] if c["artifact_id"] == "loop.py"]
        assert loop_corr
        # Should have stopped at max iterations and escalated
        assert loop_corr[0]["iterations"] == 5

        # Verify escalation agents spawned
        spawned_types = [call[0] for call in mock_lifecycle.spawn_calls]
        assert "META_ANALYZER" in spawned_types
        assert "OVERSEER" in spawned_types

        await loop.stop_monitoring()

    @pytest.mark.asyncio
    async def test_review_changes_handler(self, bus, fresh_loop, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        from backend.core.peer_review import PeerReviewSystem, get_peer_review_system
        from backend.persistence.db import init_db

        init_db()
        monkeypatch.setattr(PeerReviewSystem, "_instance", None)
        prs = get_peer_review_system()
        review = await prs.submit_for_review("svc.py", "code", "CODER", "content")
        await prs.conduct_review(review.review_id, "ANALYZER", "changes_requested")

        mock_lifecycle = MockLifecycleManager()
        loop = fresh_loop
        loop._lifecycle = mock_lifecycle
        await loop.start_monitoring()

        await bus.publish(
            "review.completed",
            BusMessage(
                message_id="rv1",
                source_agent="PEER_REVIEW_SYSTEM",
                payload={"review_id": review.review_id},
            ),
        )
        await asyncio.sleep(0.3)

        status = loop.get_status()
        assert any(c["trigger"] == "review_changes" for c in status["corrections"])

        spawned_types = [call[0] for call in mock_lifecycle.spawn_calls]
        assert spawned_types == ["REFACTOR_CLEAN", "CODER"]

        await loop.stop_monitoring()

    @pytest.mark.asyncio
    async def test_singleton_get_auto_correction_loop(self):
        """Verify get_auto_correction_loop returns the same instance."""
        loop1 = get_auto_correction_loop()
        loop2 = get_auto_correction_loop()
        assert loop1 is loop2

    @pytest.mark.asyncio
    async def test_get_auto_correction_loop_injects_lifecycle_manager(self):
        """Verify lifecycle manager can be injected into the singleton."""
        mock = MagicMock()
        loop = get_auto_correction_loop(lifecycle_manager=mock)
        assert loop._lifecycle is mock


class TestCheckStillFailing:
    def test_explicit_pass(self):
        assert AutoCorrectionLoop._check_still_failing("All tests passed\n0 failed") is False

    def test_explicit_fail(self):
        assert AutoCorrectionLoop._check_still_failing("3 tests failed") is True

    def test_empty_output_defaults_to_failing(self):
        assert AutoCorrectionLoop._check_still_failing("") is True

    def test_ambiguous_defaults_to_failing(self):
        assert AutoCorrectionLoop._check_still_failing("some random text") is True

    def test_no_failures_phrase(self):
        assert AutoCorrectionLoop._check_still_failing("no failures found") is False
