"""Session Lifecycle Management — garbage collection for stale sessions.

Provides a :class:`SessionLifecycleManager` that can:

* Mark sessions as ``expired`` after they have been inactive for a
  configurable TTL (soft-delete).
* Delete the FK-referenced data (messages, tool executions, …) for
  expired sessions.
* Permanently hard-delete soft-deleted session rows after 7 days.
* Clean up orphan artifacts (unreferenced agent_states, whiteboard
  entries that no longer belong to any active session, …).
* Remove temporary files in ``data/temp/`` older than 24 h.
* Report session stats.

The manager also runs an optional background asyncio loop that
invokes the GC at a configurable interval.  It publishes a
``session.cleanup_completed`` event on the :class:`EventBus` after
each full cycle.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config.settings import get_settings

logger = logging.getLogger(__name__)

# Lazy-imported to avoid circular deps at module level
_db = None
_events = None


def _get_db():
    global _db
    if _db is None:
        from backend.persistence import db as _db
    return _db


def _get_event_bus():
    global _events
    if _events is None:
        from backend.orchestrator.events import OrchestratorEvent as _events
        return _events
    return _events


# ---------------------------------------------------------------------------
# Audit logging — JSONL file in data/audit/
# ---------------------------------------------------------------------------

_AUDIT_DIR = Path(__file__).resolve().parents[2] / "data" / "audit"
_AUDIT_FILE = _AUDIT_DIR / "gc-audit.log"


def _write_audit_entry(entry: dict[str, Any]) -> None:
    """Append a single JSON line to the GC audit log (best-effort)."""
    try:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        with _AUDIT_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError:
        logger.exception("Failed to write GC audit entry")


# ---------------------------------------------------------------------------
# SessionLifecycleManager
# ---------------------------------------------------------------------------


class SessionLifecycleManager:
    """Manages session garbage-collection cycles.

    Usage::

        manager = SessionLifecycleManager(event_bus=app.state.event_bus)
        manager.start()                    # begin background loop
        await manager.run_gc(allow_destructive=True)  # explicit manual cycle
        manager.stop()                     # tear down
    """

    def __init__(
        self,
        event_bus: Any | None = None,
        *,
        ttl_hours: int | None = None,
        gc_interval_minutes: int | None = None,
        temp_dir: Path | None = None,
    ) -> None:
        settings = get_settings()
        self._ttl_hours = ttl_hours if ttl_hours is not None else settings.nexus_session_ttl_hours
        self._gc_interval = (
            gc_interval_minutes if gc_interval_minutes is not None else settings.nexus_gc_interval_minutes
        )
        self._event_bus = event_bus
        self._temp_dir = temp_dir
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._running = False

    # ── Properties ─────────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._running

    @property
    def ttl_hours(self) -> int:
        return self._ttl_hours

    @property
    def gc_interval_minutes(self) -> int:
        return self._gc_interval

    # ── Background loop ─────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background GC loop as a detached asyncio task."""
        if self._task is not None and not self._task.done():
            logger.warning("SessionLifecycleManager background loop is already running")
            return
        loop = asyncio.get_running_loop()
        self._stop_event.clear()
        self._running = True
        self._task = loop.create_task(self._run_loop())
        logger.info(
            "Session GC background loop started (interval=%d min, ttl=%d h)",
            self._gc_interval,
            self._ttl_hours,
        )

    async def stop(self) -> None:
        """Signal the background loop to stop and wait for it to finish."""
        if self._task is None or self._task.done():
            return
        self._stop_event.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        self._running = False
        logger.info("Session GC background loop stopped")

    async def _run_loop(self) -> None:
        """Periodically run garbage collection."""
        self._running = True
        try:
            while not self._stop_event.is_set():
                try:
                    # Background maintenance is deliberately non-destructive.
                    # It inventories stale data and emits an audit event, but
                    # deletion requires the explicit authenticated admin call.
                    await self.run_gc(allow_destructive=False)
                except Exception:
                    logger.exception("Session GC cycle failed")
                # Wait for the configured interval (or until a stop signal)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._gc_interval * 60,
                    )
                    break  # stop event was set
                except TimeoutError:
                    continue  # interval elapsed, run again
        finally:
            self._running = False

    # ── Core GC logic ───────────────────────────────────────────────────

    async def run_gc(self, *, allow_destructive: bool = False) -> dict[str, Any]:
        """Inventory or explicitly execute a GC cycle.

        Destructive work is fail-closed: the periodic background cycle uses
        the default dry-run mode.  Callers must pass ``allow_destructive=True``
        (the authenticated admin endpoint does so) before session content,
        orphan rows, or generated temporary files can be removed.

        Destructive steps:
        1. Soft-delete expired sessions.
        2. Delete orphan data for the newly expired sessions.
        3. Hard-delete session rows that were soft-deleted >7 days ago.
        4. Clean up unreferenced artifacts.
        5. Clean up temporary files older than 24 h.
        """
        db = _get_db()
        report: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "ttl_hours": self._ttl_hours,
            "destructive_cleanup": allow_destructive,
            "cleanup_skipped": not allow_destructive,
            "expired_session_candidates": [],
            "expired_sessions": [],
            "expired_data_counts": {},
            "hard_deleted_ids": [],
            "orphan_artifacts_removed": 0,
            "temp_files_removed": 0,
            "temp_bytes_freed": 0,
        }

        # 1. Find and soft-delete expired sessions
        expired = db.list_expired_sessions(ttl_hours=self._ttl_hours)
        report["expired_session_candidates"] = [session["id"] for session in expired]
        if not allow_destructive:
            try:
                report["stats"] = db.get_session_stats()
            except Exception:
                report["stats"] = {"active": 0, "expired": 0, "total": 0}
            _write_audit_entry({"action": "gc_inventory", **report})
            await self._publish_event(report)
            logger.info(
                "GC inventory complete: %d stale session candidate(s); no data deleted",
                len(report["expired_session_candidates"]),
            )
            return report

        for session in expired:
            sid = session["id"]
            db.mark_session_expired(sid)
            # 2. Delete FK data for newly expired sessions
            counts = db.delete_session_related_data(sid)
            report["expired_sessions"].append(sid)
            report["expired_data_counts"][sid] = counts

        # 3. Hard-delete sessions that have been expired for >= 7 days
        hard_deleted = db.hard_delete_expired_sessions(before_days=7)
        report["hard_deleted_ids"] = hard_deleted

        # 4. Clean up orphan artifacts
        report["orphan_artifacts_removed"] = self._cleanup_orphan_artifacts()

        # 5. Clean up temporary files
        temp_removed, temp_bytes = self._cleanup_temporary_files()
        report["temp_files_removed"] = temp_removed
        report["temp_bytes_freed"] = temp_bytes

        # Stats
        try:
            report["stats"] = db.get_session_stats()
        except Exception:
            report["stats"] = {"active": 0, "expired": 0, "total": 0}

        # Audit log
        _write_audit_entry({"action": "run_gc_destructive", **report})

        # Publish event
        await self._publish_event(report)

        logger.info(
            "GC cycle complete: %d sessions expired, %d hard-deleted, "
            "%d orphans removed, %d temp files freed (%d bytes)",
            len(report["expired_sessions"]),
            len(report["hard_deleted_ids"]),
            report["orphan_artifacts_removed"],
            report["temp_files_removed"],
            report["temp_bytes_freed"],
        )
        return report

    # ── Sub-routines ────────────────────────────────────────────────────

    def _cleanup_orphan_artifacts(self) -> int:
        """Remove agent_states, whiteboard entries, and persistent_memories
        that reference non-existent sessions.

        Returns the total number of orphan rows removed.
        """
        db = _get_db()
        total = 0
        try:
            with db.get_db() as conn:
                # Remove agent_states with no valid session
                cursor = conn.execute(
                    """DELETE FROM agent_states
                       WHERE session_id IS NOT NULL
                         AND session_id != ''
                         AND session_id NOT IN (SELECT id FROM sessions)"""
                )
                total += cursor.rowcount

                # Remove persistent_memories with no valid session
                cursor = conn.execute(
                    """DELETE FROM persistent_memories
                       WHERE session_id IS NOT NULL
                         AND session_id != ''
                         AND session_id NOT IN (SELECT id FROM sessions)"""
                )
                total += cursor.rowcount

                # Remove whiteboard_entries with no valid author session (best-effort)
                # (whiteboard uses author_agent, not session_id — skip)
        except Exception as exc:
            logger.warning("Orphan artifact cleanup failed: %s", exc)
        return total

    def _cleanup_temporary_files(self) -> tuple[int, int]:
        """Remove files in ``data/temp/`` older than 24 hours.

        Returns ``(files_removed, bytes_freed)``.
        """
        temp_dir = self._temp_dir or (Path(__file__).resolve().parents[2] / "data" / "temp")
        if not temp_dir.exists():
            return 0, 0

        cutoff = time.time() - 86400  # 24 hours
        removed = 0
        freed = 0
        try:
            for entry in temp_dir.iterdir():
                try:
                    if entry.is_file() and entry.stat().st_mtime < cutoff:
                        freed += entry.stat().st_size
                        entry.unlink()
                        removed += 1
                    elif entry.is_dir():
                        # Check directory mtime (use the dir itself)
                        mtime = entry.stat().st_mtime
                        age = time.time() - mtime
                        if age > 86400:
                            shutil.rmtree(entry, ignore_errors=True)
                            removed += 1
                except OSError:
                    continue
        except OSError as exc:
            logger.warning("Temp file cleanup failed: %s", exc)
        return removed, freed

    async def _publish_event(self, report: dict[str, Any]) -> None:
        """Publish a ``session.cleanup_completed`` event on the event bus."""
        if self._event_bus is None:
            return
        try:
            from backend.orchestrator.events import EventType, OrchestratorEvent

            await self._event_bus.publish(
                OrchestratorEvent(
                    event_type=EventType.SESSION_CLEANUP_COMPLETED,
                    source="SessionLifecycleManager",
                    data=report,
                )
            )
        except Exception:
            logger.exception("Failed to publish GC completion event")

    # ── Stats (no side effects) ─────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Return session stats without triggering GC."""
        db = _get_db()
        stats = db.get_session_stats()
        return {
            **stats,
            "ttl_hours": self._ttl_hours,
            "gc_interval_minutes": self._gc_interval,
            "running": self._running,
        }


__all__ = ["SessionLifecycleManager"]
