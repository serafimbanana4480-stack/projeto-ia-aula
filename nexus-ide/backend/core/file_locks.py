"""File lock manager for NEXUS IDE.

Prevents corruption when multiple agents write to the same file concurrently.
Supports shared read locks and exclusive write locks with automatic expiry,
deadlock detection, and administrative override capabilities.

**Cross-process safety**: Uses ``filelock.SoftFileLock`` (synchronous variant
wrapped with ``asyncio.to_thread``) as a process-level barrier so that
multiple Uvicorn workers (or separate Python processes) coordinate safely.
The in-memory structures remain for deadlock detection and metrics.

Shared read locks across processes are implemented with a dedicated
*readers counter* file protected by its own mutex lock, as requested in the
refactoring spec.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, ClassVar

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cross-process lock support
# ---------------------------------------------------------------------------
try:
    from filelock import SoftFileLock, Timeout

    _FILELOCK_AVAILABLE = True
except Exception:  # pragma: no cover
    _FILELOCK_AVAILABLE = False
    SoftFileLock = None  # type: ignore[misc,assignment]
    Timeout = None  # type: ignore[misc,assignment]


def _cross_process_lock_path(file_path: str, suffix: str = "write") -> str:
    """Return a deterministic lock-file path for *file_path*."""
    abs_path = str(Path(file_path).resolve())
    path_hash = hashlib.sha256(abs_path.encode()).hexdigest()[:16]
    lock_name = f"nexus_filelock_{suffix}_{path_hash}.lock"
    return str(Path(tempfile.gettempdir()) / lock_name)


def _readers_count_path(file_path: str) -> str:
    """Return a deterministic path for the readers counter file."""
    abs_path = str(Path(file_path).resolve())
    path_hash = hashlib.sha256(abs_path.encode()).hexdigest()[:16]
    return str(Path(tempfile.gettempdir()) / f"nexus_readers_count_{path_hash}.json")


def _filelock_enabled() -> bool:
    """Return whether the cross-process filelock layer should be used."""
    return (
        _FILELOCK_AVAILABLE
        and os.environ.get("NEXUS_DISABLE_FILELOCK", "").lower() not in ("1", "true", "yes")
    )


# ---------------------------------------------------------------------------
# Distributed lock via Redis (single-instance Redlock simplification)
# ---------------------------------------------------------------------------
# Acquire:  SET <key> <token> NX PX <ttl>
# Release:  Lua script that DELs only if the stored value still equals the
#           caller's token (prevents releasing a lock owned by another holder).
#
# Heartbeat / renewal is intentionally omitted for simplicity. Long-running
# critical sections must complete within ``REDIS_LOCK_TTL_MS``; otherwise the
# Redis key auto-expires and another worker may acquire it. Tune
# ``NEXUS_LOCK_REDIS_TTL_MS`` if longer holds are required.
REDIS_LOCK_TTL_MS = int(os.environ.get("NEXUS_LOCK_REDIS_TTL_MS", "30000"))
REDIS_LOCK_KEY_PREFIX = os.environ.get("NEXUS_LOCK_REDIS_PREFIX", "nexus:lock:")
REDIS_LOCK_CONNECT_TIMEOUT = float(os.environ.get("NEXUS_LOCK_REDIS_CONNECT_TIMEOUT", "1.0"))
REDIS_LOCK_RETRY_INTERVAL = float(os.environ.get("NEXUS_LOCK_REDIS_RETRY", "0.1"))
REDIS_LOCK_UNAVAILABLE_COOLDOWN = float(
    os.environ.get("NEXUS_LOCK_REDIS_COOLDOWN", "5.0")
)

# Lua release script — atomic compare-and-delete.
_REDIS_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


class _RedisUnavailable(Exception):
    """Signals that Redis is offline/unconfigured; callers must use fallback."""


# Module-level cached Redis client and unavailability cooldown.
_redis_client: Any = None
_redis_unavailable_until: float = 0.0


def _mark_redis_unavailable(cooldown: float = REDIS_LOCK_UNAVAILABLE_COOLDOWN) -> None:
    """Mark Redis as unavailable for *cooldown* seconds and drop the client."""
    global _redis_client, _redis_unavailable_until
    _redis_client = None
    _redis_unavailable_until = time.monotonic() + cooldown


def _redis_lock_key(file_path: str) -> str:
    """Return the Redis key used for the distributed write lock on *file_path*."""
    abs_path = str(Path(file_path).resolve())
    path_hash = hashlib.sha256(abs_path.encode()).hexdigest()[:16]
    return f"{REDIS_LOCK_KEY_PREFIX}write:{path_hash}"


async def _redis_lock_client() -> Any:
    """Lazily obtain a short-timeout async Redis client, or ``None`` if offline.

    The client is created with a short connect/socket timeout so that a
    down/unconfigured Redis is detected within ~1s and never blocks the caller.
    A successful ``PING`` is required before the client is cached.
    """
    global _redis_client, _redis_unavailable_until
    now = time.monotonic()
    if _redis_client is not None:
        return _redis_client
    if now < _redis_unavailable_until:
        return None
    try:
        import redis.asyncio as aioredis  # type: ignore[import-not-found]
    except Exception:
        _mark_redis_unavailable(cooldown=30.0)
        logger.debug("redis package not importable; distributed locks disabled")
        return None

    host = os.environ.get("REDIS_HOST", "localhost")
    port = int(os.environ.get("REDIS_PORT", "6379"))
    db = int(os.environ.get("REDIS_DB", "0"))
    password = os.environ.get("REDIS_PASSWORD") or None
    client = aioredis.Redis(
        host=host,
        port=port,
        db=db,
        password=password,
        socket_connect_timeout=REDIS_LOCK_CONNECT_TIMEOUT,
        socket_timeout=REDIS_LOCK_CONNECT_TIMEOUT,
        decode_responses=True,
    )
    try:
        await asyncio.wait_for(client.ping(), timeout=REDIS_LOCK_CONNECT_TIMEOUT)
    except Exception as exc:
        _mark_redis_unavailable()
        logger.warning(
            "Redis unavailable for distributed file locks (%s); "
            "using in-memory/filelock fallback",
            exc,
        )
        try:
            await client.aclose()
        except Exception:  # pragma: no cover - best effort cleanup
            pass
        return None
    _redis_client = client
    return client


class RedisDistributedLock:
    """Redis-backed distributed lock using ``SET NX PX`` + Lua release.

    This is a single-instance simplification of Redlock: it provides mutual
    exclusion across processes/workers as long as they all talk to the same
    Redis instance. It does *not* provide the fencing guarantees of full
    Redlock across multiple Redis nodes.
    """

    def __init__(
        self,
        ttl_ms: int = REDIS_LOCK_TTL_MS,
        retry_interval: float = REDIS_LOCK_RETRY_INTERVAL,
    ) -> None:
        self._ttl_ms = ttl_ms
        self._retry_interval = retry_interval

    async def acquire(self, key: str, timeout: float) -> str:
        """Try to acquire *key* within *timeout* seconds.

        Returns the unique token on success.

        Raises:
            _RedisUnavailable: if Redis is offline/unconfigured — the caller
                must fall back to the in-memory/filelock layer.
            LockError: if the lock could not be acquired within *timeout*
                because another holder owns it.
        """
        token = uuid.uuid4().hex
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        first_attempt = True
        while True:
            client = await _redis_lock_client()
            if client is None:
                raise _RedisUnavailable()
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise LockError(f"Timeout acquiring distributed lock on {key}")
            try:
                ok = await asyncio.wait_for(
                    client.set(key, token, nx=True, px=self._ttl_ms),
                    timeout=min(remaining, REDIS_LOCK_CONNECT_TIMEOUT),
                )
            except Exception as exc:
                _mark_redis_unavailable()
                logger.warning(
                    "Redis SET failed for lock %s (%s); using fallback", key, exc
                )
                raise _RedisUnavailable() from exc
            if ok:
                return token
            if first_attempt:
                logger.debug("Distributed lock %s contended; retrying", key)
                first_attempt = False
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise LockError(f"Timeout acquiring distributed lock on {key}")
            await asyncio.sleep(min(self._retry_interval, remaining))

    async def release(self, key: str, token: str) -> bool:
        """Safely release *key* only if *token* still owns it.

        Returns ``True`` if the lock was released, ``False`` otherwise (e.g.
        the lock expired or is held by another token). Never raises on Redis
        errors — a failed release simply lets the TTL expire the key.
        """
        client = await _redis_lock_client()
        if client is None:
            return False
        try:
            res = await asyncio.wait_for(
                client.eval(_REDIS_RELEASE_SCRIPT, 1, key, token),
                timeout=REDIS_LOCK_CONNECT_TIMEOUT,
            )
            return bool(res)
        except Exception:
            logger.debug("Redis lock release failed for %s", key, exc_info=True)
            return False


_redis_lock: RedisDistributedLock | None = None


def _get_redis_lock() -> RedisDistributedLock:
    """Return the cached :class:`RedisDistributedLock` singleton."""
    global _redis_lock
    if _redis_lock is None:
        _redis_lock = RedisDistributedLock()
    return _redis_lock


def _redis_lock_enabled() -> bool:
    """Return whether the Redis distributed lock layer should be attempted."""
    return os.environ.get("NEXUS_DISABLE_REDIS_LOCK", "").lower() not in (
        "1",
        "true",
        "yes",
    )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class LockError(Exception):
    """Raised when a lock cannot be acquired or is invalid."""


class DeadlockError(LockError):
    """Raised when acquiring a lock would cause a deadlock."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class FileLock:
    """Represents an active lock on a file.

    Attributes:
        file_path: Absolute path to the locked file.
        lock_type: Either ``"read"`` (shared) or ``"write"`` (exclusive).
        owner: Identifier of the agent that owns the lock.
        acquired_at: UTC timestamp when the lock was acquired.
        expires_at: UTC timestamp when the lock auto-expires.
        lock_id: Unique identifier for this lock instance.
    """

    file_path: str
    lock_type: str
    owner: str
    acquired_at: datetime
    expires_at: datetime
    lock_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        if self.lock_type not in ("read", "write"):
            raise ValueError(f"Invalid lock_type: {self.lock_type!r}")

    def is_expired(self) -> bool:
        """Return ``True`` if the lock has passed its expiry time."""
        return datetime.now(timezone.utc) >= self.expires_at


