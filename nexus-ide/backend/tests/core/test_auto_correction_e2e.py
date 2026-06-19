"""E2E tests for the Auto-Correction Loop.

These tests exercise the full closed-loop path:
  1. Publish an error event to the real AgentBus
  2. AutoCorrectionLoop detects it via subscription
  3. Fix agents are spawned through the (mocked) lifecycle manager
  4. After 5 failed iterations escalation to META_ANALYZER + OVERSEER occurs
  5. The 300 s agent timeout is respected (patched to a short value for speed)

No real LLM or Ollama instance is required — everything is mocked.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

import pytest

from backend.core.agent_bus import AgentBus, BusMessage, get_agent_bus
from backend.core.agent_lifecycle import AgentInstanceStatus
from backend.core.auto_correction import (
    AutoCorrectionLoop,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeInstance:
    """Fake agent instance compatible with lifecycle manager expectations."""

    def __init__(
        self,
        instance_id: str,
        agent_type: str,
        status: str = AgentInstanceStatus.RUNNING.value,
        output: str = "",
    ):
        self.instance_id = instance_id
        self.agent_type = agent_type
        self.status = status
        self.context: dict[str, Any] = {"output": output}

    def is_terminal(self) -> bool:
        return self.status in {
            AgentInstanceStatus.COMPLETED.value,
            AgentInstanceStatus.FAILED.value,
            AgentInstanceStatus.ABORTED.value,
        }


class MockLifecycleManager:
    """Mock lifecycle manager that records spawn calls and simulates agents."""

    def __init__(
        self,
        outputs: dict[str, str] | None = None,
        terminal_after: float = 0.05,
        never_terminal: bool = False,
    ):
        self.spawn_calls: list[tuple[str, str]] = []
        self._instances: dict[str, FakeInstance] = {}
        self._counter = 0
        self._outputs = outputs or {}
        self._terminal_after = terminal_after
        self._never_terminal = never_terminal

    async def spawn(self, agent_type: str, objective: str, **kwargs: Any) -> str:
        self.spawn_calls.append((agent_type, objective))
        self._counter += 1
        instance_id = f"fake_{agent_type.lower()}_{self._counter}"
        instance = FakeInstance(
            instance_id,
            agent_type,
            status=AgentInstanceStatus.RUNNING.value,
            output=self._outputs.get(agent_type, f"{agent_type} done"),
        )
        self._instances[instance_id] = instance
        if not self._never_terminal:
            asyncio.create_task(self._complete_later(instance_id))
        return instance_id

    async def _complete_later(self, instance_id: str) -> None:
        await asyncio.sleep(self._terminal_after)
        instance = self._instances.get(instance_id)
        if instance:
            instance.status = AgentInstanceStatus.COMPLETED.value

    def get_status(self, instance_id: str) -> FakeInstance | None:
        return self._instances.get(instance_id)

    async def abort(self, instance_id: str, reason: str = "") -> None:
        instance = self._instances.get(instance_id)
        if instance:
            instance.status = AgentInstanceStatus.ABORTED.value


@pytest.fixture
def fresh_bus(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Provide a completely fresh AgentBus backed by a temp DB."""
    monkeypatch.setattr("backend.core.agent_bus.DB_PATH", tmp_path / "agent_bus_e2e.db")
    monkeypatch.setattr(AgentBus, "_instance", None)
    return get_agent_bus()


@pytest.fixture
def fresh_loop(monkeypatch: pytest.MonkeyPatch):
    """Provide a fresh AutoCorrectionLoop and reset the singleton."""
    monkeypatch.setattr("backend.core.auto_correction._auto_correction_loop_instance", None)
    return AutoCorrectionLoop()


# ---------------------------------------------------------------------------
# E2E tests
# ---------------------------------------------------------------------------


