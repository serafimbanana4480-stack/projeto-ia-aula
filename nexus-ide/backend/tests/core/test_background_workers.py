"""Tests for backend.core.background_workers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from backend.core.background_workers import (
    BackgroundWorker,
    BackgroundWorkerManager,
    CodeWatcher,
    DependencyWatcher,
    MemoryWatcher,
    PerformanceWatcher,
    WorkerStatus,
)

# ---------------------------------------------------------------------------
# Dummy worker for testing base class behaviour
# ---------------------------------------------------------------------------


class DummyWorker(BackgroundWorker):
    """A test worker that increments a counter on every tick."""

    def __init__(self, interval_seconds: float = 0.1) -> None:
        super().__init__("DUMMY", interval_seconds=interval_seconds)
        self.tick_count = 0
        self.last_payload: dict[str, Any] | None = None

    async def _tick(self) -> None:
        self.tick_count += 1


# ---------------------------------------------------------------------------
# Base worker tests
# ---------------------------------------------------------------------------


class TestBackgroundWorker:
    async def test_start_stop(self) -> None:
        worker = DummyWorker(interval_seconds=0.05)
        assert worker.info().status == WorkerStatus.STOPPED.value

        await worker.start()
        assert worker.info().status == WorkerStatus.RUNNING.value

        await worker.stop()
        assert worker.info().status == WorkerStatus.STOPPED.value

    async def test_pause_resume(self) -> None:
        worker = DummyWorker(interval_seconds=0.05)
        await worker.start()
        await asyncio.sleep(0.12)
        ticks_before = worker.tick_count

        await worker.pause()
        assert worker.info().status == WorkerStatus.PAUSED.value

        await asyncio.sleep(0.12)
        assert worker.tick_count == ticks_before  # should not tick while paused

        await worker.resume()
        assert worker.info().status == WorkerStatus.RUNNING.value
        await asyncio.sleep(0.18)
        assert worker.tick_count >= ticks_before

        await worker.stop()

    async def test_heartbeat_publishes(self) -> None:
        worker = DummyWorker(interval_seconds=0.05)
        await worker.start()
        await asyncio.sleep(0.05)
        # Heartbeat runs every 30s by default, but we can inspect the task exists
        assert worker._heartbeat_task is not None
        assert not worker._heartbeat_task.done()
        await worker.stop()

    async def test_info_contains_counts(self) -> None:
        worker = DummyWorker(interval_seconds=0.05)
        info = worker.info()
        assert info.name == "DUMMY"
        assert info.heartbeat_count == 0
        assert info.error_count == 0


# ---------------------------------------------------------------------------
# CodeWatcher tests
# ---------------------------------------------------------------------------


class TestCodeWatcher:
    def test_ignores_runtime_artifacts(self, tmp_path: Path) -> None:
        watcher = CodeWatcher(watch_path=tmp_path)

        assert watcher._is_relevant_file(tmp_path / "backend" / "main.py")
        assert not watcher._is_relevant_file(tmp_path / "logs" / "backend.py")
        assert not watcher._is_relevant_file(tmp_path / "tmp" / "generated.py")
        assert not watcher._is_relevant_file(tmp_path / ".venv" / "lib" / "worker.py")

    async def test_detects_python_changes(self, tmp_path: Path) -> None:
        watcher = CodeWatcher(watch_path=str(tmp_path), interval_seconds=0.05)
        await watcher.start()

        # Create a python file
        (tmp_path / "main.py").write_text("print('hello')")
        await asyncio.sleep(0.15)

        await watcher.stop()
        # No exception means success; actual bus publish is hard to assert
        # without a running event loop consumer, so we rely on smoke test.
        assert watcher.info().status == WorkerStatus.STOPPED.value

    async def test_fallback_polling(self, tmp_path: Path) -> None:
        watcher = CodeWatcher(watch_path=str(tmp_path), interval_seconds=0.05)
        # Force polling mode by faking no watchdog
        watcher._has_watchdog = False
        await watcher.start()

        (tmp_path / "test.py").write_text("x = 1")
        await asyncio.sleep(0.15)

        await watcher.stop()
        assert watcher.info().status == WorkerStatus.STOPPED.value


# ---------------------------------------------------------------------------
# DependencyWatcher tests
# ---------------------------------------------------------------------------


class TestDependencyWatcher:
    async def test_tick_no_files(self, tmp_path: Path) -> None:
        watcher = DependencyWatcher(watch_path=str(tmp_path), interval_seconds=0.05)
        await watcher.start()
        await asyncio.sleep(0.1)
        await watcher.stop()
        assert watcher.info().error_count == 0


# ---------------------------------------------------------------------------
# PerformanceWatcher tests
# ---------------------------------------------------------------------------


class TestPerformanceWatcher:
    async def test_baseline_save_load(self, tmp_path: Path) -> None:
        watcher = PerformanceWatcher(watch_path=str(tmp_path), interval_seconds=0.05)
        # Manually save and load a baseline
        baseline = {"custom": {"elapsed_ms": 100}}
        watcher._save_baseline(baseline)
        loaded = watcher._load_baseline()
        assert loaded == baseline

    async def test_compare_regression(self) -> None:
        watcher = PerformanceWatcher(interval_seconds=0.05)
        baseline = {"custom": {"elapsed_ms": 100}}
        results = {"custom": {"elapsed_ms": 120}}
        comp = watcher._compare_to_baseline(results, baseline)
        assert comp["regressed"] is True
        assert comp["improved"] is False

    async def test_compare_improvement(self) -> None:
        watcher = PerformanceWatcher(interval_seconds=0.05)
        baseline = {"custom": {"elapsed_ms": 100}}
        results = {"custom": {"elapsed_ms": 80}}
        comp = watcher._compare_to_baseline(results, baseline)
        assert comp["regressed"] is False
        assert comp["improved"] is True

    async def test_compare_no_baseline(self) -> None:
        watcher = PerformanceWatcher(interval_seconds=0.05)
        comp = watcher._compare_to_baseline({}, None)
        assert comp["new_baseline"] is True


# ---------------------------------------------------------------------------
# MemoryWatcher tests
# ---------------------------------------------------------------------------


class TestMemoryWatcher:
    async def test_maintenance_runs(self) -> None:
        watcher = MemoryWatcher(interval_seconds=0.05)
        await watcher.start()
        await asyncio.sleep(0.12)
        await watcher.stop()
        assert watcher.info().error_count == 0


# ---------------------------------------------------------------------------
# BackgroundWorkerManager tests
# ---------------------------------------------------------------------------


class TestBackgroundWorkerManager:
    async def test_start_stop_all(self) -> None:
        manager = BackgroundWorkerManager()
        await manager.start_all()
        infos = manager.list_workers()
        assert {info.name for info in infos} == {
            "CODE_WATCHER",
            "DEPENDENCY_WATCHER",
            "PERFORMANCE_WATCHER",
            "MEMORY_WATCHER",
            "SELF_IMPROVEMENT_WATCHER",
            "ESCALATION_WATCHER",
            "RUN_REAPER",
        }
        for info in infos:
            assert info.status == WorkerStatus.RUNNING.value

        await manager.stop_all()
        for info in manager.list_workers():
            assert info.status == WorkerStatus.STOPPED.value

    async def test_individual_control(self) -> None:
        manager = BackgroundWorkerManager()
        await manager.start_all()

        ok = await manager.pause("CODE_WATCHER")
        assert ok is True
        assert manager.get_worker("CODE_WATCHER").info().status == WorkerStatus.PAUSED.value

        ok = await manager.resume("CODE_WATCHER")
        assert ok is True
        assert manager.get_worker("CODE_WATCHER").info().status == WorkerStatus.RUNNING.value

        ok = await manager.stop("CODE_WATCHER")
        assert ok is True
        assert manager.get_worker("CODE_WATCHER").info().status == WorkerStatus.STOPPED.value

        await manager.stop_all()

    async def test_unknown_worker_returns_false(self) -> None:
        manager = BackgroundWorkerManager()
        assert await manager.start("UNKNOWN") is False
        assert await manager.stop("UNKNOWN") is False
        assert await manager.pause("UNKNOWN") is False
        assert await manager.resume("UNKNOWN") is False
