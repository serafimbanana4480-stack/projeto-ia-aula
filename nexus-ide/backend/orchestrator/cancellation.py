"""Request cancellation registry — server-side cancellation for streaming.

When the frontend aborts a request, FastAPI's streaming response naturally
stops, but the agent/side-effects in flight can keep running. This module
provides an explicit cancellation registry so agents and the orchestrator
can be told to abort cooperatively.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CancellationEntry:
    """A registered request that can be cancelled."""

    request_id: str
    session_id: str | None
    event: asyncio.Event = field(default_factory=asyncio.Event)
    created_at: float = field(default_factory=time.monotonic)
    cancelled: bool = False


class CancellationRegistry:
    """In-memory registry of in-flight requests that can be cancelled.

    Each entry exposes an ``asyncio.Event`` that flips when the request is
    cancelled. Streaming loops should periodically check this event and
    abort if set.
    """

    def __init__(self, ttl_seconds: float = 3600.0, cleanup_interval: float = 300.0) -> None:
        self._entries: dict[str, CancellationEntry] = {}
        self._ttl = ttl_seconds
        self._cleanup_interval = cleanup_interval
        self._cleanup_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def register(self, request_id: str | None = None, session_id: str | None = None) -> str:
        """Register a new request and return its ID. Generates UUID if not provided."""
        rid = request_id or str(uuid.uuid4())
        async with self._lock:
            self._entries[rid] = CancellationEntry(request_id=rid, session_id=session_id)
        self._ensure_cleanup_task()
        logger.debug("Registered request %s (session=%s)", rid, session_id)
        return rid

    async def cancel(self, request_id: str) -> bool:
        """Cancel a request. Returns True if it existed and was cancelled."""
        async with self._lock:
            entry = self._entries.get(request_id)
            if entry is None:
                return False
            entry.cancelled = True
            entry.event.set()
        logger.info("Cancelled request %s", request_id)
        return True

    def cancel_sync(self, request_id: str) -> bool:
        """Synchronous cancel (safe to call from non-async contexts)."""
        entry = self._entries.get(request_id)
        if entry is None:
            return False
        entry.cancelled = True
        entry.event.set()
        logger.info("Cancelled request %s (sync)", request_id)
        return True

    def is_cancelled(self, request_id: str) -> bool:
        """Non-blocking check whether a request is cancelled."""
        entry = self._entries.get(request_id)
        return entry.cancelled if entry else False

    async def wait_cancelled(self, request_id: str, timeout: float | None = None) -> bool:
        """Wait until the request is cancelled or timeout. Returns True if cancelled."""
        entry = self._entries.get(request_id)
        if entry is None:
            return False
        if entry.cancelled:
            return True
        try:
            await asyncio.wait_for(entry.event.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    async def unregister(self, request_id: str) -> None:
        """Remove a request from the registry (called when request completes normally)."""
        async with self._lock:
            self._entries.pop(request_id, None)

    def get(self, request_id: str) -> CancellationEntry | None:
        """Get entry (read-only)."""
        return self._entries.get(request_id)

    def stats(self) -> dict[str, Any]:
        """Return registry stats."""
        now = time.monotonic()
        active = sum(1 for e in self._entries.values() if not e.cancelled)
        cancelled = sum(1 for e in self._entries.values() if e.cancelled)
        return {
            "total": len(self._entries),
            "active": active,
            "cancelled": cancelled,
            "oldest_age_s": (
                round(min((now - e.created_at) for e in self._entries.values()), 2)
                if self._entries
                else 0
            ),
        }

    async def cleanup_expired(self) -> int:
        """Remove entries older than TTL. Returns number removed."""
        now = time.monotonic()
        async with self._lock:
            expired = [rid for rid, e in self._entries.items() if (now - e.created_at) > self._ttl]
            for rid in expired:
                self._entries.pop(rid, None)
        if expired:
            logger.debug("Cleaned up %d expired cancellation entries", len(expired))
        return len(expired)

    def _ensure_cleanup_task(self) -> None:
        """Start the background cleanup task if not already running."""
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no running loop yet
        self._cleanup_task = loop.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        """Periodically clean up expired entries."""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self.cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.exception("Cleanup loop error: %s", e)
                # Don't crash the loop
                await asyncio.sleep(60)

    async def shutdown(self) -> None:
        """Cancel the cleanup task (call on app shutdown)."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_registry: CancellationRegistry | None = None


def get_cancellation_registry() -> CancellationRegistry:
    """Get the singleton cancellation registry (creates it if needed)."""
    global _registry
    if _registry is None:
        _registry = CancellationRegistry()
    return _registry


def reset_cancellation_registry() -> None:
    """Reset the singleton (for tests)."""
    global _registry
    _registry = None
