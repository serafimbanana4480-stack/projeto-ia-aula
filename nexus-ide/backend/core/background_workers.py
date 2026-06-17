"""Background Agent Workers — the always-on layer for NEXUS IDE agents.

Provides persistent background workers that monitor the system continuously:

- ``CODE_WATCHER``:     Watches filesystem for code changes and triggers agents.
- ``DEPENDENCY_WATCHER``: Scans dependency files for known vulnerabilities.
- ``PERFORMANCE_WATCHER``: Runs benchmarks periodically and detects regressions.
- ``MEMORY_WATCHER``:   Monitors agent state store for memory bloat and archives old data.
- ``ESCALATION_WATCHER``: Monitors pending human-in-the-loop escalations and sends reminders.

All workers publish heartbeats and events via the Agent Bus.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.core.agent_bus import BusMessage, get_agent_bus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEARTBEAT_INTERVAL_SECONDS: float = 30.0
DEFAULT_WORKER_INTERVAL_SECONDS: float = 60.0

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class WorkerStatus(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"


class WorkerInfo(BaseModel):
    """Snapshot of a background worker's state."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: str
    interval_seconds: float
    last_run: str = ""
    next_run: str = ""
    heartbeat_count: int = 0
    error_count: int = 0


# ---------------------------------------------------------------------------
# Abstract base worker
# ---------------------------------------------------------------------------


