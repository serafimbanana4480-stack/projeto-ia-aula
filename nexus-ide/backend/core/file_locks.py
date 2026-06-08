"""File lock manager for NEXUS IDE.

Prevents corruption when multiple agents write to the same file concurrently.
Supports shared read locks and exclusive write locks with automatic expiry,
deadlock detection, and administrative override capabilities.

**Cross-process safety**: Uses ``filelock.AsyncFileLock`` as a process-level
barrier so that multiple Uvicorn workers (or separate Python processes)
coordinate safely.  The in-memory structures remain for deadlock detection
and metrics.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncGenerator, ClassVar

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cross-process lock support
# ---------------------------------------------------------------------------
try:
    from filelock import AsyncFileLock as _AsyncFileLock

    _FILELOCK_AVAILABLE = True
except Exception:  # pragma: no cover
    _FILELOCK_AVAILABLE = False
    _AsyncFileLock = None  # type: ignore[misc,assignment]


def _cross_process_lock_path(file_path: str) -> str:
    """Return a deterministic lock-file path for *file_path*.

    The lock file is stored under the system temp directory so it is writable
    on all platforms and does not pollute the project tree.
    """
    # Hash the absolute path to get a short, deterministic filename
    import hashlib

    abs_path = str(Path(file_path).resolve())
    path_hash = hashlib.sha256(abs_path.encode()).hexdigest()[:16]
    lock_name = f"nexus_filelock_{path_hash}.lock"
    return str(Path(tempfile.gettempdir()) / lock_name)


def _filelock_enabled() -> bool:
    """Return whether the cross-process filelock layer should be used.

    This is evaluated at *call time* so that tests can toggle the behaviour
    via the ``NEXUS_DISABLE_FILELOCK`` environment variable.
    """
    return (
        _FILELOCK_AVAILABLE
        and os.environ.get("NEXUS_DISABLE_FILELOCK", "").lower() not in ("1", "true", "yes")
    )


class LockError(Exception):
    """Raised when a lock cannot be acquired or is invalid."""


class DeadlockError(LockError):
    """Raised when acquiring a lock would cause a deadlock."""


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


class FileLockManager:
    """Singleton manager for concurrent file locking across agents.

    Features:
    - Multiple simultaneous **read** locks (shared).
    - Exclusive **write** locks (blocks reads and other writes).
    - Auto-expiry to prevent permanent blocks.
    - Deadlock detection via a wait-for graph.
    - asyncio-safe internal state.

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
        # Cross-process file locks (filelock) — one per file_path
        self._filelock_map: dict[str, asyncio.Lock] = {}

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
            # Release cross-process lock if this was the last holder
            if hasattr(lock, "_cross_proc_lock") and lock._cross_proc_lock is not None:
                try:
                    lock._cross_proc_lock.release()
                except Exception:
                    pass
                lock._cross_proc_lock = None
            if hasattr(lock, "_cross_proc_async_lock") and lock._cross_proc_async_lock is not None:
                try:
                    lock._cross_proc_async_lock.release()
                except Exception:
                    pass
                lock._cross_proc_async_lock = None

        if not locks:
            del self._locks[file_path]
            # Clean up stale lock file on disk if no in-memory locks remain
            if _filelock_enabled():
                lock_file = Path(_cross_process_lock_path(file_path))
                try:
                    if lock_file.exists():
                        lock_file.unlink()
                except OSError:
                    pass

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
                    # Release cross-process lock if this was the last holder
                    if hasattr(lock, "_cross_proc_lock") and lock._cross_proc_lock is not None:
                        try:
                            lock._cross_proc_lock.release()
                        except Exception:
                            pass
                        lock._cross_proc_lock = None
                    if hasattr(lock, "_cross_proc_async_lock") and lock._cross_proc_async_lock is not None:
                        try:
                            lock._cross_proc_async_lock.release()
                        except Exception:
                            pass
                        lock._cross_proc_async_lock = None
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
        # Build the wait-for graph: owner -> set of owners they are waiting on
        graph: dict[str, set[str]] = defaultdict(set)

        for owner, file_paths in self._wait_graph.items():
            for fp in file_paths:
                for lock in self._locks.get(fp, []):
                    if not lock.is_expired():
                        graph[owner].add(lock.owner)

        # DFS for cycles
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
        return count

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def _normalise_path(file_path: str) -> str:
        """Return a canonical, absolute path string."""
        from pathlib import Path

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
            if not locks:
                del self._locks[file_path]

    async def _wait_for_predicate(
        self,
        file_path: str,
        lock_type: str,
        owner: str,
    ) -> None:
        """Poll until the predicate for acquiring the lock becomes true.

        This is used with ``asyncio.wait_for`` to implement a cancellable
        blocking wait without holding the internal mutex.
        """
        while True:
            await asyncio.sleep(0.1)
            async with self._mutex:
                self._prune_expired()
                if self._can_acquire(file_path, lock_type, owner):
                    return

    async def _acquire_lock(
        self,
        file_path: str,
        lock_type: str,
        owner: str,
        timeout_seconds: float,
    ) -> str:
        """Internal implementation of lock acquisition.

        Acquires a cross-process ``filelock`` *only* when the in-memory lock
        becomes available.  This avoids holding an OS-level lock while
        waiting for other asyncio tasks, and guarantees safety even when
        multiple Uvicorn workers run in separate OS processes.
        """
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
                    fl: Any = None
                    fl_async: asyncio.Lock | None = None
                    if _filelock_enabled() and _AsyncFileLock is not None:
                        lock_file = _cross_process_lock_path(file_path)
                        if file_path not in self._filelock_map:
                            self._filelock_map[file_path] = asyncio.Lock()
                        fl_async = self._filelock_map[file_path]
                        try:
                            await asyncio.wait_for(
                                fl_async.acquire(),
                                timeout=min(timeout_seconds, 1.0),
                            )
                        except asyncio.TimeoutError:
                            raise LockError(
                                f"Timeout waiting for cross-process lock on {file_path}"
                            )
                        fl = _AsyncFileLock(lock_file)
                        try:
                            await asyncio.wait_for(
                                fl.acquire(),
                                timeout=min(timeout_seconds, 5.0),
                            )
                        except asyncio.TimeoutError:
                            fl_async.release()
                            raise LockError(
                                f"Timeout acquiring cross-process lock on {file_path}"
                            )

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
                    if fl is not None:
                        lock._cross_proc_lock = fl  # type: ignore[attr-defined]
                        lock._cross_proc_async_lock = fl_async  # type: ignore[attr-defined]
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