# ---------------------------------------------------------------------------
# Cross-process helpers (synchronous — safe to call from async via to_thread)
# ---------------------------------------------------------------------------
def _cleanup_stale_lock(lock_path: str, timeout: float) -> None:
    """Remove a stale SoftFileLock file if it is older than *timeout* × 2."""
    path = Path(lock_path)
    if not path.exists():
        return
    try:
        mtime = path.stat().st_mtime
        age = datetime.now(timezone.utc).timestamp() - mtime
        if age > timeout * 2:
            logger.warning("Removing stale lock file %s (age=%.1fs)", lock_path, age)
            path.unlink(missing_ok=True)
    except OSError:
        logger.debug("Failed to cleanup stale lock %s", lock_path, exc_info=True)


def _read_readers_count(count_path: str) -> int:
    """Read the current reader count from disk."""
    try:
        with open(count_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return int(data.get("count", 0))
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return 0


def _write_readers_count(count_path: str, count: int) -> None:
    """Persist the reader count to disk."""
    with open(count_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "count": count,
                "updated": datetime.now(timezone.utc).isoformat(),
            },
            f,
        )


def _sync_acquire_soft_lock(lock_path: str, timeout: float) -> SoftFileLock:
    """Synchronously acquire a SoftFileLock, cleaning stale files first."""
    if SoftFileLock is None:
        raise LockError("filelock is not available")
    _cleanup_stale_lock(lock_path, timeout)
    lock = SoftFileLock(lock_path, thread_local=False)
    try:
        lock.acquire(timeout=timeout)
    except Timeout as exc:
        raise LockError(f"Timeout acquiring cross-process lock on {lock_path}") from exc
    return lock


