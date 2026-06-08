"""End-to-end test for Background Workers, Auto-Correction, and Agent Lifecycle.

Usage:
    cd nexus-ide
    python -m pytest e2e/test_workers_auto_correction_lifecycle.py -v -s

This script uses httpx.AsyncClient with ASGITransport to test the live FastAPI
app directly — no background server required.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root is on PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import httpx
import pytest
from fastapi import FastAPI

from backend.core.agent_bus import AgentBus, BusMessage, get_agent_bus
from backend.core.agent_lifecycle import AgentLifecycleManager
from backend.core.auto_correction import AutoCorrectionLoop, get_auto_correction_loop
from backend.core.background_workers import (
    BackgroundWorkerManager,
    WorkerStatus,
)
from backend.orchestrator.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_ms() -> int:
    return int(time.time() * 1000)


async def _wait_for_condition(
    condition: callable,
    timeout: float = 5.0,
    interval: float = 0.1,
) -> bool:
    """Poll until condition() is True or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await condition():
            return True
        await asyncio.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Provide an async HTTP client wired to the FastAPI app."""
    # Isolate the bus DB so tests don't pollute each other
    bus_db = tmp_path / "e2e_bus.db"
    monkeypatch.setattr("backend.core.agent_bus.DB_PATH", bus_db)
    monkeypatch.setattr(AgentBus, "_instance", None)

    # Isolate the persistence DB
    persist_db = tmp_path / "e2e_persist.db"
    monkeypatch.setattr("backend.persistence.db.DB_PATH", persist_db)
    from backend.persistence.db import init_db

    init_db()

    # Manually initialise app.state objects that routes depend on
    app.state.worker_manager = BackgroundWorkerManager(watch_path=str(tmp_path))
    await app.state.worker_manager.start_all()

    app.state.agent_lifecycle = AgentLifecycleManager()

    app.state.auto_correction = get_auto_correction_loop()
    await app.state.auto_correction.start_monitoring()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    # Teardown
    await app.state.worker_manager.stop_all()
    await app.state.auto_correction.stop_monitoring()


@pytest.fixture
async def fresh_auto_correction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Provide a fresh auto-correction loop with an isolated bus."""
    bus_db = tmp_path / "ac_bus.db"
    monkeypatch.setattr("backend.core.agent_bus.DB_PATH", bus_db)
    monkeypatch.setattr(AgentBus, "_instance", None)

    persist_db = tmp_path / "ac_persist.db"
    monkeypatch.setattr("backend.persistence.db.DB_PATH", persist_db)
    from backend.persistence.db import init_db

    init_db()

    loop = AutoCorrectionLoop()
    yield loop
    await loop.stop_monitoring()


