"""Tests for backend.core.file_locks — cross-process safe locking.

Covers:
1. Basic acquire / release for read and write locks.
2. Multiple concurrent readers (shared locks).
3. Writer exclusivity — blocks other writers and readers.
4. Cross-process exclusivity using a subprocess holding a SoftFileLock.
5. Timeout behaviour.
6. Context managers, legacy API, deadlock detection, force release.
7. Auto-expiry.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from multiprocessing import Process
from pathlib import Path
from typing import Any

import pytest

from backend.core.file_locks import (
    DeadlockError,
    FileLockManager,
    LockError,
    _cross_process_lock_path,
    _filelock_enabled,
    _readers_count_path,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def manager() -> FileLockManager:
    """Return a fresh FileLockManager instance (reset singleton)."""
    # Reset singleton so tests are isolated
    FileLockManager._instance = None  # type: ignore[misc]
    m = FileLockManager()
    m._init_storage()
    return m


@pytest.fixture
def dummy_file(tmp_path: Path) -> str:
    """Return the path of a temporary file."""
    p = tmp_path / "dummy.txt"
    p.write_text("hello")
    return str(p)


# ---------------------------------------------------------------------------
# 1. Basic acquire / release
# ---------------------------------------------------------------------------

class TestBasicAcquireRelease:
    async def test_acquire_read_lock_returns_id(self, manager: FileLockManager, dummy_file: str) -> None:
        lock_id = await manager.acquire_read_lock(dummy_file, "agent-a")
        assert isinstance(lock_id, str) and len(lock_id) > 0
        manager.release_lock(dummy_file, "agent-a")

    async def test_acquire_write_lock_returns_id(self, manager: FileLockManager, dummy_file: str) -> None:
        lock_id = await manager.acquire_write_lock(dummy_file, "agent-b")
        assert isinstance(lock_id, str) and len(lock_id) > 0
        manager.release_lock(dummy_file, "agent-b")

    async def test_release_lock_removes_holder(self, manager: FileLockManager, dummy_file: str) -> None:
        await manager.acquire_read_lock(dummy_file, "agent-c")
        assert manager.is_locked(dummy_file)
        manager.release_lock(dummy_file, "agent-c")
        assert not manager.is_locked(dummy_file)

    async def test_release_lock_unknown_is_noop(self, manager: FileLockManager, dummy_file: str) -> None:
        # Should not raise
        manager.release_lock(dummy_file, "nobody")

    async def test_get_lock_status(self, manager: FileLockManager, dummy_file: str) -> None:
        await manager.acquire_write_lock(dummy_file, "agent-d", timeout=10.0)
        status = manager.get_lock_status(dummy_file)
        assert status["locked"] is True
        assert len(status["holders"]) == 1
        assert status["holders"][0]["agent"] == "agent-d"
        assert status["holders"][0]["type"] == "write"
        manager.release_lock(dummy_file, "agent-d")


# ---------------------------------------------------------------------------
# 2. Multiple readers (shared locks)
# ---------------------------------------------------------------------------

class TestSharedReaders:
    async def test_multiple_readers_allowed(self, manager: FileLockManager, dummy_file: str) -> None:
        id1 = await manager.acquire_read_lock(dummy_file, "r1")
        id2 = await manager.acquire_read_lock(dummy_file, "r2")
        status = manager.get_lock_status(dummy_file)
        assert status["locked"] is True
        assert len(status["holders"]) == 2
        manager.release_lock(dummy_file, "r1")
        manager.release_lock(dummy_file, "r2")
        assert not manager.is_locked(dummy_file)

    async def test_reader_blocks_writer(self, manager: FileLockManager, dummy_file: str) -> None:
        await manager.acquire_read_lock(dummy_file, "r1")
        with pytest.raises(LockError):
            await manager.acquire_write_lock(dummy_file, "w1", timeout=0.2)
        manager.release_lock(dummy_file, "r1")


# ---------------------------------------------------------------------------
# 3. Writer exclusivity
# ---------------------------------------------------------------------------

class TestWriterExclusivity:
    async def test_writer_blocks_other_writer(self, manager: FileLockManager, dummy_file: str) -> None:
        await manager.acquire_write_lock(dummy_file, "w1")
        with pytest.raises(LockError):
            await manager.acquire_write_lock(dummy_file, "w2", timeout=0.2)
        manager.release_lock(dummy_file, "w1")

    async def test_writer_blocks_reader(self, manager: FileLockManager, dummy_file: str) -> None:
        await manager.acquire_write_lock(dummy_file, "w1")
        with pytest.raises(LockError):
            await manager.acquire_read_lock(dummy_file, "r1", timeout=0.2)
        manager.release_lock(dummy_file, "w1")

    async def test_writer_blocks_then_allows_reader_after_release(self, manager: FileLockManager, dummy_file: str) -> None:
        await manager.acquire_write_lock(dummy_file, "w1")
        with pytest.raises(LockError):
            await manager.acquire_read_lock(dummy_file, "r1", timeout=0.2)
        manager.release_lock(dummy_file, "w1")
        # After release, reader should succeed
        lock_id = await manager.acquire_read_lock(dummy_file, "r1", timeout=1.0)
        assert lock_id
        manager.release_lock(dummy_file, "r1")


# ---------------------------------------------------------------------------
# 4. Cross-process exclusivity (real concurrency)
# ---------------------------------------------------------------------------

class TestCrossProcess:
    async def test_write_lock_blocks_subprocess_writer(self, manager: FileLockManager, dummy_file: str) -> None:
        """A write lock held by this process must block a subprocess trying
        to acquire the same cross-process SoftFileLock."""
        if not _filelock_enabled():
            pytest.skip("filelock not available")

        await manager.acquire_write_lock(dummy_file, "main")

        # Build a small Python script that runs in a subprocess and tries
        # to acquire the same cross-process lock.
        lock_path = _cross_process_lock_path(dummy_file, "write")
        script = (
            "import sys, time\n"
            "from filelock import SoftFileLock, Timeout\n"
            f"lock = SoftFileLock({lock_path!r})\n"
            "try:\n"
            "    lock.acquire(timeout=0.5)\n"
            "    print('ACQUIRED')\n"
            "    lock.release()\n"
            "except Timeout:\n"
            "    print('BLOCKED')\n"
        )

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        result = stdout.decode().strip()

        manager.release_lock(dummy_file, "main")
        assert result == "BLOCKED", f"Expected BLOCKED, got {result!r} stderr={stderr.decode()!r}"

    async def test_read_lock_allows_subprocess_reader(self, manager: FileLockManager, dummy_file: str) -> None:
        """Multiple readers (this process + subprocess) should both succeed."""
        if not _filelock_enabled():
            pytest.skip("filelock not available")

        await manager.acquire_read_lock(dummy_file, "main")

        # Subprocess script: acquire read lock via the same protocol
        count_path = _readers_count_path(dummy_file)
        mutex_path = _cross_process_lock_path(dummy_file, "readers_mutex")
        write_path = _cross_process_lock_path(dummy_file, "write")
        script = (
            "import json, sys\n"
            "from filelock import SoftFileLock, Timeout\n"
            f"mutex = SoftFileLock({mutex_path!r})\n"
            "mutex.acquire(timeout=2.0)\n"
            f"count_path = {count_path!r}\n"
            "try:\n"
            "    with open(count_path, 'r') as f:\n"
            "        data = json.load(f)\n"
            "        count = data.get('count', 0)\n"
            "except Exception:\n"
            "    count = 0\n"
            "if count == 0:\n"
            f"    write_lock = SoftFileLock({write_path!r})\n"
            "    write_lock.acquire(timeout=2.0)\n"
            "else:\n"
            "    write_lock = None\n"
            "count += 1\n"
            "with open(count_path, 'w') as f:\n"
            "    json.dump({'count': count}, f)\n"
            "mutex.release()\n"
            "print('ACQUIRED')\n"
            "# cleanup\n"
            "mutex.acquire(timeout=2.0)\n"
            "with open(count_path, 'r') as f:\n"
            "    data = json.load(f)\n"
            "    count = data.get('count', 0) - 1\n"
            "with open(count_path, 'w') as f:\n"
            "    json.dump({'count': count}, f)\n"
            "if count == 0 and write_lock is not None:\n"
            "    write_lock.release()\n"
            "mutex.release()\n"
            "print('RELEASED')\n"
        )

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        lines = stdout.decode().strip().splitlines()

        manager.release_lock(dummy_file, "main")
        assert "ACQUIRED" in lines, f"stderr={stderr.decode()!r}"
        assert "RELEASED" in lines


# ---------------------------------------------------------------------------
# 5. Timeout
# ---------------------------------------------------------------------------

class TestTimeout:
    async def test_read_timeout_waiting_on_write(self, manager: FileLockManager, dummy_file: str) -> None:
        await manager.acquire_write_lock(dummy_file, "w1")
        with pytest.raises(LockError):
            await manager.acquire_read_lock(dummy_file, "r1", timeout=0.1)
        manager.release_lock(dummy_file, "w1")

    async def test_write_timeout_waiting_on_read(self, manager: FileLockManager, dummy_file: str) -> None:
        await manager.acquire_read_lock(dummy_file, "r1")
        with pytest.raises(LockError):
            await manager.acquire_write_lock(dummy_file, "w1", timeout=0.1)
        manager.release_lock(dummy_file, "r1")


# ---------------------------------------------------------------------------
# 6. Context managers & legacy API
# ---------------------------------------------------------------------------

class TestContextManagers:
    async def test_read_lock_context_manager(self, manager: FileLockManager, dummy_file: str) -> None:
        async with manager.read_lock(dummy_file, "ctx-r", timeout=1.0):
            assert manager.is_locked(dummy_file)
        assert not manager.is_locked(dummy_file)

    async def test_write_lock_context_manager(self, manager: FileLockManager, dummy_file: str) -> None:
        async with manager.write_lock(dummy_file, "ctx-w", timeout=1.0):
            assert manager.is_locked(dummy_file)
        assert not manager.is_locked(dummy_file)

    async def test_legacy_acquire_lock(self, manager: FileLockManager, dummy_file: str) -> None:
        lock_id = await manager.acquire_lock(dummy_file, "read", "legacy", timeout_seconds=1.0)
        assert lock_id
        manager.release_lock_by_id(lock_id)
        assert not manager.is_locked(dummy_file)

    async def test_release_lock_by_id_missing_raises(self, manager: FileLockManager) -> None:
        with pytest.raises(LockError):
            manager.release_lock_by_id("non-existent-id")


# ---------------------------------------------------------------------------
# 7. Deadlock detection
# ---------------------------------------------------------------------------

class TestDeadlock:
    async def test_deadlock_detected(self, manager: FileLockManager, dummy_file: str) -> None:
        # Simulate a deadlock by forcing the wait graph
        await manager.acquire_write_lock(dummy_file + "_a", "agent-x", timeout=1.0)
        await manager.acquire_write_lock(dummy_file + "_b", "agent-y", timeout=1.0)

        # Manually inject wait edges (normally done by _acquire_lock polling)
        manager._wait_graph["agent-x"].add(dummy_file + "_b")
        manager._wait_graph["agent-y"].add(dummy_file + "_a")

        deadlocked = manager.detect_deadlock()
        assert "agent-x" in deadlocked
        assert "agent-y" in deadlocked

        manager.release_lock(dummy_file + "_a", "agent-x")
        manager.release_lock(dummy_file + "_b", "agent-y")


# ---------------------------------------------------------------------------
# 8. Force release & wait
# ---------------------------------------------------------------------------

class TestForceRelease:
    async def test_force_release_clears_all(self, manager: FileLockManager, dummy_file: str) -> None:
        await manager.acquire_read_lock(dummy_file, "r1")
        await manager.acquire_read_lock(dummy_file, "r2")
        assert manager.get_lock_status(dummy_file)["holders"].__len__() == 2
        count = manager.force_release(dummy_file)
        assert count == 2
        assert not manager.is_locked(dummy_file)

    async def test_wait_for_lock(self, manager: FileLockManager, dummy_file: str) -> None:
        await manager.acquire_write_lock(dummy_file, "w1")

        async def releaser() -> None:
            await asyncio.sleep(0.2)
            manager.release_lock(dummy_file, "w1")

        asyncio.create_task(releaser())
        ok = await manager.wait_for_lock(dummy_file, timeout_seconds=2.0)
        assert ok is True
        assert not manager.is_locked(dummy_file)

    async def test_wait_for_lock_timeout(self, manager: FileLockManager, dummy_file: str) -> None:
        await manager.acquire_write_lock(dummy_file, "w1")
        ok = await manager.wait_for_lock(dummy_file, timeout_seconds=0.1)
        assert ok is False
        manager.release_lock(dummy_file, "w1")


# ---------------------------------------------------------------------------
# 9. Auto-expiry
# ---------------------------------------------------------------------------

class TestAutoExpiry:
    async def test_lock_expires(self, manager: FileLockManager, dummy_file: str) -> None:
        lock_id = await manager.acquire_write_lock(dummy_file, "w1", timeout=0.2)
        assert manager.is_locked(dummy_file)
        await asyncio.sleep(0.3)
        # After prune, lock should be gone
        manager._prune_expired()
        assert not manager.is_locked(dummy_file)

    async def test_acquire_reuses_path_after_expiry(self, manager: FileLockManager, dummy_file: str) -> None:
        await manager.acquire_write_lock(dummy_file, "w1", timeout=0.2)
        await asyncio.sleep(0.3)
        # Should succeed because previous lock expired
        lock_id = await manager.acquire_write_lock(dummy_file, "w2", timeout=1.0)
        assert lock_id
        manager.release_lock(dummy_file, "w2")


# ---------------------------------------------------------------------------
# 10. Cross-process readers counter file
# ---------------------------------------------------------------------------

class TestReadersCounter:
    async def test_counter_file_created_for_read_lock(self, manager: FileLockManager, dummy_file: str) -> None:
        if not _filelock_enabled():
            pytest.skip("filelock not available")

        await manager.acquire_read_lock(dummy_file, "r1")
        count_path = _readers_count_path(dummy_file)
        assert Path(count_path).exists()
        data = json.loads(Path(count_path).read_text())
        assert data["count"] == 1
        manager.release_lock(dummy_file, "r1")
        # Counter file may be cleaned up on last release
        assert not Path(count_path).exists()

    async def test_counter_increments_for_multiple_readers(self, manager: FileLockManager, dummy_file: str) -> None:
        if not _filelock_enabled():
            pytest.skip("filelock not available")

        await manager.acquire_read_lock(dummy_file, "r1")
        await manager.acquire_read_lock(dummy_file, "r2")
        count_path = _readers_count_path(dummy_file)
        data = json.loads(Path(count_path).read_text())
        assert data["count"] == 2
        manager.release_lock(dummy_file, "r1")
        manager.release_lock(dummy_file, "r2")
