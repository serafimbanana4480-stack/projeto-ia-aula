"""Nexus Guardian — constantly-running agent that monitors system health and suggests improvements.

Inspired by Kubernetes health probes, Datadog watchdog, and self-healing systems.
Runs every 30 seconds in a background task.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.observability.advanced_logging import get_structured_logger
from backend.tools.project_analyzer import analyze_project

logger = logging.getLogger(__name__)


@dataclass
class Suggestion:
    id: str
    category: str  # "performance", "security", "quality", "maintenance"
    priority: str  # "critical", "high", "medium", "low"
    title: str
    description: str
    action: str  # what to do
    auto_fixable: bool
    created_at: float = field(default_factory=time.time)
    applied: bool = False
    applied_at: float | None = None


@dataclass
class SystemHealth:
    timestamp: float
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    active_sessions: int = 0
    recent_errors: int = 0
    avg_latency_ms: float = 0.0
    status: str = "healthy"  # healthy, warning, critical


class NexusGuardianAgent:
    name = "GUARDIAN"
    """Constantly-running guardian that monitors and improves the system.

    Usage:
        guardian = NexusGuardianAgent()
        await guardian.start()

        # Query status
        status = guardian.get_status()
        suggestions = guardian.get_suggestions()
    """

    CHECK_INTERVAL = 30.0  # seconds
    HISTORY_SIZE = 1000

    def __init__(self) -> None:
        self._suggestions: deque[Suggestion] = deque(maxlen=100)
        self._health_history: deque[SystemHealth] = deque(maxlen=self.HISTORY_SIZE)
        self._error_patterns: dict[str, int] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        self._slog = get_structured_logger()

    async def start(self) -> asyncio.Task[None]:
        """Start the guardian monitoring loop and return its background task.

        Starting through this method is important: :meth:`monitor_loop`
        intentionally exits while ``_running`` is false, so scheduling that
        method directly creates a task that immediately stops.
        """
        if self._running:
            if self._task is None:
                raise RuntimeError("Guardian is marked running without a monitor task")
            return self._task
        self._running = True
        self._task = asyncio.create_task(self.monitor_loop())
        logger.info("Nexus Guardian started")
        self._slog.info("Nexus Guardian started", agent="GUARDIAN", source="guardian")
        return self._task

    async def stop(self) -> None:
        """Stop the guardian."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        logger.info("Nexus Guardian stopped")

    async def monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check_system_health()
                await self._analyze_recent_logs()
                await self._check_project_health()
                await self._generate_suggestions()
            except Exception as exc:
                logger.error("Guardian monitor loop error: %s", exc)
                self._slog.error(f"Guardian error: {exc}", agent="GUARDIAN", source="guardian")

            await asyncio.sleep(self.CHECK_INTERVAL)

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    async def _check_system_health(self) -> None:
        """Check system resources."""
        try:
            import psutil

            cpu, mem, disk = await asyncio.to_thread(
                lambda: (
                    psutil.cpu_percent(interval=0.5),
                    psutil.virtual_memory().percent,
                    psutil.disk_usage("/").percent,
                )
            )
        except ImportError:
            cpu, mem, disk = 0.0, 0.0, 0.0

        # Determine status
        status = "healthy"
        if cpu > 90 or mem > 90 or disk > 95:
            status = "critical"
        elif cpu > 70 or mem > 80 or disk > 85:
            status = "warning"

        health = SystemHealth(
            timestamp=time.time(),
            cpu_percent=cpu,
            memory_percent=mem,
            disk_percent=disk,
            status=status,
        )
        self._health_history.append(health)

        if status != "healthy":
            self._slog.warning(
                f"System {status}: CPU={cpu}%, MEM={mem}%, DISK={disk}%",
                agent="GUARDIAN",
                source="guardian",
                extra={"cpu": cpu, "memory": mem, "disk": disk, "status": status},
            )

    async def _analyze_recent_logs(self) -> None:
        """Analyze recent logs for error patterns."""
        recent = self._slog.get_recent(count=100)
        errors = [r for r in recent if r.get("level") in ("ERROR", "CRITICAL")]

        # Count errors by source
        for entry in errors:
            source = entry.get("source", "unknown")
            self._error_patterns[source] = self._error_patterns.get(source, 0) + 1

        # If high error rate from a source, create suggestion
        for source, count in self._error_patterns.items():
            if count >= 5:
                self._add_suggestion(
                    category="maintenance",
                    priority="high",
                    title=f"High error rate from {source}",
                    description=f"Detected {count} recent errors from {source}. Review logs for root cause.",
                    action=f"Check logs for source='{source}' and investigate.",
                    auto_fixable=False,
                )
                # Reset counter after suggestion
                self._error_patterns[source] = 0

    async def _check_project_health(self) -> None:
        """Check active projects for issues."""
        try:
            from backend.persistence.db import list_projects

            # list_projects is synchronous and obtains a pooled SQLite
            # connection. Never block the event loop while the pool is busy.
            projects = await asyncio.to_thread(list_projects)
            for project in projects:
                project_path = project.get("path", "")
                if not project_path or not os.path.exists(project_path):
                    continue

                # Run project analysis
                try:
                    analysis = await analyze_project(project_path)
                    if isinstance(analysis, dict) and "error" not in analysis:
                        health_score = analysis.get("health_score", 100)

                        if health_score < 50:
                            self._add_suggestion(
                                category="quality",
                                priority="high",
                                title=f"Project '{project['name']}' has poor health ({health_score}/100)",
                                description="\n".join(analysis.get("recommendations", []))[:500],
                                action="Review recommendations and apply fixes.",
                                auto_fixable=False,
                            )
                        elif health_score < 70:
                            self._add_suggestion(
                                category="quality",
                                priority="medium",
                                title=f"Project '{project['name']}' needs improvement ({health_score}/100)",
                                description="\n".join(analysis.get("recommendations", []))[:300],
                                action="Consider adding tests and documentation.",
                                auto_fixable=False,
                            )

                        # Check for security issues
                        security = analysis.get("security_issues", [])
                        if security:
                            self._add_suggestion(
                                category="security",
                                priority="critical",
                                title=f"Security issues found in '{project['name']}'",
                                description=f"Found {len(security)} potential security issues.",
                                action="Review security scan results and fix issues.",
                                auto_fixable=False,
                            )
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("Project health check failed: %s", exc)

    async def _generate_suggestions(self) -> None:
        """Generate system-wide suggestions."""
        if not self._health_history:
            return

        recent = list(self._health_history)[-10:]
        avg_cpu = sum(h.cpu_percent for h in recent) / len(recent)
        avg_mem = sum(h.memory_percent for h in recent) / len(recent)

        if avg_cpu > 80:
            self._add_suggestion(
                category="performance",
                priority="high",
                title="High CPU usage detected",
                description=f"Average CPU usage over last {len(recent)} checks: {avg_cpu:.1f}%",
                action="Consider reducing concurrent agent executions or upgrading hardware.",
                auto_fixable=False,
            )

        if avg_mem > 85:
            self._add_suggestion(
                category="performance",
                priority="critical",
                title="High memory usage detected",
                description=f"Average memory usage: {avg_mem:.1f}%",
                action="Restart services or increase available memory.",
                auto_fixable=False,
            )

    # ------------------------------------------------------------------
    # Suggestion management
    # ------------------------------------------------------------------

    def _add_suggestion(
        self,
        category: str,
        priority: str,
        title: str,
        description: str,
        action: str,
        auto_fixable: bool,
    ) -> None:
        """Add a suggestion if not already present."""
        # Deduplicate by title
        for existing in self._suggestions:
            if existing.title == title and not existing.applied:
                return

        suggestion = Suggestion(
            id=f"sugg_{int(time.time() * 1000)}_{len(self._suggestions)}",
            category=category,
            priority=priority,
            title=title,
            description=description,
            action=action,
            auto_fixable=auto_fixable,
        )
        self._suggestions.append(suggestion)
        self._slog.info(
            f"New suggestion: [{priority}] {title}",
            agent="GUARDIAN",
            source="guardian",
            extra={"suggestion_id": suggestion.id, "category": category, "priority": priority},
        )

    def get_status(self) -> dict[str, Any]:
        """Return current guardian and system status."""
        latest = self._health_history[-1] if self._health_history else None
        return {
            "running": self._running,
            "check_interval": self.CHECK_INTERVAL,
            "system_health": {
                "status": latest.status if latest else "unknown",
                "cpu_percent": latest.cpu_percent if latest else 0,
                "memory_percent": latest.memory_percent if latest else 0,
                "disk_percent": latest.disk_percent if latest else 0,
            }
            if latest
            else None,
            "suggestion_count": len(self._suggestions),
            "pending_suggestions": len([s for s in self._suggestions if not s.applied]),
            "health_history_count": len(self._health_history),
        }

    def get_suggestions(
        self,
        limit: int = 10,
        category: str | None = None,
        priority: str | None = None,
        pending_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Return suggestions with optional filtering."""
        results = []
        for s in reversed(self._suggestions):
            if pending_only and s.applied:
                continue
            if category and s.category != category:
                continue
            if priority and s.priority != priority:
                continue
            results.append(
                {
                    "id": s.id,
                    "category": s.category,
                    "priority": s.priority,
                    "title": s.title,
                    "description": s.description,
                    "action": s.action,
                    "auto_fixable": s.auto_fixable,
                    "created_at": datetime.fromtimestamp(s.created_at, UTC).isoformat(),
                    "applied": s.applied,
                }
            )
            if len(results) >= limit:
                break
        return results

    def apply_suggestion(self, suggestion_id: str) -> dict[str, Any]:
        """Mark a suggestion as applied."""
        for s in self._suggestions:
            if s.id == suggestion_id:
                s.applied = True
                s.applied_at = time.time()
                self._slog.info(
                    f"Suggestion applied: {s.title}",
                    agent="GUARDIAN",
                    source="guardian",
                    extra={"suggestion_id": suggestion_id},
                )
                return {"success": True, "suggestion": s.id}
        return {"error": "Suggestion not found"}

    def dismiss_suggestion(self, suggestion_id: str) -> dict[str, Any]:
        """Dismiss a suggestion without applying."""
        for s in self._suggestions:
            if s.id == suggestion_id:
                s.applied = True  # Mark as handled
                s.applied_at = time.time()
                return {"success": True, "dismissed": True}
        return {"error": "Suggestion not found"}

    def get_health_trend(self, points: int = 10) -> list[dict[str, Any]]:
        """Return system health trend over time."""
        recent = list(self._health_history)[-points:]
        return [
            {
                "timestamp": h.timestamp,
                "cpu": h.cpu_percent,
                "memory": h.memory_percent,
                "disk": h.disk_percent,
                "status": h.status,
            }
            for h in recent
        ]