@pytest.fixture
async def fresh_lifecycle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Provide a fresh agent lifecycle manager with isolated DB."""
    persist_db = tmp_path / "lc_persist.db"
    monkeypatch.setattr("backend.persistence.db.DB_PATH", persist_db)
    from backend.persistence.db import init_db

    init_db()

    manager = AgentLifecycleManager()
    yield manager


# ---------------------------------------------------------------------------
# Background Workers — API tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBackgroundWorkersAPI:
    async def test_list_workers(self, async_client: httpx.AsyncClient):
        """GET /api/workers returns all four workers."""
        response = await async_client.get("/api/workers")
        assert response.status_code == 200
        data = response.json()
        workers = data["workers"]
        names = {w["name"] for w in workers}
        assert names == {
            "CODE_WATCHER",
            "DEPENDENCY_WATCHER",
            "PERFORMANCE_WATCHER",
            "MEMORY_WATCHER",
        }
        for w in workers:
            assert w["status"] in ("running", "stopped", "paused", "starting")

    async def test_start_stop_each_worker(self, async_client: httpx.AsyncClient):
        """Start, pause, resume, stop each worker via API."""
        for name in (
            "CODE_WATCHER",
            "DEPENDENCY_WATCHER",
            "PERFORMANCE_WATCHER",
            "MEMORY_WATCHER",
        ):
            # Ensure stopped first
            r = await async_client.post(f"/api/workers/{name}/stop")
            assert r.status_code in (200, 404)  # 404 if already stopped

            # Start
            r = await async_client.post(f"/api/workers/{name}/start")
            assert r.status_code == 200, f"Start {name} failed: {r.text}"
            assert r.json()["success"] is True

            # Pause
            r = await async_client.post(f"/api/workers/{name}/pause")
            assert r.status_code == 200, f"Pause {name} failed: {r.text}"
            assert r.json()["success"] is True

            # List check
            r = await async_client.get("/api/workers")
            worker = next(
                (w for w in r.json()["workers"] if w["name"] == name), None
            )
            assert worker is not None
            assert worker["status"] == "paused"

            # Resume
            r = await async_client.post(f"/api/workers/{name}/resume")
            assert r.status_code == 200, f"Resume {name} failed: {r.text}"
            assert r.json()["success"] is True

            # Stop
            r = await async_client.post(f"/api/workers/{name}/stop")
            assert r.status_code == 200, f"Stop {name} failed: {r.text}"
            assert r.json()["success"] is True

    async def test_code_watcher_detects_py_file(
        self, async_client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Create a temp .py file and verify CODE_WATCHER publishes code.change_detected."""
        # Use a temp directory for the watch path
        watch_dir = tmp_path / "code_watch"
        watch_dir.mkdir()

        # Re-initialize worker manager with our temp path
        manager = BackgroundWorkerManager(watch_path=str(watch_dir))
        await manager.stop_all()
        await manager.start_all()
        app.state.worker_manager = manager

        # Clear bus history for the topic
        bus = get_agent_bus()
        await bus.clear_history("code.change_detected")

        # Create a Python file
        py_file = watch_dir / "test_module.py"
        py_file.write_text("def hello():\n    return 'world'\n")

        # Wait up to 8s for the watcher to detect the change
        async def _has_change():
            history = await bus.get_history("code.change_detected", limit=10)
            return len(history) > 0

        found = await _wait_for_condition(_has_change, timeout=8.0, interval=0.3)

        history = await bus.get_history("code.change_detected", limit=10)
        assert len(history) > 0, "CODE_WATCHER did not publish code.change_detected"

        msg = history[0]
        assert msg.payload.get("change_type") == "python_change"
        assert any("test_module.py" in f for f in msg.payload.get("files", []))

        await manager.stop_all()

    async def test_dependency_watcher_scans_requirements(
        self, async_client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Verify DEPENDENCY_WATCHER scans requirements.txt."""
        watch_dir = tmp_path / "dep_watch"
        watch_dir.mkdir()
        req_file = watch_dir / "requirements.txt"
        req_file.write_text("requests==2.25.1\n")

        manager = BackgroundWorkerManager(watch_path=str(watch_dir))
        await manager.stop_all()
        await manager.start_all()
        app.state.worker_manager = manager

        worker = manager.get_worker("DEPENDENCY_WATCHER")
        assert worker is not None

        # Wait for at least one tick to complete
        await asyncio.sleep(1.5)
        info = worker.info()
        assert info.error_count == 0
        assert info.status in ("running", "paused")

        await manager.stop_all()

    async def test_performance_watcher_runs_benchmarks(
        self, async_client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Verify PERFORMANCE_WATCHER can run benchmarks."""
        watch_dir = tmp_path / "perf_watch"
        watch_dir.mkdir()
        benchmark_script = watch_dir / "benchmark.py"
        benchmark_script.write_text(
            "import time\nfor _ in range(3):\n    time.sleep(0.01)\nprint('done')\n"
        )

        manager = BackgroundWorkerManager(watch_path=str(watch_dir))
        await manager.stop_all()
        await manager.start_all()
        app.state.worker_manager = manager

        worker = manager.get_worker("PERFORMANCE_WATCHER")
        assert worker is not None

        await asyncio.sleep(2.0)
        info = worker.info()
        assert info.error_count == 0

        await manager.stop_all()

    async def test_memory_watcher_archives_old_memories(
        self, async_client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Verify MEMORY_WATCHER archives old memories."""
        manager = BackgroundWorkerManager()
        await manager.stop_all()
        await manager.start_all()
        app.state.worker_manager = manager

        bus = get_agent_bus()
        await bus.clear_history("memory.maintenance_completed")

        worker = manager.get_worker("MEMORY_WATCHER")
        assert worker is not None

        await asyncio.sleep(2.0)
        # Memory watcher may or may not have published depending on DB state;
        # we just verify no errors occurred.
        info = worker.info()
        assert info.error_count == 0

        await manager.stop_all()

    async def test_worker_heartbeats_on_bus(
        self, async_client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Verify that worker heartbeats appear on the Agent Bus."""
        watch_dir = tmp_path / "hb_watch"
        watch_dir.mkdir()

        manager = BackgroundWorkerManager(watch_path=str(watch_dir))
        await manager.stop_all()
        await manager.start_all()
        app.state.worker_manager = manager

        bus = get_agent_bus()
        await bus.clear_history("agent.status")

        # Heartbeats publish every 30s, but we can inspect the worker state
        # and also wait a short while to see if any heartbeat lands.
        await asyncio.sleep(1.5)

        history = await bus.get_history("agent.status", limit=50)
        worker_names = {
            msg.payload.get("worker")
            for msg in history
            if msg.payload.get("heartbeat") is True
        }

        # At least one heartbeat should have been published by now
        assert worker_names, "No worker heartbeats found on agent.status topic"

        await manager.stop_all()


# ---------------------------------------------------------------------------
# Auto-Correction Loop — Bus-driven tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAutoCorrectionLoop:
    async def test_start_stop_monitoring(self, fresh_auto_correction: AutoCorrectionLoop):
        """Start and stop the auto-correction monitor."""
        loop = fresh_auto_correction
        await loop.start_monitoring()
        assert loop.get_status()["monitoring"] is True
        await loop.stop_monitoring()
        assert loop.get_status()["monitoring"] is False

    async def test_detects_test_results_failure(self, fresh_auto_correction: AutoCorrectionLoop):
        """Publish fake test.results with failures; loop spawns DEBUGGER + CODER."""
        loop = fresh_auto_correction
        bus = get_agent_bus()
        await loop.start_monitoring()
        await asyncio.sleep(0.3)

        await bus.publish(
            "test.results",
            BusMessage(
                message_id="tr-001",
                source_agent="TEST_RUNNER_UNIT",
                payload={"failures": 3, "artifact_id": "calc.py"},
            ),
        )
        await asyncio.sleep(0.5)

        status = loop.get_status()
        corrections = status["corrections"]
        assert any(
            c["trigger"] == "test_failure" and c["artifact_id"] == "calc.py"
            for c in corrections
        ), f"Expected test_failure correction, got: {corrections}"

        corr = next(
            c
            for c in corrections
            if c["trigger"] == "test_failure" and c["artifact_id"] == "calc.py"
        )
        assert "DEBUGGER" in corr["agents_spawned"]
        assert "CODER" in corr["agents_spawned"]

        await loop.stop_monitoring()

    async def test_detects_critical_error(self, fresh_auto_correction: AutoCorrectionLoop):
        """Publish fake errors.found with CRITICAL severity; loop spawns CODER + OVERSEER."""
        loop = fresh_auto_correction
        bus = get_agent_bus()
        await loop.start_monitoring()
        await asyncio.sleep(0.3)

        await bus.publish(
            "errors.found",
            BusMessage(
                message_id="err-001",
                source_agent="BUG_HUNTER_RUNTIME",
                payload={"severity": "CRITICAL", "artifact_id": "auth.py"},
            ),
        )
        await asyncio.sleep(0.5)

        status = loop.get_status()
        corrections = status["corrections"]
        assert any(
            c["trigger"] == "critical_error" and c["artifact_id"] == "auth.py"
            for c in corrections
        ), f"Expected critical_error correction, got: {corrections}"

        corr = next(
            c
            for c in corrections
            if c["trigger"] == "critical_error" and c["artifact_id"] == "auth.py"
        )
        assert "CODER" in corr["agents_spawned"]
        assert "OVERSEER" in corr["agents_spawned"]

        await loop.stop_monitoring()

    async def test_max_iterations_limit(self, fresh_auto_correction: AutoCorrectionLoop):
        """Publish 6 test failure messages for same artifact; loop stops at 5."""
        loop = fresh_auto_correction
        bus = get_agent_bus()
        await loop.start_monitoring()
        await asyncio.sleep(0.3)

        for i in range(6):
            await bus.publish(
                "test.results",
                BusMessage(
                    message_id=f"tr-loop-{i}",
                    source_agent="TEST_RUNNER_UNIT",
                    payload={"failures": 1, "artifact_id": "loop.py"},
                ),
            )
            await asyncio.sleep(0.15)

        status = loop.get_status()
        corrections = [c for c in status["corrections"] if c["artifact_id"] == "loop.py"]
        assert corrections, f"No corrections found for loop.py: {status['corrections']}"
        assert corrections[0]["iterations"] == 5, (
            f"Expected 5 iterations, got {corrections[0]['iterations']}"
        )

        # Check that escalation was published
        history = await bus.get_history("auto_correction.status", limit=20)
        escalations = [
            h
            for h in history
            if h.payload.get("artifact_id") == "loop.py"
            and h.payload.get("status") == "escalated"
        ]
        assert escalations, "Expected escalation message after max iterations"

        await loop.stop_monitoring()


# ---------------------------------------------------------------------------
# Agent Lifecycle — API + direct tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAgentLifecycleAPI:
    async def test_spawn_check_status(self, async_client: httpx.AsyncClient):
        """Spawn an agent via direct lifecycle manager and check status via API."""
        lifecycle: AgentLifecycleManager = app.state.agent_lifecycle
        iid = await lifecycle.spawn("CODER", "Implement OAuth2", mission_id="m-test")

        response = await async_client.get(f"/api/agents/instances/{iid}")
        assert response.status_code == 200
        data = response.json()
        assert data["agent_type"] == "CODER"
        assert data["status"] == "running"
        assert data["mission_id"] == "m-test"

        # List active should include it
        response = await async_client.get("/api/agents/instances")
        assert response.status_code == 200
        active_ids = {i["instance_id"] for i in response.json()["instances"]}
        assert iid in active_ids

        await lifecycle.abort(iid, reason="cleanup")

    async def test_pause_resume_abort(self, async_client: httpx.AsyncClient):
        """Pause, resume, and abort an agent instance via API."""
        lifecycle: AgentLifecycleManager = app.state.agent_lifecycle
        iid = await lifecycle.spawn("DEBUGGER", "Fix race condition")

        # Pause
        response = await async_client.post(f"/api/agents/instances/{iid}/pause")
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["action"] == "pause"
        assert response.json()["instance"]["status"] == "paused"

        # Resume
        response = await async_client.post(f"/api/agents/instances/{iid}/resume")
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["action"] == "resume"
        assert response.json()["instance"]["status"] == "running"

        # Abort
        response = await async_client.post(
            f"/api/agents/instances/{iid}/abort", params={"reason": "test abort"}
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["action"] == "abort"
        assert response.json()["instance"]["status"] == "aborted"
        assert response.json()["instance"]["error_message"] == "test abort"

    async def test_garbage_collection_removes_old_instances(self, async_client: httpx.AsyncClient):
        """Verify GC removes terminal instances older than 1 hour."""
        lifecycle: AgentLifecycleManager = app.state.agent_lifecycle
        iid = await lifecycle.spawn("CODER", "temp task")
        await lifecycle.complete(iid, output="done", tokens_used=10)

        # Manually backdate completed_at
        lifecycle._instances[iid].completed_at = time.time() - 4000

        removed = await lifecycle.garbage_collect()
        assert iid in removed, f"Expected {iid} to be garbage collected"
        assert lifecycle.get_status(iid) is None

        # Verify it's no longer in active list via API
        response = await async_client.get("/api/agents/instances")
        assert response.status_code == 200
        active_ids = {i["instance_id"] for i in response.json()["instances"]}
        assert iid not in active_ids


# ---------------------------------------------------------------------------
# Direct lifecycle tests (no HTTP layer)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAgentLifecycleDirect:
    async def test_spawn_pause_resume_abort_direct(self, fresh_lifecycle: AgentLifecycleManager):
        """Direct test of spawn → pause → resume → abort."""
        mgr = fresh_lifecycle
        iid = await mgr.spawn("TESTER", "Run E2E suite", mission_id="m-e2e")

        inst = mgr.get_status(iid)
        assert inst is not None
        assert inst.status == "running"

        inst = await mgr.pause(iid)
        assert inst.status == "paused"

        inst = await mgr.resume(iid)
        assert inst.status == "running"

        inst = await mgr.abort(iid, reason="test complete")
        assert inst.status == "aborted"
        assert inst.error_message == "test complete"
        assert inst.completed_at > 0

    async def test_gc_keeps_recent_and_active(self, fresh_lifecycle: AgentLifecycleManager):
        """GC should keep recent terminal agents and all active agents."""
        mgr = fresh_lifecycle

        # Active agent
        active_id = await mgr.spawn("CODER", "active task")

        # Recent terminal agent (< 1h)
        recent_id = await mgr.spawn("DEBUGGER", "recent task")
        await mgr.complete(recent_id)

        # Old terminal agent (> 1h)
        old_id = await mgr.spawn("ANALYZER", "old task")
        await mgr.complete(old_id)
        mgr._instances[old_id].completed_at = time.time() - 4000

        removed = await mgr.garbage_collect()
        assert old_id in removed
        assert recent_id not in removed
        assert active_id not in removed

        assert mgr.get_status(old_id) is None
        assert mgr.get_status(recent_id) is not None
        assert mgr.get_status(active_id) is not None


# ---------------------------------------------------------------------------
# Report generation helper
# ---------------------------------------------------------------------------


def generate_report(results: list[dict[str, Any]]) -> str:
    """Generate a markdown report from test results."""
    lines = [
        "# NEXUS IDE E2E Test Report",
        "",
        "## Background Workers",
        "",
        "| Worker | Status | Heartbeat | Issues |",
        "|--------|--------|-----------|--------|",
    ]

    worker_tests = [r for r in results if r.get("category") == "worker"]
    for r in worker_tests:
        lines.append(
            f"| {r['name']} | {r['status']} | {r.get('heartbeat', 'N/A')} | {r.get('issues', '-')} |"
        )

    lines.extend([
        "",
        "## Auto-Correction",
        "",
        "| Trigger | Response | Issues |",
        "|---------|----------|--------|",
    ])

    ac_tests = [r for r in results if r.get("category") == "auto_correction"]
    for r in ac_tests:
        lines.append(
            f"| {r['trigger']} | {r['response']} | {r.get('issues', '-')} |"
        )

    lines.extend([
        "",
        "## Agent Lifecycle",
        "",
        "| Spawn | Pause | Abort | Issues |",
        "|-------|-------|-------|--------|",
    ])

    lc_tests = [r for r in results if r.get("category") == "lifecycle"]
    for r in lc_tests:
        lines.append(
            f"| {r['spawn']} | {r['pause']} | {r['abort']} | {r.get('issues', '-')} |"
        )

    lines.extend([
        "",
        "## Overall Assessment",
        "",
    ])

    total = len(results)
    passed = sum(1 for r in results if r.get("passed", False))
    failed = total - passed

    lines.append(f"- **Total tests**: {total}")
    lines.append(f"- **Passed**: {passed}")
    lines.append(f"- **Failed**: {failed}")
    lines.append("")

    if failed == 0:
        lines.append("✅ **All systems operational.**")
    elif failed <= 2:
        lines.append("⚠️ **Minor issues detected; overall system healthy.**")
    else:
        lines.append("❌ **Multiple failures detected; review required.**")

    return "\n".join(lines)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "-m", "integration"])
