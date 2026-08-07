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
import sys
from pathlib import Path

import pytest

from backend.core.file_locks import (
    FileLockManager,
    LockError,
    RedisDistributedLock,
    _cross_process_lock_path,
    _filelock_enabled,
    _readers_count_path,
    _redis_lock_enabled,
    _redis_lock_key,
    _RedisUnavailable,
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
    async def test_acquire_read_lock_returns_id(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
        lock_id = await manager.acquire_read_lock(dummy_file, "agent-a")
        assert isinstance(lock_id, str) and len(lock_id) > 0
        manager.release_lock(dummy_file, "agent-a")

    async def test_acquire_write_lock_returns_id(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
        lock_id = await manager.acquire_write_lock(dummy_file, "agent-b")
        assert isinstance(lock_id, str) and len(lock_id) > 0
        manager.release_lock(dummy_file, "agent-b")

    async def test_release_lock_removes_holder(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
        await manager.acquire_read_lock(dummy_file, "agent-c")
        assert manager.is_locked(dummy_file)
        manager.release_lock(dummy_file, "agent-c")
        assert not manager.is_locked(dummy_file)

    async def test_release_lock_unknown_is_noop(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
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
    async def test_multiple_readers_allowed(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
        await manager.acquire_read_lock(dummy_file, "r1")
        await manager.acquire_read_lock(dummy_file, "r2")
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
    async def test_writer_blocks_other_writer(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
        await manager.acquire_write_lock(dummy_file, "w1")
        with pytest.raises(LockError):
            await manager.acquire_write_lock(dummy_file, "w2", timeout=0.2)
        manager.release_lock(dummy_file, "w1")

    async def test_writer_blocks_reader(self, manager: FileLockManager, dummy_file: str) -> None:
        await manager.acquire_write_lock(dummy_file, "w1")
        with pytest.raises(LockError):
            await manager.acquire_read_lock(dummy_file, "r1", timeout=0.2)
        manager.release_lock(dummy_file, "w1")

    async def test_writer_blocks_then_allows_reader_after_release(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
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
    async def test_write_lock_blocks_subprocess_writer(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
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
            sys.executable,
            "-c",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        result = stdout.decode().strip()

        manager.release_lock(dummy_file, "main")
        assert result == "BLOCKED", f"Expected BLOCKED, got {result!r} stderr={stderr.decode()!r}"

    async def test_read_lock_allows_subprocess_reader(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
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
            sys.executable,
            "-c",
            script,
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
    async def test_read_timeout_waiting_on_write(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
        await manager.acquire_write_lock(dummy_file, "w1")
        with pytest.raises(LockError):
            await manager.acquire_read_lock(dummy_file, "r1", timeout=0.1)
        manager.release_lock(dummy_file, "w1")

    async def test_write_timeout_waiting_on_read(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
        await manager.acquire_read_lock(dummy_file, "r1")
        with pytest.raises(LockError):
            await manager.acquire_write_lock(dummy_file, "w1", timeout=0.1)
        manager.release_lock(dummy_file, "r1")


# ---------------------------------------------------------------------------
# 6. Context managers & legacy API
# ---------------------------------------------------------------------------


class TestContextManagers:
    async def test_read_lock_context_manager(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
        async with manager.read_lock(dummy_file, "ctx-r", timeout=1.0):
            assert manager.is_locked(dummy_file)
        assert not manager.is_locked(dummy_file)

    async def test_write_lock_context_manager(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
        # Write locks probe the optional Redis distributed-lock backend first
        # (see file_locks.py's _redis_lock_client), which itself waits up to
        # REDIS_LOCK_CONNECT_TIMEOUT (default 1.0s) before falling back to
        # the in-memory/filelock path when Redis is unreachable — true for
        # any dev/CI box without a local Redis. A 1.0s lock timeout left no
        # margin after that probe and made this test flaky in exactly that
        # (common) setup; 3.0s gives headroom without weakening the
        # assertion, which is unchanged.
        async with manager.write_lock(dummy_file, "ctx-w", timeout=3.0):
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
    async def test_force_release_clears_all(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
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
        await manager.acquire_write_lock(dummy_file, "w1", timeout=0.2)
        assert manager.is_locked(dummy_file)
        await asyncio.sleep(0.3)
        # After prune, lock should be gone
        manager._prune_expired()
        assert not manager.is_locked(dummy_file)

    async def test_acquire_reuses_path_after_expiry(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
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
    async def test_counter_file_created_for_read_lock(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
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

    async def test_counter_increments_for_multiple_readers(
        self, manager: FileLockManager, dummy_file: str
    ) -> None:
        if not _filelock_enabled():
            pytest.skip("filelock not available")

        await manager.acquire_read_lock(dummy_file, "r1")
        await manager.acquire_read_lock(dummy_file, "r2")
        count_path = _readers_count_path(dummy_file)
        data = json.loads(Path(count_path).read_text())
        assert data["count"] == 2
        manager.release_lock(dummy_file, "r1")
        manager.release_lock(dummy_file, "r2")


# ---------------------------------------------------------------------------
# 11. Redis distributed lock (SEC-001)
# ---------------------------------------------------------------------------
class FakeRedisClient:
    """Minimal in-process fake of ``redis.asyncio.Redis`` for lock tests.

    Implements only the subset used by :class:`RedisDistributedLock`:
    ``ping``, ``set`` (with ``nx``/``px``), ``eval`` (simulating the Lua
    compare-and-delete), ``get`` and ``aclose``.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def ping(self) -> bool:
        return True

    async def set(
        self,
        key: str,
        value: str,
        nx: bool = False,
        px: int | None = None,
    ) -> bool:
        if nx and key in self._store:
            return False
        self._store[key] = value
        return True

    async def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        if self._store.get(key) == token:
            del self._store[key]
            return 1
        return 0

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedisClient:
    """Patch ``_redis_lock_client`` to return a :class:`FakeRedisClient`."""
    client = FakeRedisClient()

    async def _fake_client() -> FakeRedisClient:
        return client

    monkeypatch.setattr("backend.core.file_locks._redis_lock_client", _fake_client)
    # Reset the cached singleton so the patched client is used.
    monkeypatch.setattr("backend.core.file_locks._redis_client", None, raising=False)
    monkeypatch.setattr("backend.core.file_locks._redis_unavailable_until", 0.0, raising=False)
    return client


@pytest.fixture
def redis_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch ``_redis_lock_client`` to simulate Redis being offline."""

    async def _no_client() -> None:
        return None

    monkeypatch.setattr("backend.core.file_locks._redis_lock_client", _no_client)
    monkeypatch.setattr("backend.core.file_locks._redis_client", None, raising=False)
    monkeypatch.setattr("backend.core.file_locks._redis_unavailable_until", 0.0, raising=False)


@pytest.fixture
def no_filelock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the filelock layer so only Redis / in-memory is exercised."""
    monkeypatch.setenv("NEXUS_DISABLE_FILELOCK", "1")


class TestRedisDistributedLock:
    """Unit tests for the Redis lock helper (no real Redis required)."""

    async def test_acquire_release_roundtrip(self, fake_redis: FakeRedisClient) -> None:
        lock = RedisDistributedLock(ttl_ms=1000)
        key = "nexus:lock:write:abc"
        token = await lock.acquire(key, timeout=1.0)
        assert isinstance(token, str) and len(token) > 0
        assert await fake_redis.get(key) == token
        released = await lock.release(key, token)
        assert released is True
        assert await fake_redis.get(key) is None

    async def test_mutual_exclusion(self, fake_redis: FakeRedisClient) -> None:
        lock = RedisDistributedLock(ttl_ms=10000, retry_interval=0.05)
        key = "nexus:lock:write:mtx"
        token1 = await lock.acquire(key, timeout=1.0)
        assert token1
        # A second acquisition on the same key must time out (LockError).
        with pytest.raises(LockError):
            await lock.acquire(key, timeout=0.2)
        # The first holder is unaffected.
        assert await fake_redis.get(key) == token1
        # After release, a new acquisition succeeds with a fresh token.
        assert await lock.release(key, token1) is True
        token2 = await lock.acquire(key, timeout=1.0)
        assert token2 and token2 != token1
        await lock.release(key, token2)

    async def test_safe_release_wrong_token(self, fake_redis: FakeRedisClient) -> None:
        lock = RedisDistributedLock(ttl_ms=10000)
        key = "nexus:lock:write:safe"
        token = await lock.acquire(key, timeout=1.0)
        # Releasing with an alien token must NOT delete the lock.
        released = await lock.release(key, "deadbeef" + "0" * 24)
        assert released is False
        assert await fake_redis.get(key) == token
        # Releasing with the correct token succeeds.
        assert await lock.release(key, token) is True
        assert await fake_redis.get(key) is None

    async def test_acquire_raises_when_redis_unavailable(self, redis_offline: None) -> None:
        lock = RedisDistributedLock()
        with pytest.raises(_RedisUnavailable):
            await lock.acquire("nexus:lock:write:offline", timeout=1.0)

    async def test_release_noop_when_redis_unavailable(self, redis_offline: None) -> None:
        lock = RedisDistributedLock()
        released = await lock.release("nexus:lock:write:offline", "sometoken")
        assert released is False


class TestManagerRedisFallback:
    """Integration of the Redis layer into ``FileLockManager``."""

    async def test_write_lock_falls_back_inmemory_when_redis_offline(
        self,
        manager: FileLockManager,
        dummy_file: str,
        redis_offline: None,
        no_filelock: None,
    ) -> None:
        # Redis offline + filelock disabled → only in-memory asyncio locking.
        lock_id = await manager.acquire_write_lock(dummy_file, "agent-a", timeout=1.0)
        assert lock_id
        assert manager.is_locked(dummy_file)
        manager.release_lock(dummy_file, "agent-a")
        assert not manager.is_locked(dummy_file)

    async def test_write_lock_uses_redis_when_available(
        self,
        manager: FileLockManager,
        dummy_file: str,
        fake_redis: FakeRedisClient,
        no_filelock: None,
    ) -> None:
        assert _redis_lock_enabled()
        lock_id = await manager.acquire_write_lock(dummy_file, "agent-a", timeout=1.0)
        assert lock_id
        # The Redis key should be present in the fake store.
        rkey = _redis_lock_key(dummy_file)
        assert await fake_redis.get(rkey) is not None
        manager.release_lock(dummy_file, "agent-a")
        # Allow the scheduled background release task to run.
        await asyncio.sleep(0.1)
        assert await fake_redis.get(rkey) is None
        assert not manager.is_locked(dummy_file)

    async def test_redis_write_lock_blocks_second_holder(
        self,
        manager: FileLockManager,
        dummy_file: str,
        fake_redis: FakeRedisClient,
        no_filelock: None,
    ) -> None:
        # First acquisition takes the Redis lock.
        await manager.acquire_write_lock(dummy_file, "agent-a", timeout=1.0)
        rkey = _redis_lock_key(dummy_file)
        token_a = await fake_redis.get(rkey)
        assert token_a is not None
        # Simulate a second *process* by directly contending on the same Redis
        # key via a fresh RedisDistributedLock instance (bypassing the in-memory
        # singleton, which would block the second acquire in-process anyway).
        other = RedisDistributedLock(ttl_ms=10000, retry_interval=0.05)
        with pytest.raises(LockError):
            await other.acquire(rkey, timeout=0.2)
        # The first holder's token is untouched.
        assert await fake_redis.get(rkey) == token_a
        manager.release_lock(dummy_file, "agent-a")
        await asyncio.sleep(0.1)
        assert await fake_redis.get(rkey) is None

    async def test_read_lock_still_works_with_redis_offline(
        self,
        manager: FileLockManager,
        dummy_file: str,
        redis_offline: None,
        no_filelock: None,
    ) -> None:
        id1 = await manager.acquire_read_lock(dummy_file, "r1", timeout=1.0)
        id2 = await manager.acquire_read_lock(dummy_file, "r2", timeout=1.0)
        assert id1 and id2
        assert len(manager.get_lock_status(dummy_file)["holders"]) == 2
        manager.release_lock(dummy_file, "r1")
        manager.release_lock(dummy_file, "r2")
        assert not manager.is_locked(dummy_file)