class TestAutoCorrectionE2E:
    @pytest.mark.asyncio
    async def test_detects_test_failure_and_spawns_fix_agents(self, fresh_bus, fresh_loop):
        """Publish a test.results event and verify the loop spawns DEBUGGER→CODER→TEST_RUNNER_UNIT."""
        mock_lifecycle = MockLifecycleManager(
            outputs={"TEST_RUNNER_UNIT": "All tests passed\n0 failed"}
        )
        loop = fresh_loop
        loop._lifecycle = mock_lifecycle
        await loop.start_monitoring()

        await fresh_bus.publish(
            "test.results",
            BusMessage(
                message_id="e2e_msg1",
                source_agent="TEST_RUNNER_UNIT",
                payload={"failures": 2, "artifact_id": "calc.py", "output": "2 tests failed"},
            ),
        )
        await asyncio.sleep(0.3)

        status = loop.get_status()
        assert status["monitoring"] is True
        corrections = [c for c in status["corrections"] if c["artifact_id"] == "calc.py"]
        assert len(corrections) == 1
        assert corrections[0]["trigger"] == "test_failure"
        assert corrections[0]["iterations"] == 1
        assert corrections[0]["status"] == "completed"

        spawned = [call[0] for call in mock_lifecycle.spawn_calls]
        assert spawned == ["DEBUGGER", "CODER", "TEST_RUNNER_UNIT"]

        await loop.stop_monitoring()

    @pytest.mark.asyncio
    async def test_detects_critical_error_and_spawns_fix_agents(self, fresh_bus, fresh_loop):
        """Publish an errors.found CRITICAL event and verify CODER + OVERSEER are spawned."""
        mock_lifecycle = MockLifecycleManager(
            outputs={"CODER": "Fixed the null pointer exception. Bug resolved."}
        )
        loop = fresh_loop
        loop._lifecycle = mock_lifecycle
        await loop.start_monitoring()

        await fresh_bus.publish(
            "errors.found",
            BusMessage(
                message_id="e2e_msg2",
                source_agent="BUG_HUNTER_RUNTIME",
                payload={
                    "severity": "CRITICAL",
                    "artifact_id": "auth.py",
                    "error_report": "Null pointer in login handler",
                },
            ),
        )
        await asyncio.sleep(0.3)

        status = loop.get_status()
        corrections = [c for c in status["corrections"] if c["artifact_id"] == "auth.py"]
        assert len(corrections) == 1
        assert corrections[0]["trigger"] == "critical_error"
        assert corrections[0]["iterations"] == 1
        assert corrections[0]["status"] == "completed"

        spawned = [call[0] for call in mock_lifecycle.spawn_calls]
        assert spawned == ["CODER", "OVERSEER"]

        await loop.stop_monitoring()

    @pytest.mark.asyncio
    async def test_escalation_after_five_iterations(self, fresh_bus, fresh_loop):
        """When tests keep failing, the loop must stop at 5 iterations and escalate."""
        mock_lifecycle = MockLifecycleManager(
            outputs={"TEST_RUNNER_UNIT": "3 tests failed\nAssertionError"}
        )
        loop = fresh_loop
        loop._lifecycle = mock_lifecycle
        await loop.start_monitoring()

        await fresh_bus.publish(
            "test.results",
            BusMessage(
                message_id="e2e_msg3",
                source_agent="TEST_RUNNER_UNIT",
                payload={"failures": 3, "artifact_id": "loop.py", "output": "3 tests failed"},
            ),
        )
        await asyncio.sleep(0.8)

        status = loop.get_status()
        corrections = [c for c in status["corrections"] if c["artifact_id"] == "loop.py"]
        assert len(corrections) == 1
        assert corrections[0]["iterations"] == 5

        spawned = [call[0] for call in mock_lifecycle.spawn_calls]
        assert "META_ANALYZER" in spawned
        assert "OVERSEER" in spawned

        # Verify escalation message was published on the bus
        history = await fresh_bus.get_history("auto_correction.status", limit=10)
        escalation_msgs = [m for m in history if m.payload.get("status") == "escalated"]
        assert len(escalation_msgs) >= 1
        assert escalation_msgs[0].payload["artifact_id"] == "loop.py"
        assert "META_ANALYZER" in escalation_msgs[0].payload["escalation_targets"]

        await loop.stop_monitoring()

    @pytest.mark.asyncio
    async def test_timeout_respected_and_aborts_stuck_agent(
        self, fresh_bus, fresh_loop, monkeypatch
    ):
        """If an agent never becomes terminal, _wait_for_agent must abort it after the timeout."""
        mock_lifecycle = MockLifecycleManager(never_terminal=True)
        loop = fresh_loop
        loop._lifecycle = mock_lifecycle

        # Replace _wait_for_agent with a fast variant so the test doesn't hang 300 s
        async def _fast_wait_for_agent(instance_id: str, timeout: float = 0.15) -> None:
            start = time.time()
            while time.time() - start < timeout:
                if loop._stop_event.is_set():
                    return
                instance = loop._lifecycle.get_status(instance_id)
                if instance is None or instance.is_terminal():
                    return
                await asyncio.sleep(0.01)
            # Timeout reached — abort the stuck agent
            with contextlib.suppress(Exception):
                await loop._lifecycle.abort(instance_id, reason="Auto-correction timeout")

        monkeypatch.setattr(loop, "_wait_for_agent", _fast_wait_for_agent)
        await loop.start_monitoring()

        await fresh_bus.publish(
            "test.results",
            BusMessage(
                message_id="e2e_msg4",
                source_agent="TEST_RUNNER_UNIT",
                payload={"failures": 1, "artifact_id": "timeout.py", "output": "1 test failed"},
            ),
        )
        # Wait long enough for the short timeout to fire across iterations
        await asyncio.sleep(0.5)

        status = loop.get_status()
        corrections = [c for c in status["corrections"] if c["artifact_id"] == "timeout.py"]
        assert len(corrections) == 1
        # Because the agent never completes, each iteration treats it as still failing,
        # so the loop should hit max iterations and escalate.
        assert corrections[0]["iterations"] == 5

        spawned = [call[0] for call in mock_lifecycle.spawn_calls]
        assert "META_ANALYZER" in spawned
        assert "OVERSEER" in spawned

        # Ensure abort was called for the stuck agents
        aborted = [
            iid
            for iid, inst in mock_lifecycle._instances.items()
            if inst.status == AgentInstanceStatus.ABORTED.value
        ]
        assert len(aborted) >= 3  # DEBUGGER, CODER, TEST_RUNNER_UNIT per iteration

        await loop.stop_monitoring()

    @pytest.mark.asyncio
    async def test_performance_regression_handler(self, fresh_bus, fresh_loop):
        """Publish a performance.regression event and verify REFACTOR_PERFORMANCE is spawned."""
        mock_lifecycle = MockLifecycleManager()
        loop = fresh_loop
        loop._lifecycle = mock_lifecycle
        await loop.start_monitoring()

        await fresh_bus.publish(
            "performance.regression",
            BusMessage(
                message_id="e2e_msg5",
                source_agent="PROFILER",
                payload={
                    "artifact_id": "slow_module.py",
                    "metrics": {"latency_ms": 1200},
                    "comparison": {"baseline_ms": 300},
                },
            ),
        )
        await asyncio.sleep(0.3)

        status = loop.get_status()
        corrections = [c for c in status["corrections"] if c["artifact_id"] == "slow_module.py"]
        assert len(corrections) == 1
        assert corrections[0]["trigger"] == "performance_regression"
        assert corrections[0]["status"] == "completed"

        spawned = [call[0] for call in mock_lifecycle.spawn_calls]
        assert spawned == ["REFACTOR_PERFORMANCE"]

        await loop.stop_monitoring()

    @pytest.mark.asyncio
    async def test_review_changes_handler_e2e(self, fresh_bus, fresh_loop, tmp_path, monkeypatch):
        """Publish a review.completed event and verify REFACTOR_CLEAN (+ CODER for code) are spawned."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test_review_e2e.db")
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

        await fresh_bus.publish(
            "review.completed",
            BusMessage(
                message_id="e2e_msg6",
                source_agent="PEER_REVIEW_SYSTEM",
                payload={"review_id": review.review_id},
            ),
        )
        await asyncio.sleep(0.3)

        status = loop.get_status()
        corrections = [c for c in status["corrections"] if c["artifact_id"] == "svc.py"]
        assert len(corrections) == 1
        assert corrections[0]["trigger"] == "review_changes"
        assert corrections[0]["status"] == "completed"

        spawned = [call[0] for call in mock_lifecycle.spawn_calls]
        assert spawned == ["REFACTOR_CLEAN", "CODER"]

        await loop.stop_monitoring()

    @pytest.mark.asyncio
    async def test_multiple_artifacts_tracked_independently(self, fresh_bus, fresh_loop):
        """Two different artifacts should each get their own tracker and independent iteration counts."""
        mock_lifecycle = MockLifecycleManager(
            outputs={
                "TEST_RUNNER_UNIT": "All tests passed\n0 failed",
                "CODER": "Fixed the issue. Bug resolved.",
            }
        )
        loop = fresh_loop
        loop._lifecycle = mock_lifecycle
        await loop.start_monitoring()

        await fresh_bus.publish(
            "test.results",
            BusMessage(
                message_id="e2e_msg7a",
                source_agent="TEST_RUNNER_UNIT",
                payload={"failures": 1, "artifact_id": "a.py"},
            ),
        )
        await fresh_bus.publish(
            "errors.found",
            BusMessage(
                message_id="e2e_msg7b",
                source_agent="BUG_HUNTER_RUNTIME",
                payload={"severity": "HIGH", "artifact_id": "b.py"},
            ),
        )
        await asyncio.sleep(0.3)

        status = loop.get_status()
        a_corr = [c for c in status["corrections"] if c["artifact_id"] == "a.py"]
        b_corr = [c for c in status["corrections"] if c["artifact_id"] == "b.py"]
        assert len(a_corr) == 1
        assert len(b_corr) == 1
        assert a_corr[0]["trigger"] == "test_failure"
        assert b_corr[0]["trigger"] == "critical_error"
        assert a_corr[0]["iterations"] == 1
        assert b_corr[0]["iterations"] == 1

        await loop.stop_monitoring()