class BackgroundWorker(ABC):
    """Abstract base for all background workers.

    Subclasses implement :meth:`_tick` to perform their monitoring work.
    The base class handles the async loop, heartbeats, pause/resume, and
    graceful shutdown.
    """

    def __init__(
        self,
        name: str,
        interval_seconds: float = DEFAULT_WORKER_INTERVAL_SECONDS,
    ) -> None:
        self.name = name
        self.interval_seconds = interval_seconds
        self._status = WorkerStatus.STOPPED
        self._task: asyncio.Task[Any] | None = None
        self._heartbeat_task: asyncio.Task[Any] | None = None
        self._pause_event: asyncio.Event | None = None
        self._stop_event: asyncio.Event | None = None
        self._last_run: datetime | None = None
        self._heartbeat_count = 0
        self._error_count = 0
        self._lock = asyncio.Lock()
        self._subscription = None

    # -- public lifecycle ---------------------------------------------------

    async def start(self) -> None:
        """Start the worker loop and heartbeat."""
        async with self._lock:
            if self._status in (WorkerStatus.RUNNING, WorkerStatus.STARTING):
                logger.warning("Worker %s already running", self.name)
                return
            self._status = WorkerStatus.STARTING
            # Recreate events in the current loop to avoid cross-loop issues
            self._stop_event = asyncio.Event()
            self._pause_event = asyncio.Event()
            self._stop_event.clear()
            self._pause_event.clear()
            self._task = asyncio.create_task(self._run_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._status = WorkerStatus.RUNNING
            logger.info("Worker %s started (interval=%.0fs)", self.name, self.interval_seconds)

    async def stop(self) -> None:
        """Signal the worker to stop and wait for task completion."""
        async with self._lock:
            self._status = WorkerStatus.STOPPED
            if self._stop_event is not None:
                self._stop_event.set()
            if self._pause_event is not None:
                if self._pause_event is not None:
                    self._pause_event.set()  # unblock any paused wait

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.debug("Worker %s task cancelled", self.name)
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                logger.debug("Worker %s heartbeat cancelled", self.name)

        logger.info("Worker %s stopped", self.name)

    async def pause(self) -> None:
        """Pause the worker loop (heartbeats continue)."""
        async with self._lock:
            if self._status == WorkerStatus.RUNNING:
                self._status = WorkerStatus.PAUSED
                self._pause_event.set()
                logger.info("Worker %s paused", self.name)

    async def resume(self) -> None:
        """Resume a paused worker."""
        async with self._lock:
            if self._status == WorkerStatus.PAUSED:
                self._status = WorkerStatus.RUNNING
                if self._pause_event is not None:
                    self._pause_event.clear()
                logger.info("Worker %s resumed", self.name)

    def info(self) -> WorkerInfo:
        """Return a snapshot of this worker's state."""
        now = datetime.now(UTC)
        next_run = ""
        if self._last_run and self._status == WorkerStatus.RUNNING:
            next_dt = self._last_run + timedelta(seconds=self.interval_seconds)
            next_run = next_dt.isoformat()
        return WorkerInfo(
            name=self.name,
            status=self._status.value,
            interval_seconds=self.interval_seconds,
            last_run=self._last_run.isoformat() if self._last_run else "",
            next_run=next_run,
            heartbeat_count=self._heartbeat_count,
            error_count=self._error_count,
        )

    # -- internal loops -----------------------------------------------------

    async def _run_loop(self) -> None:
        """Main worker loop — calls `_tick` at configured intervals."""
        while self._stop_event is not None and not self._stop_event.is_set():
            try:
                if self._status == WorkerStatus.PAUSED:
                    await self._wait_for_resume()
                    if self._stop_event is not None and self._stop_event.is_set():
                        break

                await self._tick()
                self._last_run = datetime.now(UTC)
            except asyncio.CancelledError:
                break
            except Exception:
                self._error_count += 1
                logger.exception("Worker %s tick failed", self.name)

            # Sleep in short chunks so we respond quickly to stop/resume
            deadline = time.monotonic() + self.interval_seconds
            while time.monotonic() < deadline and (
                self._stop_event is None or not self._stop_event.is_set()
            ):
                if self._status == WorkerStatus.PAUSED:
                    break
                await asyncio.sleep(min(1.0, deadline - time.monotonic()))

    async def _heartbeat_loop(self) -> None:
        """Publish heartbeat to the Agent Bus every 30 seconds."""
        while self._stop_event is not None and not self._stop_event.is_set():
            try:
                await self._publish(
                    "agent.status",
                    {
                        "worker": self.name,
                        "status": self._status.value,
                        "heartbeat": True,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
                self._heartbeat_count += 1
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Worker %s heartbeat failed", self.name)
            if self._stop_event is not None:
                await asyncio.wait_for(self._stop_event.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS)

    async def _wait_for_resume(self) -> None:
        """Block until the worker is resumed or stopped."""
        while self._status == WorkerStatus.PAUSED and (
            self._stop_event is None or not self._stop_event.is_set()
        ):
            await asyncio.sleep(0.5)

    # -- bus helper ---------------------------------------------------------

    async def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Publish a message to the Agent Bus."""
        bus = get_agent_bus()
        await bus.publish(
            topic,
            BusMessage(
                message_id=uuid.uuid4().hex[:16],
                source_agent=self.name,
                payload=payload,
            ),
        )

    # -- abstract hook ------------------------------------------------------

    @abstractmethod
    async def _tick(self) -> None:
        """Perform one unit of work. Called periodically by `_run_loop`."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# CODE_WATCHER
# ---------------------------------------------------------------------------


class CodeWatcher(BackgroundWorker):
    """Watches filesystem for code changes and triggers relevant agents.

    Uses ``watchdog`` if available, otherwise falls back to polling.
    """

    def __init__(
        self,
        watch_path: str | Path = ".",
        interval_seconds: float = 10.0,
    ) -> None:
        super().__init__("CODE_WATCHER", interval_seconds=interval_seconds)
        self.watch_path = Path(watch_path).resolve()
        self._snapshots: dict[Path, float] = {}
        self._has_watchdog = self._detect_watchdog()
        self._observer: Any = None
        self._event_queue: asyncio.Queue[list[Path]] = asyncio.Queue()

    def _detect_watchdog(self) -> bool:
        try:
            import watchdog.observers  # noqa: F401

            return True
        except ImportError:
            return False

    async def _tick(self) -> None:
        if self._has_watchdog:
            await self._tick_watchdog()
        else:
            await self._tick_polling()

    async def _tick_watchdog(self) -> None:
        """Process queued filesystem events from the watchdog observer."""
        # Lazy-start observer on first tick
        if self._observer is None:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class _Handler(FileSystemEventHandler):
                def __init__(self, queue: asyncio.Queue[list[Path]]) -> None:
                    self._queue = queue

                def on_any_event(self, event: Any) -> None:
                    if event.is_directory:
                        return
                    try:
                        self._queue.put_nowait([Path(event.src_path)])
                    except asyncio.QueueFull:
                        logger.warning("File watcher queue full, dropping event")

            observer = Observer()
            handler = _Handler(self._event_queue)
            observer.schedule(handler, str(self.watch_path), recursive=True)
            observer.start()
            self._observer = observer
            logger.info("CODE_WATCHER using watchdog on %s", self.watch_path)

        # Drain queue without blocking
        changed_files: set[Path] = set()
        while not self._event_queue.empty():
            try:
                batch = self._event_queue.get_nowait()
                changed_files.update(batch)
            except asyncio.QueueEmpty:
                break

        if changed_files:
            await self._process_changes(list(changed_files))

    async def _tick_polling(self) -> None:
        """Poll filesystem mtimes to detect changes."""
        changed_files: list[Path] = []
        for root, _dirs, files in os.walk(self.watch_path):
            for fname in files:
                fpath = Path(root) / fname
                try:
                    mtime = fpath.stat().st_mtime
                except OSError:
                    continue
                old_mtime = self._snapshots.get(fpath)
                if old_mtime is not None and mtime != old_mtime:
                    changed_files.append(fpath)
                self._snapshots[fpath] = mtime

        if changed_files:
            await self._process_changes(changed_files)

    async def _process_changes(self, files: list[Path]) -> None:
        """Classify changed files and trigger appropriate downstream actions."""
        triggers: set[str] = set()
        for fpath in files:
            name = fpath.name.lower()
            if name.endswith(".py"):
                triggers.add("python_change")
            elif name.endswith(".test.py"):
                triggers.add("test_change")
            elif name in (
                "requirements.txt",
                "package.json",
                "cargo.toml",
                "poetry.lock",
                "pdm.lock",
            ):
                triggers.add("dependency_change")

        if "python_change" in triggers:
            await self._publish(
                "code.change_detected",
                {
                    "change_type": "python_change",
                    "files": [str(f) for f in files],
                    "triggered_agents": ["TEST_RUNNER_UNIT", "BUG_HUNTER_STATIC"],
                },
            )
            logger.info("CODE_WATCHER triggered TEST_RUNNER_UNIT + BUG_HUNTER_STATIC")

        if "test_change" in triggers:
            await self._publish(
                "code.change_detected",
                {
                    "change_type": "test_change",
                    "files": [str(f) for f in files],
                    "triggered_agents": ["TEST_RUNNER_UNIT"],
                },
            )
            logger.info("CODE_WATCHER triggered TEST_RUNNER_UNIT")

        if "dependency_change" in triggers:
            await self._publish(
                "code.change_detected",
                {
                    "change_type": "dependency_change",
                    "files": [str(f) for f in files],
                    "triggered_agents": ["DEPENDENCY_WATCHER"],
                },
            )
            logger.info("CODE_WATCHER triggered DEPENDENCY_WATCHER")

    async def stop(self) -> None:
        await super().stop()
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)


# ---------------------------------------------------------------------------
# DEPENDENCY_WATCHER
# ---------------------------------------------------------------------------


class DependencyWatcher(BackgroundWorker):
    """Scans dependency files for known vulnerabilities.

    Uses ``safety`` for Python (requirements.txt) and ``npm audit`` for JS.
    Runs weekly or on-demand (triggered by dependency file changes).
    """

    def __init__(
        self,
        watch_path: str | Path = ".",
        interval_seconds: float = 604_800,  # 1 week
    ) -> None:
        super().__init__("DEPENDENCY_WATCHER", interval_seconds=interval_seconds)
        self.watch_path = Path(watch_path).resolve()
        self._safety_available = shutil.which("safety") is not None
        self._npm_available = shutil.which("npm") is not None

    async def _tick(self) -> None:
        findings: list[dict[str, Any]] = []

        # Python dependencies
        req_file = self.watch_path / "requirements.txt"
        if req_file.exists() and self._safety_available:
            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["safety", "check", "--file", str(req_file), "--json"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode != 0 and result.stdout:
                    data = json.loads(result.stdout)
                    vulns = data.get("vulnerabilities", [])
                    for v in vulns:
                        findings.append(
                            {
                                "ecosystem": "python",
                                "file": "requirements.txt",
                                "package": v.get("package_name", "unknown"),
                                "vulnerability": v.get("vulnerability_id", "unknown"),
                                "severity": v.get("severity", "unknown"),
                            }
                        )
            except Exception as exc:
                logger.warning("DEPENDENCY_WATCHER safety check failed: %s", exc)

        # JS dependencies
        pkg_file = self.watch_path / "package.json"
        if pkg_file.exists() and self._npm_available:
            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["npm", "audit", "--json"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=str(self.watch_path),
                )
                data = json.loads(result.stdout)
                advisories = data.get("advisories", {})
                for adv in advisories.values():
                    findings.append(
                        {
                            "ecosystem": "npm",
                            "file": "package.json",
                            "package": adv.get("module_name", "unknown"),
                            "vulnerability": adv.get("id", "unknown"),
                            "severity": adv.get("severity", "unknown"),
                        }
                    )
            except Exception as exc:
                logger.warning("DEPENDENCY_WATCHER npm audit failed: %s", exc)

        if findings:
            await self._publish(
                "dependency.vulnerability_found",
                {
                    "findings": findings,
                    "count": len(findings),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            logger.info("DEPENDENCY_WATCHER found %d vulnerabilities", len(findings))
        else:
            logger.debug("DEPENDENCY_WATCHER scan completed — no vulnerabilities")


# ---------------------------------------------------------------------------
# PERFORMANCE_WATCHER
# ---------------------------------------------------------------------------


class PerformanceWatcher(BackgroundWorker):
    """Runs benchmarks periodically, compares to baseline, detects regressions.

    Uses ``pytest-benchmark`` if available, otherwise falls back to custom
    timing scripts. Baselines are stored in the Agent State Store.
    """

    def __init__(
        self,
        watch_path: str | Path = ".",
        interval_seconds: float = 3_600,  # 1 hour
    ) -> None:
        super().__init__("PERFORMANCE_WATCHER", interval_seconds=interval_seconds)
        self.watch_path = Path(watch_path).resolve()
        self._pytest_benchmark_available = self._detect_pytest_benchmark()

    def _detect_pytest_benchmark(self) -> bool:
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "--benchmark-only", "-q", "--co"],
                capture_output=True,
                cwd=str(self.watch_path),
                timeout=30,
            )
            return result.returncode in (0, 5)  # 5 = no tests collected
        except Exception:
            return False

    async def _tick(self) -> None:
        results: dict[str, Any] = {}

        if self._pytest_benchmark_available:
            results = await self._run_pytest_benchmark()
        else:
            results = await self._run_custom_benchmark()

        # Compare to baseline
        baseline = self._load_baseline()
        comparison = self._compare_to_baseline(results, baseline)

        # Persist new baseline if improved or first run
        if not baseline or comparison.get("improved"):
            self._save_baseline(results)

        if comparison.get("regressed"):
            await self._publish(
                "performance.regression",
                {
                    "metrics": results,
                    "comparison": comparison,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            logger.warning(
                "PERFORMANCE_WATCHER regression detected: %s",
                comparison.get("details", []),
            )
        elif comparison.get("improved"):
            await self._publish(
                "performance.improvement",
                {
                    "metrics": results,
                    "comparison": comparison,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            logger.info("PERFORMANCE_WATCHER improvement detected")
        else:
            logger.debug("PERFORMANCE_WATCHER no significant change")

    async def _run_pytest_benchmark(self) -> dict[str, Any]:
        """Run pytest-benchmark and parse JSON output."""
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [
                    "python",
                    "-m",
                    "pytest",
                    "--benchmark-only",
                    "--benchmark-json=benchmark.json",
                    "-q",
                ],
                capture_output=True,
                text=True,
                cwd=str(self.watch_path),
                timeout=300,
            )
            bench_file = self.watch_path / "benchmark.json"
            if bench_file.exists():
                data = json.loads(bench_file.read_text())
                bench_file.unlink(missing_ok=True)
                return {"pytest_benchmark": data}
        except Exception as exc:
            logger.warning("pytest-benchmark failed: %s", exc)
        return {}

    async def _run_custom_benchmark(self) -> dict[str, Any]:
        """Fallback: time a simple Python script execution."""
        script = self.watch_path / "benchmark.py"
        if not script.exists():
            return {"custom": {"note": "No benchmark.py found"}}
        try:
            started = time.monotonic()
            result = await asyncio.to_thread(
                subprocess.run,
                ["python", str(script)],
                capture_output=True,
                text=True,
                cwd=str(self.watch_path),
                timeout=300,
            )
            elapsed = time.monotonic() - started
            return {
                "custom": {
                    "script": str(script),
                    "elapsed_ms": round(elapsed * 1000, 2),
                    "returncode": result.returncode,
                }
            }
        except Exception as exc:
            logger.warning("Custom benchmark failed: %s", exc)
            return {"custom": {"error": str(exc)}}

    def _load_baseline(self) -> dict[str, Any] | None:
        """Load baseline from agent state store."""
        from backend.core.agent_state import AgentStateStore

        store = AgentStateStore()
        mem = store.load_state(
            agent_name="PERFORMANCE_WATCHER",
            session_id="global",
            project_path=str(self.watch_path),
            tier="medium_term",
            key="baseline",
        )
        if mem and mem.value:
            return mem.value if isinstance(mem.value, dict) else None
        return None

    def _save_baseline(self, results: dict[str, Any]) -> None:
        """Save baseline to agent state store."""
        from backend.core.agent_state import AgentStateStore

        store = AgentStateStore()
        store.save_state(
            agent_name="PERFORMANCE_WATCHER",
            session_id="global",
            project_path=str(self.watch_path),
            tier="medium_term",
            key="baseline",
            value=results,
            importance=0.7,
        )

    def _compare_to_baseline(
        self, results: dict[str, Any], baseline: dict[str, Any] | None
    ) -> dict[str, Any]:
        if not baseline:
            return {"new_baseline": True, "regressed": False, "improved": False, "details": []}

        details: list[dict[str, Any]] = []
        regressed = False
        improved = False

        # Simple comparison for pytest-benchmark mean times
        old_benches = baseline.get("pytest_benchmark", {}).get("benchmarks", [])
        new_benches = results.get("pytest_benchmark", {}).get("benchmarks", [])
        for new in new_benches:
            old = next(
                (o for o in old_benches if o.get("name") == new.get("name")),
                None,
            )
            if old and old.get("stats", {}).get("mean") and new.get("stats", {}).get("mean"):
                old_mean = old["stats"]["mean"]
                new_mean = new["stats"]["mean"]
                delta_pct = ((new_mean - old_mean) / old_mean) * 100 if old_mean else 0
                threshold = 10.0  # 10% change threshold
                if delta_pct > threshold:
                    regressed = True
                    details.append(
                        {
                            "test": new["name"],
                            "change_pct": round(delta_pct, 2),
                            "direction": "regression",
                        }
                    )
                elif delta_pct < -threshold:
                    improved = True
                    details.append(
                        {
                            "test": new["name"],
                            "change_pct": round(delta_pct, 2),
                            "direction": "improvement",
                        }
                    )

        # Custom benchmark comparison
        old_custom = baseline.get("custom", {}).get("elapsed_ms")
        new_custom = results.get("custom", {}).get("elapsed_ms")
        if old_custom and new_custom:
            delta_pct = ((new_custom - old_custom) / old_custom) * 100
            if delta_pct > 10:
                regressed = True
                details.append(
                    {
                        "test": "custom_benchmark",
                        "change_pct": round(delta_pct, 2),
                        "direction": "regression",
                    }
                )
            elif delta_pct < -10:
                improved = True
                details.append(
                    {
                        "test": "custom_benchmark",
                        "change_pct": round(delta_pct, 2),
                        "direction": "improvement",
                    }
                )

        return {
            "regressed": regressed,
            "improved": improved,
            "details": details,
        }


# ---------------------------------------------------------------------------
# SELF_IMPROVEMENT_WATCHER
# ---------------------------------------------------------------------------


class SelfImprovementWatcher(BackgroundWorker):
    """Periodically runs self-improvement analysis and publishes proposals."""

    def __init__(
        self,
        interval_seconds: float = 86_400,  # 24 hours default
    ) -> None:
        super().__init__("SELF_IMPROVEMENT_WATCHER", interval_seconds=interval_seconds)
        self._analyzer = None

    async def _tick(self) -> None:
        try:
            from backend.core.self_improvement import SelfImprovementAnalyzer

            if self._analyzer is None:
                self._analyzer = SelfImprovementAnalyzer()

            report = await self._analyzer.run_analysis()

            if report.proposals:
                high_conf = [p for p in report.proposals if p.confidence >= 0.6]
                await self._publish(
                    "self_improvement.proposals_ready",
                    {
                        "proposal_count": len(report.proposals),
                        "high_confidence_count": len(high_conf),
                        "summary": report.summary,
                        "proposals": [p.model_dump(mode="json") for p in report.proposals],
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
                logger.info(
                    "SELF_IMPROVEMENT_WATCHER generated %d proposals (%d high confidence)",
                    len(report.proposals),
                    len(high_conf),
                )

                # Auto-apply approved high-confidence proposals
                apply_results = await self._analyzer.auto_apply_approved(
                    report,
                    min_confidence=0.7,
                    require_meta_approval=True,
                )
                if apply_results["applied"]:
                    await self._publish(
                        "self_improvement.applied",
                        {
                            "applied_count": len(apply_results["applied"]),
                            "applied": apply_results["applied"],
                            "timestamp": datetime.now(UTC).isoformat(),
                        },
                    )
                    logger.info(
                        "SELF_IMPROVEMENT_WATCHER auto-applied %d proposals",
                        len(apply_results["applied"]),
                    )

            else:
                logger.debug("SELF_IMPROVEMENT_WATCHER no proposals generated")

        except Exception as exc:
            logger.exception("SELF_IMPROVEMENT_WATCHER analysis failed: %s", exc)
            self._error_count += 1


# ---------------------------------------------------------------------------
# MEMORY_WATCHER
# ---------------------------------------------------------------------------


class MemoryWatcher(BackgroundWorker):
    """Monitors Agent State Store for memory bloat and performs maintenance.

    Archives old memories, decays importance scores, and removes stale entries.
    """

    def __init__(
        self,
        interval_seconds: float = 3_600,  # 1 hour
    ) -> None:
        super().__init__("MEMORY_WATCHER", interval_seconds=interval_seconds)

    async def _tick(self) -> None:
        from backend.core.agent_state import AgentStateStore

        store = AgentStateStore()
        now = datetime.now(UTC)

        # Decay all memories
        deleted = store.decay_memories(decay_factor=0.95, min_importance=0.05)

        # Count remaining memories for metrics
        total_memories = 0
        try:
            from backend.persistence.db import get_db

            with get_db() as conn:
                row = conn.execute("SELECT COUNT(*) AS cnt FROM agent_states").fetchone()
                total_memories = row["cnt"] if row else 0
        except Exception:
            logger.warning("Failed to count agent states for memory maintenance")

        await self._publish(
            "memory.maintenance_completed",
            {
                "deleted_memories": deleted,
                "total_memories": total_memories,
                "timestamp": now.isoformat(),
            },
        )
        logger.info(
            "MEMORY_WATCHER maintenance completed: deleted=%d, total=%d",
            deleted,
            total_memories,
        )


# ---------------------------------------------------------------------------
# ESCALATION_WATCHER
# ---------------------------------------------------------------------------


class EscalationWatcher(BackgroundWorker):
    """Monitors pending human-in-the-loop escalations and sends reminders.

    Subscribes to ``human_in_the_loop.pending`` for immediate notifications
    and also processes any queued pending escalations on each tick.
    """

    def __init__(
        self,
        watch_path: str | Path = ".",
        interval_seconds: float = 300.0,
    ) -> None:
        super().__init__("ESCALATION_WATCHER", interval_seconds=interval_seconds)
        self._subscribed = False
        self._pending: list[dict[str, Any]] = []

    async def start(self) -> None:
        await super().start()
        if not self._subscribed:
            bus = get_agent_bus()
            try:
                sub = await bus.subscribe("human_in_the_loop.pending", self._on_pending)
            except Exception as exc:
                logger.error("ESCALATION_WATCHER failed to subscribe to human_in_the_loop.pending: %s", exc)
                self._error_count += 1
                return
            self._subscription = sub
            self._subscribed = True
            logger.info("ESCALATION_WATCHER subscribed to human_in_the_loop.pending")

    async def stop(self) -> None:
        await super().stop()
        if self._subscription is not None:
            try:
                bus = get_agent_bus()
                await bus.unsubscribe(self._subscription.subscription_id)
            except Exception as exc:
                logger.debug("ESCALATION_WATCHER unsubscribe failed: %s", exc)

    async def _on_pending(self, message: BusMessage) -> None:
        payload = message.payload or {}
        escalation_id = payload.get("escalation_id")
        if escalation_id is None:
            logger.debug("ESCALATION_WATCHER received pending message without escalation_id")
            return
        self._pending.append(payload)

    async def _tick(self) -> None:
        pending: list[dict[str, Any]] = []

        if self._pending:
            pending.extend(self._pending)
            self._pending.clear()

        try:
            from backend.core.human_in_the_loop import HumanInTheLoopManager

            manager = HumanInTheLoopManager()
            pending.extend(manager.list_pending())
        except Exception as exc:
            logger.warning("ESCALATION_WATCHER failed to load pending escalations: %s", exc)

        reminder_count = 0
        for item in pending:
            escalation_id = item.get("escalation_id") or item.get("request_id")
            if escalation_id is None:
                continue
            reason = self._build_reason(item)
            try:
                from backend.core.human_in_the_loop import HumanInTheLoopManager

                manager = HumanInTheLoopManager()
                policy = manager.load_policy()
            except Exception:
                policy = None

            if policy is None or not getattr(policy, "enabled", False):
                continue

            await self._publish(
                "human_in_the_loop.reminder",
                {
                    "escalation_id": escalation_id,
                    "reason": reason,
                },
            )
            reminder_count += 1

        logger.info(
            "ESCALATION_WATCHER processed %d pending escalations, sent %d reminders",
            len(pending),
            reminder_count,
        )

    def _build_reason(self, item: dict[str, Any]) -> str:
        reason = item.get("reason")
        if reason:
            return str(reason)
        proposal = item.get("proposal") or {}
        category = proposal.get("category", "unknown")
        confidence = proposal.get("confidence", "unknown")
        return f"Pending escalation for category={category}, confidence={confidence}"


# ---------------------------------------------------------------------------
# BackgroundWorkerManager
# ---------------------------------------------------------------------------


class BackgroundWorkerManager:
    """Manages all background workers as a group.

    Usage::

        manager = BackgroundWorkerManager(watch_path=".")
        await manager.start_all()
        await manager.stop_all()
    """

    def __init__(self, watch_path: str | Path = ".") -> None:
        self.watch_path = Path(watch_path).resolve()
        self._workers: dict[str, BackgroundWorker] = {
            "CODE_WATCHER": CodeWatcher(self.watch_path, interval_seconds=10.0),
            "DEPENDENCY_WATCHER": DependencyWatcher(self.watch_path, interval_seconds=604_800),
            "PERFORMANCE_WATCHER": PerformanceWatcher(self.watch_path, interval_seconds=3_600),
            "MEMORY_WATCHER": MemoryWatcher(interval_seconds=3_600),
            "SELF_IMPROVEMENT_WATCHER": SelfImprovementWatcher(interval_seconds=86_400),
            "ESCALATION_WATCHER": EscalationWatcher(self.watch_path, interval_seconds=300),
        }

    async def start_all(self) -> None:
        """Start every registered worker."""
        for worker in self._workers.values():
            await worker.start()

    async def stop_all(self) -> None:
        """Stop every registered worker."""
        for worker in self._workers.values():
            await worker.stop()

    def get_worker(self, name: str) -> BackgroundWorker | None:
        """Retrieve a worker by name."""
        return self._workers.get(name)

    def list_workers(self) -> list[WorkerInfo]:
        """Return status info for every worker."""
        return [w.info() for w in self._workers.values()]

    async def start(self, name: str) -> bool:
        """Start a single worker by name."""
        worker = self._workers.get(name)
        if worker:
            await worker.start()
            return True
        return False

    async def stop(self, name: str) -> bool:
        """Stop a single worker by name."""
        worker = self._workers.get(name)
        if worker:
            await worker.stop()
            return True
        return False

    async def pause(self, name: str) -> bool:
        """Pause a single worker by name."""
        worker = self._workers.get(name)
        if worker:
            await worker.pause()
            return True
        return False

    async def resume(self, name: str) -> bool:
        """Resume a single worker by name."""
        worker = self._workers.get(name)
        if worker:
            await worker.resume()
            return True
        return False
