"""Tests for backend.orchestrator.subagent_* modules."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.core.agent_bus import BusMessage
from backend.core.agent_lifecycle import AgentLifecycleManager
from backend.orchestrator.subagent_checkpoint import SubagentCheckpoint, SubagentCheckpointStore
from backend.orchestrator.subagent_manager import (
    SubagentManager,
    derive_subagent_id,
)
from backend.orchestrator.subagent_registry import get_subagent_phase, list_phases

# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestSubagentRegistry:
    def test_list_phases_returns_four(self) -> None:
        assert sorted(list_phases()) == ["BUILD", "DESIGN", "RESEARCH", "VERIFY"]

    def test_research_phase_config(self) -> None:
        cfg = get_subagent_phase("RESEARCH")
        assert cfg is not None
        assert cfg.phase == "RESEARCH"
        assert cfg.agent_type == "RESEARCHER"
        assert cfg.timeout == 120.0
        assert cfg.token_budget == 8000
        assert cfg.max_retries == 2
        assert cfg.bus_topic_complete == "subagent.research.complete"
        assert cfg.bus_topic_failed == "subagent.research.failed"

    def test_design_phase_config(self) -> None:
        cfg = get_subagent_phase("DESIGN")
        assert cfg is not None
        assert cfg.agent_type == "ARCHITECT_DESIGN"
        assert cfg.bus_topic_complete == "subagent.design.complete"

    def test_build_phase_config(self) -> None:
        cfg = get_subagent_phase("BUILD")
        assert cfg is not None
        assert cfg.agent_type == "CODER"
        assert cfg.timeout == 300.0
        assert cfg.token_budget == 16000

    def test_verify_phase_config(self) -> None:
        cfg = get_subagent_phase("VERIFY")
        assert cfg is not None
        assert cfg.agent_type == "REVIEWER"
        assert cfg.bus_topic_complete == "subagent.verify.complete"

    def test_unknown_phase_returns_none(self) -> None:
        assert get_subagent_phase("UNKNOWN") is None

    def test_phase_case_insensitive(self) -> None:
        assert get_subagent_phase("research") is not None
        assert get_subagent_phase("Research") is not None


# ---------------------------------------------------------------------------
# Checkpoint store tests
# ---------------------------------------------------------------------------


class TestSubagentCheckpointStore:
    def test_save_and_get_latest(self, tmp_path) -> None:
        store = SubagentCheckpointStore(db_path=tmp_path / "ckpt.db")
        ckpt = SubagentCheckpoint(
            checkpoint_id="ckpt-1",
            subagent_id="sub-a",
            phase="RESEARCH",
            state={"key": "value"},
            completed=True,
        )
        store.save(ckpt)
        loaded = store.get_latest("sub-a")
        assert loaded is not None
        assert loaded.checkpoint_id == "ckpt-1"
        assert loaded.phase == "RESEARCH"
        assert loaded.state["key"] == "value"
        assert loaded.completed is True

    def test_get_latest_returns_none_for_missing(self, tmp_path) -> None:
        store = SubagentCheckpointStore(db_path=tmp_path / "ckpt.db")
        assert store.get_latest("missing") is None

    def test_get_by_phase(self, tmp_path) -> None:
        store = SubagentCheckpointStore(db_path=tmp_path / "ckpt.db")
        store.save(SubagentCheckpoint(checkpoint_id="c1", subagent_id="s1", phase="BUILD", state={}))
        store.save(SubagentCheckpoint(checkpoint_id="c2", subagent_id="s2", phase="BUILD", state={}))
        store.save(SubagentCheckpoint(checkpoint_id="c3", subagent_id="s3", phase="RESEARCH", state={}))
        results = store.get_by_phase("BUILD")
        assert len(results) == 2

    def test_mark_completed(self, tmp_path) -> None:
        store = SubagentCheckpointStore(db_path=tmp_path / "ckpt.db")
        store.save(SubagentCheckpoint(checkpoint_id="c1", subagent_id="s1", phase="RESEARCH", state={}, completed=False))
        store.mark_completed("c1")
        loaded = store.get_latest("s1")
        assert loaded is not None
        assert loaded.completed is True

    def test_get_incomplete_subagents(self, tmp_path) -> None:
        store = SubagentCheckpointStore(db_path=tmp_path / "ckpt.db")
        store.save(SubagentCheckpoint(checkpoint_id="c1", subagent_id="s1", phase="RESEARCH", state={}, completed=False))
        store.save(SubagentCheckpoint(checkpoint_id="c2", subagent_id="s2", phase="BUILD", state={}, completed=True))
        incomplete = store.get_incomplete_subagents()
        assert "s1" in incomplete
        assert "s2" not in incomplete


# ---------------------------------------------------------------------------
# SubagentManager tests
# ---------------------------------------------------------------------------


@pytest.fixture
def manager(tmp_path) -> SubagentManager:
    # An explicit temp store, not the default one. Subagent ids are now derived
    # from (mission, phase, objective) so that checkpoints can actually be
    # found again — which also means a test writing to the shared
    # `data/subagent_checkpoints.db` would leave a checkpoint that a later run
    # of the same test resumes from, making results depend on run history.
    return SubagentManager(
        lifecycle=AgentLifecycleManager(registry=None, llm_client=None),
        checkpoint_store=SubagentCheckpointStore(db_path=tmp_path / "manager-ckpt.db"),
    )


class TestSubagentManagerRunPhase:
    async def test_successful_phase(self, manager: SubagentManager) -> None:
        async def _fn() -> str:
            return "research output"

        result = await manager.run_phase("RESEARCH", "Analyze codebase", fn=_fn)
        assert result.success is True
        assert result.output == "research output"
        assert result.phase == "RESEARCH"
        assert result.duration_seconds >= 0

    async def test_failed_phase(self, manager: SubagentManager) -> None:
        async def _fn() -> str:
            raise RuntimeError("boom")

        result = await manager.run_phase("BUILD", "Write code", fn=_fn)
        assert result.success is False
        assert "boom" in (result.error or "")

    async def test_timeout_phase(self, manager: SubagentManager, monkeypatch: pytest.MonkeyPatch) -> None:
        import backend.orchestrator.subagent_manager as sm_mod
        from backend.orchestrator.subagent_registry import SubagentPhaseConfig

        monkeypatch.setattr(
            sm_mod,
            "get_subagent_phase",
            lambda phase: SubagentPhaseConfig(
                phase="VERIFY",
                agent_type="REVIEWER",
                timeout=0.3,
                token_budget=100,
                max_retries=1,
                bus_topic_complete="subagent.verify.complete",
                bus_topic_failed="subagent.verify.failed",
            ),
        )

        async def _fn() -> str:
            await asyncio.sleep(10)
            return "never"

        result = await manager.run_phase("VERIFY", "Run tests", fn=_fn)
        assert result.success is False
        assert "Timeout" in (result.error or "")

    async def test_publishes_to_bus(self, manager: SubagentManager, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        published: list[BusMessage] = []

        async def _fake_publish(topic: str, message: BusMessage) -> None:
            published.append(message)

        manager._bus.publish = _fake_publish  # type: ignore[method-assign]

        async def _fn() -> str:
            return "ok"

        result = await manager.run_phase("DESIGN", "Design system", fn=_fn)
        assert result.success is True
        assert any(m.topic == "subagent.design.complete" for m in published)

    async def test_saves_checkpoint(self, manager: SubagentManager, tmp_path) -> None:
        store = SubagentCheckpointStore(db_path=tmp_path / "ckpt.db")
        manager._checkpoints = store

        async def _fn() -> str:
            return "ok"

        result = await manager.run_phase("BUILD", "Write code", fn=_fn)
        assert result.success is True
        ckpt = store.get_latest(result.subagent_id)
        assert ckpt is not None
        assert ckpt.completed is True
        assert ckpt.phase == "BUILD"

    async def test_get_result(self, manager: SubagentManager) -> None:
        async def _fn() -> str:
            return "x"

        result = await manager.run_phase("RESEARCH", "task", fn=_fn)
        stored = manager.get_result(result.subagent_id)
        assert stored is not None
        assert stored.subagent_id == result.subagent_id
        assert stored.success is True

    async def test_get_stats(self, manager: SubagentManager) -> None:
        async def _ok() -> str:
            return "1"

        async def _fail() -> str:
            raise RuntimeError("err")

        await manager.run_phase("RESEARCH", "t1", fn=_ok)
        await manager.run_phase("BUILD", "t2", fn=_fail)

        stats = manager.get_stats()
        assert stats["total_subagents"] == 2
        assert stats["successful"] == 1
        assert stats["failed"] == 1
        assert stats["success_rate"] == 0.5

    async def test_uses_lifecycle_spawn_with_budget(self, manager: SubagentManager) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []

        original_spawn = manager._lifecycle.spawn

        async def _fake_spawn(agent_type: str, objective: str, **kwargs: Any) -> str:
            calls.append((agent_type, kwargs))
            return await original_spawn(agent_type, objective, **kwargs)

        manager._lifecycle.spawn = _fake_spawn  # type: ignore[method-assign]

        async def _fn() -> str:
            return "ok"

        await manager.run_phase("BUILD", "Write code", fn=_fn)
        assert len(calls) == 1
        assert calls[0][0] == "CODER"
        assert calls[0][1]["token_budget"] == 16000
        assert calls[0][1]["time_budget_seconds"] == 300

    async def test_tokens_counted_not_characters(self, manager: SubagentManager) -> None:
        """`tokens_used` used to be `len(str(output))`, ~4x the real figure."""
        payload = "palavra " * 400  # 3200 characters

        async def _fn() -> str:
            return payload

        result = await manager.run_phase("RESEARCH", "count me", fn=_fn)
        assert result.success is True
        assert 0 < result.tokens_used < len(payload) / 2


# ---------------------------------------------------------------------------
# Stable ids — the precondition for checkpoint recovery working at all
# ---------------------------------------------------------------------------


class TestDeriveSubagentId:
    def test_same_inputs_give_same_id(self) -> None:
        a = derive_subagent_id("RESEARCH", "analyse the repo", "mission-1")
        b = derive_subagent_id("RESEARCH", "analyse the repo", "mission-1")
        assert a == b

    def test_different_objectives_give_different_ids(self) -> None:
        a = derive_subagent_id("RESEARCH", "analyse the repo", "mission-1")
        b = derive_subagent_id("RESEARCH", "analyse the tests", "mission-1")
        assert a != b

    def test_different_missions_give_different_ids(self) -> None:
        a = derive_subagent_id("BUILD", "same work", "mission-1")
        b = derive_subagent_id("BUILD", "same work", "mission-2")
        assert a != b

    def test_phase_is_case_insensitive(self) -> None:
        assert derive_subagent_id("build", "x", "m") == derive_subagent_id("BUILD", "x", "m")

    def test_id_names_its_phase(self) -> None:
        assert derive_subagent_id("VERIFY", "x", "m").startswith("subagent-verify-")


# ---------------------------------------------------------------------------
# Retries — `max_retries` was declared and asserted but never read
# ---------------------------------------------------------------------------


class TestSubagentRetries:
    async def test_transient_failure_is_retried_then_succeeds(
        self, manager: SubagentManager
    ) -> None:
        attempts = 0

        async def _flaky() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError("provider unreachable")
            return "recovered"

        # RESEARCH allows 2 retries → 3 attempts total.
        result = await manager.run_phase("RESEARCH", "flaky work", fn=_flaky)
        assert result.success is True
        assert result.output == "recovered"
        assert attempts == 3
        assert result.retries == 2

    async def test_retries_stop_at_the_configured_limit(
        self, manager: SubagentManager
    ) -> None:
        attempts = 0

        async def _always_down() -> str:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("still down")

        # VERIFY allows 1 retry → 2 attempts, then give up.
        result = await manager.run_phase("VERIFY", "doomed", fn=_always_down)
        assert result.success is False
        assert attempts == 2
        assert result.retries == 1

    async def test_deterministic_failures_are_not_retried(
        self, manager: SubagentManager
    ) -> None:
        """A ValueError will fail identically every time; retrying only costs."""
        attempts = 0

        async def _bug() -> str:
            nonlocal attempts
            attempts += 1
            raise ValueError("bad input")

        result = await manager.run_phase("BUILD", "buggy", fn=_bug)
        assert result.success is False
        assert attempts == 1
        assert result.retries == 0
        assert "bad input" in (result.error or "")

    async def test_each_retry_spawns_a_fresh_instance(
        self, manager: SubagentManager
    ) -> None:
        """Reusing the instance would make attempt 2 inherit attempt 1's
        terminal failure and return immediately without doing any work."""
        spawned: list[str] = []
        original_spawn = manager._lifecycle.spawn

        async def _fake_spawn(agent_type: str, objective: str, **kwargs: Any) -> str:
            instance_id = await original_spawn(agent_type, objective, **kwargs)
            spawned.append(instance_id)
            return instance_id

        manager._lifecycle.spawn = _fake_spawn  # type: ignore[method-assign]

        calls = 0

        async def _flaky() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ConnectionError("blip")
            return "ok"

        await manager.run_phase("RESEARCH", "retry me", fn=_flaky)
        assert len(spawned) == 2
        assert len(set(spawned)) == 2


# ---------------------------------------------------------------------------
# Checkpoint resume — previously unreachable, because ids were random
# ---------------------------------------------------------------------------


class TestSubagentResume:
    async def test_incomplete_checkpoint_is_resumed(self, manager: SubagentManager) -> None:
        objective = "analyse the provider layer"
        subagent_id = derive_subagent_id("RESEARCH", objective, "m1")

        manager._checkpoints.save(
            SubagentCheckpoint(
                checkpoint_id=f"ckpt-{subagent_id}",
                subagent_id=subagent_id,
                phase="RESEARCH",
                state={"context": {"partial_findings": "found three providers"}},
                completed=False,
            )
        )

        seen: list[dict[str, Any]] = []
        original_spawn = manager._lifecycle.spawn

        async def _fake_spawn(agent_type: str, objective: str, **kwargs: Any) -> str:
            seen.append(kwargs.get("context", {}))
            return await original_spawn(agent_type, objective, **kwargs)

        manager._lifecycle.spawn = _fake_spawn  # type: ignore[method-assign]

        async def _fn() -> str:
            return "done"

        result = await manager.run_phase(
            "RESEARCH", objective, context={"fresh": "value"}, mission_id="m1", fn=_fn
        )

        assert result.resumed is True
        assert seen[0]["partial_findings"] == "found three providers"
        assert seen[0]["fresh"] == "value"

    async def test_fresh_context_wins_over_checkpoint(self, manager: SubagentManager) -> None:
        """The caller knows the current world; the checkpoint knows the world
        as it stood when the process died."""
        objective = "rebuild the index"
        subagent_id = derive_subagent_id("BUILD", objective, "")

        manager._checkpoints.save(
            SubagentCheckpoint(
                checkpoint_id=f"ckpt-{subagent_id}",
                subagent_id=subagent_id,
                phase="BUILD",
                state={"context": {"plan": "stale plan"}},
                completed=False,
            )
        )

        seen: list[dict[str, Any]] = []
        original_spawn = manager._lifecycle.spawn

        async def _fake_spawn(agent_type: str, objective: str, **kwargs: Any) -> str:
            seen.append(kwargs.get("context", {}))
            return await original_spawn(agent_type, objective, **kwargs)

        manager._lifecycle.spawn = _fake_spawn  # type: ignore[method-assign]

        async def _fn() -> str:
            return "done"

        await manager.run_phase("BUILD", objective, context={"plan": "fresh plan"}, fn=_fn)
        assert seen[0]["plan"] == "fresh plan"

    async def test_completed_checkpoint_is_not_resumed(self, manager: SubagentManager) -> None:
        objective = "already finished"
        subagent_id = derive_subagent_id("VERIFY", objective, "")

        manager._checkpoints.save(
            SubagentCheckpoint(
                checkpoint_id=f"ckpt-{subagent_id}",
                subagent_id=subagent_id,
                phase="VERIFY",
                state={"context": {"old": "state"}},
                completed=True,
            )
        )

        async def _fn() -> str:
            return "ok"

        result = await manager.run_phase("VERIFY", objective, fn=_fn)
        assert result.resumed is False


# ---------------------------------------------------------------------------
# Context budgeting for large, detailed tasks
# ---------------------------------------------------------------------------


class TestSubagentContextBudget:
    async def test_small_context_reaches_the_agent_intact(
        self, manager: SubagentManager
    ) -> None:
        seen: list[dict[str, Any]] = []
        original_spawn = manager._lifecycle.spawn

        async def _fake_spawn(agent_type: str, objective: str, **kwargs: Any) -> str:
            seen.append(kwargs.get("context", {}))
            return await original_spawn(agent_type, objective, **kwargs)

        manager._lifecycle.spawn = _fake_spawn  # type: ignore[method-assign]

        async def _fn() -> str:
            return "ok"

        context = {"objective": "small", "files": {"a.py": "x = 1"}}
        result = await manager.run_phase("BUILD", "tiny task", context=context, fn=_fn)

        assert seen[0] == context
        assert result.context_report is not None
        assert result.context_report.degraded is False

    async def test_oversized_context_is_budgeted_before_spawn(
        self, manager: SubagentManager
    ) -> None:
        seen: list[dict[str, Any]] = []
        original_spawn = manager._lifecycle.spawn

        async def _fake_spawn(agent_type: str, objective: str, **kwargs: Any) -> str:
            seen.append(kwargs.get("context", {}))
            return await original_spawn(agent_type, objective, **kwargs)

        manager._lifecycle.spawn = _fake_spawn  # type: ignore[method-assign]

        async def _fn() -> str:
            return "ok"

        context = {
            "objective": "refactor the provider layer",
            "plan": "step. " * 4_000,
            "transcript": "chatter. " * 40_000,
            "telemetry": {"samples": list(range(4_000))},
        }
        result = await manager.run_phase("BUILD", "huge task", context=context, fn=_fn)

        report = result.context_report
        assert report is not None
        assert report.degraded is True
        assert report.final_tokens < report.original_tokens
        # CRITICAL is handed over byte-identical…
        assert seen[0]["objective"] == context["objective"]
        # …while the LOW-priority transcript absorbs the reduction. It may be
        # trimmed rather than removed outright — keeping part of a value beats
        # discarding it whole, as long as the budget is respected.
        transcript = seen[0].get("transcript", "")
        assert len(transcript) < len(context["transcript"]) / 4

    async def test_budget_is_scaled_up_for_large_tasks(
        self, manager: SubagentManager
    ) -> None:
        """A twenty-file refactor and a one-line fix used to get identical
        time and token allowances."""
        calls: list[dict[str, Any]] = []
        original_spawn = manager._lifecycle.spawn

        async def _fake_spawn(agent_type: str, objective: str, **kwargs: Any) -> str:
            calls.append(kwargs)
            return await original_spawn(agent_type, objective, **kwargs)

        manager._lifecycle.spawn = _fake_spawn  # type: ignore[method-assign]

        async def _fn() -> str:
            return "ok"

        await manager.run_phase(
            "BUILD",
            "large refactor",
            context={"files": {f"f{i}.py": "code. " * 900 for i in range(20)}},
            fn=_fn,
        )

        cfg = get_subagent_phase("BUILD")
        assert cfg is not None
        assert calls[0]["token_budget"] > cfg.token_budget
        assert calls[0]["time_budget_seconds"] > cfg.timeout

    async def test_stats_surface_degradation(self, manager: SubagentManager) -> None:
        async def _fn() -> str:
            return "ok"

        await manager.run_phase("RESEARCH", "clean", context={"objective": "x"}, fn=_fn)
        await manager.run_phase(
            "RESEARCH",
            "messy",
            context={"objective": "x", "transcript": "noise. " * 40_000},
            fn=_fn,
        )

        stats = manager.get_stats()
        assert stats["total_subagents"] == 2
        assert stats["context_degraded"] == 1
        assert stats["total_tokens"] > 0
