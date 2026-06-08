"""Tests for backend.core.agent_lifecycle."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from backend.core.agent_lifecycle import (
    AgentInstanceStatus,
    AgentLifecycleManager,
    DEFAULT_TOKEN_BUDGET,
    MAX_CONCURRENT_AGENTS_GLOBAL,
    MAX_CONCURRENT_AGENTS_PER_TYPE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def manager() -> AgentLifecycleManager:
    return AgentLifecycleManager()


@pytest.fixture
def overseer_log() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def manager_with_overseer(overseer_log: list[dict[str, Any]]) -> AgentLifecycleManager:
    mgr = AgentLifecycleManager()

    async def callback(iid: str, event: str, data: dict[str, Any]) -> None:
        overseer_log.append({"instance_id": iid, "event": event, **data})

    mgr.set_overseer_callback(callback)
    return mgr


# ---------------------------------------------------------------------------
# Spawn / basic CRUD
# ---------------------------------------------------------------------------


class TestSpawn:
    async def test_spawn_returns_id(self, manager: AgentLifecycleManager) -> None:
        iid = await manager.spawn("CODER", "Write tests")
        assert isinstance(iid, str)
        assert len(iid) > 0

    async def test_spawn_sets_defaults(self, manager: AgentLifecycleManager) -> None:
        iid = await manager.spawn("CODER", "Write tests")
        inst = manager.get_status(iid)
        assert inst is not None
        assert inst.agent_type == "CODER"
        assert inst.objective == "Write tests"
        assert inst.status == AgentInstanceStatus.RUNNING.value
        assert inst.token_budget == DEFAULT_TOKEN_BUDGET
        assert inst.deadline > 0

    async def test_spawn_custom_budgets(self, manager: AgentLifecycleManager) -> None:
        before = time.time()
        iid = await manager.spawn(
            "CODER", "Write tests", token_budget=500, time_budget_seconds=30
        )
        inst = manager.get_status(iid)
        assert inst is not None
        assert inst.token_budget == 500
        assert inst.deadline <= before + 35

    async def test_spawn_enforces_global_limit(self, manager: AgentLifecycleManager) -> None:
        ids: list[str] = []
        types = ["CODER", "DEBUGGER", "ANALYZER", "ARCHITECT", "OPTIMIZER"]
        for i in range(MAX_CONCURRENT_AGENTS_GLOBAL):
            iid = await manager.spawn(types[i % len(types)], f"task {i}")
            ids.append(iid)

        with pytest.raises(RuntimeError, match="Global concurrent agent limit reached"):
            await manager.spawn("CODER", "overflow")

        for iid in ids:
            await manager.abort(iid)

    async def test_spawn_enforces_per_type_limit(self, manager: AgentLifecycleManager) -> None:
        ids: list[str] = []
        for _ in range(MAX_CONCURRENT_AGENTS_PER_TYPE):
            iid = await manager.spawn("CODER", f"task {_}")
            ids.append(iid)

        with pytest.raises(RuntimeError, match="Concurrent limit for agent type 'CODER'"):
            await manager.spawn("CODER", "overflow")

        for iid in ids:
            await manager.abort(iid)

    async def test_spawn_notifies_overseer(
        self, manager_with_overseer: AgentLifecycleManager, overseer_log: list[dict[str, Any]]
    ) -> None:
        iid = await manager_with_overseer.spawn("CODER", "Write tests", mission_id="m1")
        assert any(
            e["event"] == "agent_started" and e["instance_id"] == iid
            for e in overseer_log
        )


# ---------------------------------------------------------------------------
# Pause / Resume / Abort
# ---------------------------------------------------------------------------


class TestLifecycleTransitions:
    async def test_pause_resume(self, manager: AgentLifecycleManager) -> None:
        iid = await manager.spawn("CODER", "Write tests")
        inst = await manager.pause(iid)
        assert inst.status == AgentInstanceStatus.PAUSED.value

        inst = await manager.resume(iid)
        assert inst.status == AgentInstanceStatus.RUNNING.value

    async def test_abort(self, manager: AgentLifecycleManager) -> None:
        iid = await manager.spawn("CODER", "Write tests")
        inst = await manager.abort(iid, reason="test abort")
        assert inst.status == AgentInstanceStatus.ABORTED.value
        assert inst.error_message == "test abort"
        assert inst.completed_at > 0

    async def test_cannot_pause_terminal(self, manager: AgentLifecycleManager) -> None:
        iid = await manager.spawn("CODER", "Write tests")
        await manager.abort(iid)
        with pytest.raises(ValueError, match="Cannot pause agent in state"):
            await manager.pause(iid)

    async def test_cannot_resume_running(self, manager: AgentLifecycleManager) -> None:
        iid = await manager.spawn("CODER", "Write tests")
        with pytest.raises(ValueError, match="Cannot resume agent in state"):
            await manager.resume(iid)

    async def test_unknown_instance_raises(self, manager: AgentLifecycleManager) -> None:
        with pytest.raises(ValueError, match="not found"):
            await manager.pause("nonexistent")
        with pytest.raises(ValueError, match="not found"):
            await manager.resume("nonexistent")
        with pytest.raises(ValueError, match="not found"):
            await manager.abort("nonexistent")

    async def test_abort_notifies_overseer(
        self, manager_with_overseer: AgentLifecycleManager, overseer_log: list[dict[str, Any]]
    ) -> None:
        iid = await manager_with_overseer.spawn("CODER", "Write tests")
        await manager_with_overseer.abort(iid, reason="test")
        assert any(
            e["event"] == "agent_aborted" and e["instance_id"] == iid
            for e in overseer_log
        )


# ---------------------------------------------------------------------------
# Complete / Fail
# ---------------------------------------------------------------------------


class TestCompleteFail:
    async def test_complete(self, manager: AgentLifecycleManager) -> None:
        iid = await manager.spawn("CODER", "Write tests")
        inst = await manager.complete(iid, output="done", tokens_used=42)
        assert inst.status == AgentInstanceStatus.COMPLETED.value
        assert inst.tokens_used == 42

    async def test_fail(self, manager: AgentLifecycleManager) -> None:
        iid = await manager.spawn("CODER", "Write tests")
        inst = await manager.fail(iid, error="something broke")
        assert inst.status == AgentInstanceStatus.FAILED.value
        assert inst.error_message == "something broke"


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


class TestQueries:
    async def test_list_active(self, manager: AgentLifecycleManager) -> None:
        iid1 = await manager.spawn("CODER", "task1")
        iid2 = await manager.spawn("DEBUGGER", "task2")
        await manager.complete(iid1)

        active = manager.list_active()
        assert len(active) == 1
        assert active[0].instance_id == iid2

    async def test_list_by_mission(self, manager: AgentLifecycleManager) -> None:
        iid1 = await manager.spawn("CODER", "task1", mission_id="m1")
        iid2 = await manager.spawn("DEBUGGER", "task2", mission_id="m1")
        iid3 = await manager.spawn("CODER", "task3", mission_id="m2")

        m1 = manager.list_by_mission("m1")
        assert len(m1) == 2
        assert {i.instance_id for i in m1} == {iid1, iid2}

    async def test_get_status(self, manager: AgentLifecycleManager) -> None:
        iid = await manager.spawn("CODER", "task")
        inst = manager.get_status(iid)
        assert inst is not None
        assert inst.instance_id == iid
        assert manager.get_status("bogus") is None

    async def test_get_stats(self, manager: AgentLifecycleManager) -> None:
        iid = await manager.spawn("CODER", "task")
        stats = manager.get_stats()
        assert stats["total_instances"] == 1
        assert stats["active_instances"] == 1
        assert stats["global_limit"] == MAX_CONCURRENT_AGENTS_GLOBAL


# ---------------------------------------------------------------------------
# Garbage Collection
# ---------------------------------------------------------------------------


class TestGarbageCollect:
    async def test_gc_removes_old_terminal(self, manager: AgentLifecycleManager) -> None:
        iid = await manager.spawn("CODER", "task")
        await manager.complete(iid)
        # Manually backdate completed_at
        manager._instances[iid].completed_at = asyncio.get_event_loop().time() - 4000

        removed = await manager.garbage_collect()
        assert iid in removed
        assert manager.get_status(iid) is None

    async def test_gc_keeps_recent_terminal(self, manager: AgentLifecycleManager) -> None:
        iid = await manager.spawn("CODER", "task")
        await manager.complete(iid)

        removed = await manager.garbage_collect()
        assert iid not in removed
        assert manager.get_status(iid) is not None

    async def test_gc_keeps_active(self, manager: AgentLifecycleManager) -> None:
        iid = await manager.spawn("CODER", "task")
        removed = await manager.garbage_collect()
        assert iid not in removed


# ---------------------------------------------------------------------------
# Task tracking
# ---------------------------------------------------------------------------


class TestTaskTracking:
    async def test_track_task(self, manager: AgentLifecycleManager) -> None:
        iid = await manager.spawn("CODER", "task")
        task = asyncio.create_task(asyncio.sleep(10))
        manager.track_task(iid, task)
        assert iid in manager._tasks

        await manager.abort(iid)
        # Give the event loop a chance to process the cancellation
        await asyncio.sleep(0)
        assert task.done()
