"""Cancellation registry for orchestration runs.

Extracted from :mod:`backend.orchestrator.engine` to keep the main
``OrchestrationEngine`` focused on coordination. ``CancellationRegistry``
owns the per-session cancellation event and the list of running asyncio
tasks, so that ``cancel`` can interrupt a live run without race conditions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class CancellationRegistry:
    """Track cancellation events and active asyncio tasks per session."""

    def __init__(self) -> None:
        self._active_runs: dict[str, asyncio.Task[Any]] = {}
        self._cancellation_events: dict[str, asyncio.Event] = {}
        self._active_tasks: dict[str, list[asyncio.Task[Any]]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Cancellation events
    # ------------------------------------------------------------------

    def create(self, session_id: str) -> asyncio.Event:
        """Return a fresh (cleared) cancellation event for ``session_id`` and store it."""
        event = asyncio.Event()
        self._cancellation_events[session_id] = event
        return event

    def is_cancelled(self, session_id: str) -> bool:
        """Return True if the session's event is set or has never been registered."""
        event = self._cancellation_events.get(session_id)
        if event is None:
            return True
        return event.is_set()

    def cancel(self, session_id: str) -> int:
        """Set the session's cancellation event and cancel its running tasks.

        Returns the number of active tasks that were still running and
        were successfully cancelled.
        """
        event = self._cancellation_events.get(session_id)
        if event is None:
            event = asyncio.Event()
            self._cancellation_events[session_id] = event
        event.set()

        cancelled_count = 0
        # Snapshot and pop the running tasks for this session
        tasks = self._active_tasks.pop(session_id, [])
        for t in tasks:
            if not t.done():
                t.cancel()
                cancelled_count += 1
        return cancelled_count

    def get_event(self, session_id: str) -> asyncio.Event | None:
        """Return the cancellation event for ``session_id`` (creates one if missing)."""
        event = self._cancellation_events.get(session_id)
        if event is None:
            event = self.create(session_id)
        return event

    # ------------------------------------------------------------------
    # Active task tracking
    # ------------------------------------------------------------------

    def register_tasks(self, session_id: str, tasks: list[asyncio.Task]) -> None:
        """Register a list of running asyncio tasks for ``session_id``."""
        self._active_tasks[session_id] = list(tasks)

    def pop_tasks(self, session_id: str) -> list[asyncio.Task]:
        """Remove and return the list of running tasks for ``session_id``."""
        return self._active_tasks.pop(session_id, [])

    def get_tasks(self, session_id: str) -> list[asyncio.Task]:
        """Return (a copy of) the running tasks for ``session_id`` without removing them."""
        return list(self._active_tasks.get(session_id, []))

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def lock(self) -> asyncio.Lock:
        """Expose the registry's lock for callers that need atomic updates."""
        return self._lock