def _sync_release_soft_lock(lock: SoftFileLock | None) -> None:
    """Synchronously release a SoftFileLock, swallowing errors."""
    if lock is None:
        return
    try:
        lock.release()
    except Exception:
        logger.debug("Failed to release soft lock", exc_info=True)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------
class FileLockManager:
    """Singleton manager for concurrent file locking across agents.

    Features:
    - Multiple simultaneous **read** locks (shared, both in-process and
      cross-process via a readers counter).
    - Exclusive **write** locks (blocks reads and other writes).
    - Auto-expiry to prevent permanent blocks.
    - Deadlock detection via a wait-for graph.
    - asyncio-safe internal state.
    - Cross-process safety via ``filelock.SoftFileLock``.

    Usage:
        manager = FileLockManager()
        lock_id = await manager.acquire_read_lock("/path/to/file", "agent-1")
        ...
        manager.release_lock("/path/to/file", "agent-1")
    """

    _instance: ClassVar[FileLockManager | None] = None
    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    def __new__(cls) -> FileLockManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_storage()
        return cls._instance

    def _init_storage(self) -> None:
        """Initialise internal storage (called once by ``__new__``)."""
        # file_path -> list of FileLock
        self._locks: dict[str, list[FileLock]] = defaultdict(list)
        # owner -> set of file_paths they are waiting on
        self._wait_graph: dict[str, set[str]] = defaultdict(set)
        # Internal asyncio lock protecting the above structures
        self._mutex = asyncio.Lock()
        # Cross-process SoftFileLock instances cached per path
        self._filelock_map: dict[str, SoftFileLock] = {}

    # --------------------------------------------------------------------- #
    # Required public API
    # --------------------------------------------------------------------- #

    async def acquire_read_lock(
        self,
        file_path: str,
        agent_name: str,
        timeout: float = 60.0,
    ) -> str:
        """Acquire a shared read lock on *file_path*.

        Args:
            file_path: Absolute or relative path to the target file.
            agent_name: Unique identifier for the requesting agent.
            timeout: Maximum time to wait for the lock (seconds). The
                acquired lock itself will also expire after this duration.

        Returns:
            The unique *lock_id* for the acquired lock.

        Raises:
            LockError: If the lock cannot be acquired within the timeout.
            DeadlockError: If granting the lock would create a deadlock.
        """
        lock_id = await self._acquire_lock(file_path, "read", agent_name, timeout)
        logger.info(
            "Read lock acquired on %s by %s (lock_id=%s)",
            file_path,
            agent_name,
            lock_id,
        )
        return lock_id

    async def acquire_write_lock(
        self,
        file_path: str,
        agent_name: str,
        timeout: float = 60.0,
    ) -> str:
        """Acquire an exclusive write lock on *file_path*.

        Args:
            file_path: Absolute or relative path to the target file.
            agent_name: Unique identifier for the requesting agent.
            timeout: Maximum time to wait for the lock (seconds). The
                acquired lock itself will also expire after this duration.

        Returns:
            The unique *lock_id* for the acquired lock.

        Raises:
            LockError: If the lock cannot be acquired within the timeout.
            DeadlockError: If granting the lock would create a deadlock.
        """
        lock_id = await self._acquire_lock(file_path, "write", agent_name, timeout)
        logger.info(
            "Write lock acquired on %s by %s (lock_id=%s)",
            file_path,
            agent_name,
            lock_id,
        )
        return lock_id

    def release_lock(self, file_path: str, agent_name: str) -> None:
        """Release all locks held by *agent_name* on *file_path*.

        Args:
            file_path: Path to the file to unlock.
            agent_name: The agent whose locks should be released.
        """
        file_path = self._normalise_path(file_path)
        locks = self._locks.get(file_path, [])
        to_remove = [lock for lock in locks if lock.owner == agent_name]

        if not to_remove:
            logger.warning(
                "release_lock called for %s on %s but no lock found",
                agent_name,
                file_path,
            )
            return

        for lock in to_remove:
            locks.remove(lock)
            logger.info(
                "Lock released on %s by %s (type=%s, lock_id=%s)",
                file_path,
                agent_name,
                lock.lock_type,
                lock.lock_id,
            )
            # Release cross-process resources (Redis and/or filelock).
            self._release_cross_process_lock(lock)

        if not locks:
            del self._locks[file_path]

    def get_lock_status(self, file_path: str) -> dict:
        """Return the current lock status for *file_path*.

        Args:
            file_path: Path to the file to inspect.

        Returns:
            Dict with ``locked`` (bool), ``path``, and ``holders`` list.
            Each holder entry contains ``agent``, ``type``, ``since``,
            and ``expires_at``.
        """
        file_path = self._normalise_path(file_path)
        self._prune_expired()
        locks = self._locks.get(file_path, [])
        holders = []
        for lock in locks:
            holders.append(
                {
                    "agent": lock.owner,
                    "type": lock.lock_type,
                    "since": lock.acquired_at.isoformat(),
                    "expires_at": lock.expires_at.isoformat(),
                }
            )
        return {
            "path": file_path,
            "locked": len(holders) > 0,
            "holders": holders,
        }

    @asynccontextmanager
    async def read_lock(
        self,
        file_path: str,
        agent_name: str,
        timeout: float = 60.0,
    ) -> AsyncGenerator[None, None]:
        """Async context manager for a read lock."""
        await self.acquire_read_lock(file_path, agent_name, timeout)
        try:
            yield
        finally:
            self.release_lock(file_path, agent_name)

    @asynccontextmanager
    async def write_lock(
        self,
        file_path: str,
        agent_name: str,
        timeout: float = 60.0,
    ) -> AsyncGenerator[None, None]:
        """Async context manager for a write lock."""
        await self.acquire_write_lock(file_path, agent_name, timeout)
        try:
            yield
        finally:
            self.release_lock(file_path, agent_name)

    # --------------------------------------------------------------------- #
    # Legacy / internal API
    # --------------------------------------------------------------------- #

    async def acquire_lock(
        self,
        file_path: str,
        lock_type: str,
        owner: str,
        timeout_seconds: float = 30.0,
    ) -> str:
        """Acquire a lock on *file_path*.

        .. deprecated::
            Use :meth:`acquire_read_lock` or :meth:`acquire_write_lock` instead.

        Returns:
            The unique *lock_id* for the acquired lock.
        """
        return await self._acquire_lock(file_path, lock_type, owner, timeout_seconds)

    def release_lock_by_id(self, lock_id: str) -> None:
        """Release the lock identified by *lock_id*.

        .. deprecated::
            Use :meth:`release_lock` instead.

        Raises:
            LockError: If *lock_id* does not exist.
        """
        found = False
        for file_path, locks in list(self._locks.items()):
            for lock in locks:
                if lock.lock_id == lock_id:
                    locks.remove(lock)
                    found = True
                    logger.info(
                        "Lock released by id: %s %s on %s by %s",
                        lock.lock_type,
                        lock_id,
                        file_path,
                        lock.owner,
                    )
                    self._release_cross_process_lock(lock)
                    break
            if not locks:
                del self._locks[file_path]
            if found:
                break

        if not found:
            raise LockError(f"Lock {lock_id!r} not found")

    # --------------------------------------------------------------------- #
    # Additional helpers
    # --------------------------------------------------------------------- #

    def is_locked(self, file_path: str) -> bool:
        """Return ``True`` if *file_path* currently has any active lock."""
        file_path = self._normalise_path(file_path)
        locks = self._locks.get(file_path, [])
        return any(not lock.is_expired() for lock in locks)

    def get_lock_owner(self, file_path: str) -> str:
        """Return the owner of the **first** active lock on *file_path*.

        Returns an empty string if the file is not locked.
        """
        file_path = self._normalise_path(file_path)
        for lock in self._locks.get(file_path, []):
            if not lock.is_expired():
                return lock.owner
        return ""

    async def wait_for_lock(
        self,
        file_path: str,
        timeout_seconds: float = 30.0,
    ) -> bool:
        """Wait until *file_path* is no longer locked by anyone.

        Args:
            file_path: Path to the file to monitor.
            timeout_seconds: Maximum time to wait.

        Returns:
            ``True`` if the file became unlocked, ``False`` on timeout.
        """
        file_path = self._normalise_path(file_path)
        deadline = asyncio.get_event_loop().time() + timeout_seconds

        while self.is_locked(file_path):
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(0.1, remaining))

        return True

    def detect_deadlock(self) -> list[str]:
        """Detect deadlocks using a cycle search in the wait-for graph.

        Returns:
            A list of agent names involved in a deadlock cycle.
            Empty list if no deadlock is detected.
        """
        graph: dict[str, set[str]] = defaultdict(set)

        for owner, file_paths in self._wait_graph.items():
            for fp in file_paths:
                for lock in self._locks.get(fp, []):
                    if not lock.is_expired():
                        graph[owner].add(lock.owner)

        visited: set[str] = set()
        rec_stack: set[str] = set()
        cycle_nodes: set[str] = set()

        def _dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbour in graph.get(node, set()):
                if neighbour not in visited:
                    if _dfs(neighbour):
                        cycle_nodes.add(node)
                        return True
                elif neighbour in rec_stack:
                    cycle_nodes.add(node)
                    cycle_nodes.add(neighbour)
                    return True
            rec_stack.remove(node)
            return False

        for node in list(graph.keys()):
            if node not in visited:
                _dfs(node)

        return list(cycle_nodes)

    def force_release(self, file_path: str) -> int:
        """Administrative override: forcibly release **all** locks on *file_path*.

        Args:
            file_path: Path to the file to unlock.

        Returns:
            Number of locks that were released.
        """
        file_path = self._normalise_path(file_path)
        locks = self._locks.pop(file_path, [])
        count = len(locks)
        for lock in locks:
            logger.warning(
                "Force-released %s lock %s on %s (owner=%s)",
                lock.lock_type,
                lock.lock_id,
                file_path,
                lock.owner,
            )
            self._release_cross_process_lock(lock)
        return count

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def _normalise_path(file_path: str) -> str:
        """Return a canonical, absolute path string."""
        return str(Path(file_path).resolve())

    def _can_acquire(self, file_path: str, lock_type: str, owner: str) -> bool:
        """Check whether *owner* can acquire *lock_type* on *file_path* now."""
        current_locks = self._locks.get(file_path, [])

        if not current_locks:
            return True

        if lock_type == "read":
            # Read lock allowed if no write lock is held
            return all(lock.lock_type == "read" for lock in current_locks)

        # Write lock is exclusive
        return False

    def _prune_expired(self) -> None:
        """Remove expired locks from internal state."""
        for file_path, locks in list(self._locks.items()):
            expired = [lock for lock in locks if lock.is_expired()]
            for lock in expired:
                locks.remove(lock)
                logger.info(
                    "Auto-expired %s lock %s on %s (owner=%s)",
                    lock.lock_type,
                    lock.lock_id,
                    file_path,
                    lock.owner,
                )
                self._release_cross_process_lock(lock)
            if not locks:
                del self._locks[file_path]

    async def _wait_for_predicate(
        self,
        file_path: str,
        lock_type: str,
        owner: str,
    ) -> None:
        """Poll until the predicate for acquiring the lock becomes true."""
        while True:
            await asyncio.sleep(0.1)
            async with self._mutex:
                self._prune_expired()
                if self._can_acquire(file_path, lock_type, owner):
                    return

    # --------------------------------------------------------------------- #
    # Cross-process helpers
    # --------------------------------------------------------------------- #

    def _get_or_create_soft_lock(self, lock_path: str) -> SoftFileLock:
        """Return a cached SoftFileLock instance for *lock_path*."""
        if lock_path not in self._filelock_map:
            self._filelock_map[lock_path] = SoftFileLock(lock_path, thread_local=False)
        return self._filelock_map[lock_path]

    async def _acquire_cross_process_write_lock(
        self, file_path: str, timeout: float
    ) -> SoftFileLock:
        """Acquire the exclusive cross-process write lock."""
        lock_path = _cross_process_lock_path(file_path, "write")
        lock = self._get_or_create_soft_lock(lock_path)
        try:
            await asyncio.to_thread(lock.acquire, timeout=timeout)
        except Timeout as exc:
            raise LockError(
                f"Timeout acquiring cross-process write lock on {file_path}"
            ) from exc
        return lock

    async def _acquire_cross_process_read_lock(
        self, file_path: str, timeout: float
    ) -> tuple[SoftFileLock, SoftFileLock | None]:
        """Acquire cross-process resources for a read lock.

        Returns:
            A tuple of *(readers_mutex_lock, write_lock_or_None)*.
            The mutex must be released by the caller after updating the
            in-memory state (we release it immediately inside this helper).
        """
        deadline = asyncio.get_event_loop().time() + timeout
        mutex_path = _cross_process_lock_path(file_path, "readers_mutex")
        write_path = _cross_process_lock_path(file_path, "write")
        count_path = _readers_count_path(file_path)

        # 1. Acquire readers mutex
        mutex_lock = self._get_or_create_soft_lock(mutex_path)
        try:
            await asyncio.to_thread(mutex_lock.acquire, timeout=timeout)
        except Timeout as exc:
            raise LockError(
                f"Timeout waiting for readers mutex on {file_path}"
            ) from exc

        write_lock: SoftFileLock | None = None
        try:
            count = _read_readers_count(count_path)
            if count == 0:
                # First reader: block writers from other processes
                write_lock = self._get_or_create_soft_lock(write_path)
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise LockError(
                        f"Timeout acquiring cross-process read lock on {file_path}"
                    )
                try:
                    await asyncio.to_thread(write_lock.acquire, timeout=remaining)
                except Timeout as exc:
                    raise LockError(
                        f"Timeout acquiring cross-process read lock on {file_path}"
                    ) from exc

            count += 1
            _write_readers_count(count_path, count)
        except Exception:
            # On any failure, release the mutex before re-raising
            _sync_release_soft_lock(mutex_lock)
            raise

        # Release mutex so other readers can enter
        _sync_release_soft_lock(mutex_lock)
        return mutex_lock, write_lock

    def _schedule_redis_release(self, key: str, token: str) -> None:
        """Best-effort async release of a Redis distributed lock.

        Called from synchronous release paths. If no running event loop is
        available the release is skipped — the Redis TTL will expire the key.
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
        if loop.is_closed():
            return
        try:
            loop.create_task(_get_redis_lock().release(key, token))
        except RuntimeError:
            # No running loop in the current thread — rely on TTL expiry.
            logger.debug(
                "No running loop to release Redis lock %s; relying on TTL", key
            )

    def _release_cross_process_lock(self, lock: FileLock) -> None:
        """Synchronously release cross-process resources held by *lock*.

        Redis releases are scheduled as background tasks (best-effort): the
        Redis key has a TTL, so a missed release simply expires the lock
        instead of leaking it permanently.
        """
        file_path = lock.file_path
        if lock.lock_type == "write":
            redis_token = getattr(lock, "_redis_token", None)
            redis_key = getattr(lock, "_redis_key", None)
            if redis_token is not None and redis_key is not None:
                self._schedule_redis_release(redis_key, redis_token)
                return
            if not _filelock_enabled():
                return
            write_path = _cross_process_lock_path(file_path, "write")
            fl = self._filelock_map.pop(write_path, None)
            _sync_release_soft_lock(fl)
        else:
            if not _filelock_enabled():
                return
            # Read lock: decrement counter, release write lock if last reader
            mutex_path = _cross_process_lock_path(file_path, "readers_mutex")
            count_path = _readers_count_path(file_path)
            write_path = _cross_process_lock_path(file_path, "write")

            mutex_lock = self._filelock_map.get(mutex_path)
            if mutex_lock is None:
                # Best-effort: create a new instance just to acquire & release
                mutex_lock = SoftFileLock(mutex_path, thread_local=False)
                self._filelock_map[mutex_path] = mutex_lock

            try:
                mutex_lock.acquire(timeout=5.0)
            except Exception:
                logger.warning(
                    "Could not acquire readers mutex to release read lock on %s",
                    file_path,
                )
                return

            try:
                count = _read_readers_count(count_path)
                count = max(0, count - 1)
                _write_readers_count(count_path, count)
                if count == 0:
                    write_lock = self._filelock_map.pop(write_path, None)
                    _sync_release_soft_lock(write_lock)
                    # Clean up counter file
                    try:
                        Path(count_path).unlink(missing_ok=True)
                    except OSError:
                        logger.debug("Failed to unlink readers count file %s", count_path, exc_info=True)
            finally:
                _sync_release_soft_lock(mutex_lock)

    # --------------------------------------------------------------------- #
    # Core acquisition logic
    # --------------------------------------------------------------------- #

    async def _acquire_lock(
        self,
        file_path: str,
        lock_type: str,
        owner: str,
        timeout_seconds: float,
    ) -> str:
        """Internal implementation of lock acquisition."""
        file_path = self._normalise_path(file_path)

        if lock_type not in ("read", "write"):
            raise ValueError(f"lock_type must be 'read' or 'write', got {lock_type!r}")

        acquired = False
        lock_id = ""
        deadline = asyncio.get_event_loop().time() + timeout_seconds

        async with self._mutex:
            self._prune_expired()

        while not acquired:
            async with self._mutex:
                self._prune_expired()

                deadlocked = self.detect_deadlock()
                if deadlocked and owner in deadlocked:
                    self._wait_graph[owner].discard(file_path)
                    raise DeadlockError(
                        f"Deadlock detected for agent {owner!r} on {file_path}"
                    )

                if self._can_acquire(file_path, lock_type, owner):
                    # ------------------------------------------------------
                    # Cross-process lock (filelock) — only when we are
                    # about to really take the in-memory lock.
                    # ------------------------------------------------------
                    cross_proc_locks: list[SoftFileLock] = []
                    redis_token: str | None = None
                    redis_key: str | None = None
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        raise LockError(
                            f"Timeout acquiring {lock_type} lock on {file_path} for {owner!r}"
                        )
                    if lock_type == "write" and _redis_lock_enabled():
                        # Prefer the Redis distributed lock for cross-worker
                        # mutual exclusion; fall back to filelock if Redis is
                        # offline/unconfigured.
                        rlock = _get_redis_lock()
                        rkey = _redis_lock_key(file_path)
                        try:
                            redis_token = await rlock.acquire(rkey, remaining)
                            redis_key = rkey
                        except _RedisUnavailable:
                            redis_token = None
                            redis_key = None
                            remaining = deadline - asyncio.get_event_loop().time()
                            if remaining <= 0:
                                raise LockError(
                                    f"Timeout acquiring {lock_type} lock on "
                                    f"{file_path} for {owner!r}"
                                )
                        # LockError (contention timeout) propagates naturally.

                    if (
                        lock_type == "write"
                        and redis_token is None
                        and _filelock_enabled()
                    ):
                        fl = await self._acquire_cross_process_write_lock(
                            file_path, remaining
                        )
                        cross_proc_locks.append(fl)
                    elif lock_type == "read" and _filelock_enabled():
                        _mutex_fl, _write_fl = await self._acquire_cross_process_read_lock(
                            file_path, remaining
                        )
                        if _write_fl is not None:
                            cross_proc_locks.append(_write_fl)

                    lock = FileLock(
                        file_path=file_path,
                        lock_type=lock_type,
                        owner=owner,
                        acquired_at=datetime.now(timezone.utc),
                        expires_at=datetime.now(timezone.utc)
                        + timedelta(seconds=timeout_seconds),
                    )
                    self._locks[file_path].append(lock)
                    lock_id = lock.lock_id
                    acquired = True
                    self._wait_graph[owner].discard(file_path)
                    # Attach cross-process handles for cleanup in release_lock
                    if cross_proc_locks:
                        lock._cross_proc_locks = cross_proc_locks  # type: ignore[attr-defined]
                    if redis_token is not None:
                        lock._redis_token = redis_token  # type: ignore[attr-defined]
                        lock._redis_key = redis_key  # type: ignore[attr-defined]
                    logger.debug(
                        "Lock acquired: %s %s on %s by %s",
                        lock_type,
                        lock_id,
                        file_path,
                        owner,
                    )
                else:
                    self._wait_graph[owner].add(file_path)

            if not acquired:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    async with self._mutex:
                        self._wait_graph[owner].discard(file_path)
                    raise LockError(
                        f"Timeout acquiring {lock_type} lock on {file_path} for {owner!r}"
                    )
                try:
                    await asyncio.wait_for(
                        self._wait_for_predicate(file_path, lock_type, owner),
                        timeout=remaining,
                    )
                except asyncio.TimeoutError:
                    async with self._mutex:
                        self._wait_graph[owner].discard(file_path)
                    raise LockError(
                        f"Timeout acquiring {lock_type} lock on {file_path} for {owner!r}"
                    )

        return lock_id


# --------------------------------------------------------------------- #
# Standalone convenience context managers
# --------------------------------------------------------------------- #
_default_manager = FileLockManager()


@asynccontextmanager
async def read_lock(
    file_path: str,
    agent_name: str,
    timeout: float = 60.0,
) -> AsyncGenerator[None, None]:
    """Async context manager for a read lock using the default manager."""
    async with _default_manager.read_lock(file_path, agent_name, timeout):
        yield


@asynccontextmanager
async def write_lock(
    file_path: str,
    agent_name: str,
    timeout: float = 60.0,
) -> AsyncGenerator[None, None]:
    """Async context manager for a write lock using the default manager."""
    async with _default_manager.write_lock(file_path, agent_name, timeout):
        yield
