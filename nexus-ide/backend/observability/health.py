"""Deep health checks for NEXUS IDE background services.

Provides :class:`HealthChecker` which probes every critical subsystem
with short timeouts so the deep endpoint stays under 2 s total.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Short timeout for every individual check (seconds). Redis-backed file locks
# may spend up to one second discovering that Redis is unavailable before the
# local file-lock fallback can run, so 0.5s produced a false degraded signal.
_CHECK_TIMEOUT = 1.25


class HealthChecker:
    """Probe all long-lived services attached to ``app.state``.

    Usage::

        checker = HealthChecker(app.state)
        report = await checker.check_all()
    """

    def __init__(self, app_state: Any) -> None:
        self._state = app_state

    async def check_all(self) -> dict[str, Any]:
        """Run all health checks concurrently.

        Returns a dict with ``status`` (``"healthy"`` or ``"degraded"``),
        ``checks`` (per-service details), and ``elapsed_ms``.
        """
        started = time.monotonic()

        coros = {
            "database": self._check_database(),
            "llm": self._check_llm(),
            "dashboard_agent": self._check_dashboard(),
            "guardian_agent": self._check_guardian(),
            "auto_correction": self._check_auto_correction(),
            "background_workers": self._check_workers(),
            "file_locks": self._check_file_locks(),
        }

        async def run_check(name: str, coro: Any) -> tuple[str, dict[str, Any]]:
            try:
                return name, await asyncio.wait_for(coro, timeout=_CHECK_TIMEOUT)
            except TimeoutError:
                result = {"status": "timeout", "healthy": False}
                logger.warning("Health check timeout: %s", name)
            except Exception as exc:
                result = {"status": f"error: {exc}", "healthy": False}
                logger.warning("Health check error: %s — %s", name, exc)
            return name, result

        # The checks are independent. Running them sequentially made a slow
        # provider/lock probe block every other health signal and inflated the
        # endpoint latency, which in turn made the UI look disconnected.
        checked = await asyncio.gather(*(run_check(name, coro) for name, coro in coros.items()))
        results = dict(checked)

        elapsed_ms = round((time.monotonic() - started) * 1000, 2)
        overall = (
            "healthy" if all(r.get("healthy", False) for r in results.values()) else "degraded"
        )

        return {
            "status": overall,
            "elapsed_ms": elapsed_ms,
            "checks": results,
        }

    # ------------------------------------------------------------------ #
    # Individual checks
    # ------------------------------------------------------------------ #

    async def _check_database(self) -> dict[str, Any]:
        from backend.persistence.db import get_db

        def _ping() -> bool:
            with get_db() as conn:
                row = conn.execute("SELECT 1 AS ok").fetchone()
                return row is not None and row["ok"] == 1

        ok = await asyncio.to_thread(_ping)
        return {"status": "connected" if ok else "failed", "healthy": ok}

    async def _check_llm(self) -> dict[str, Any]:
        client = getattr(self._state, "llm_client", None)
        if client is None:
            return {"status": "not_initialized", "healthy": False}

        if hasattr(client, "health_check"):
            try:
                ok = await asyncio.wait_for(client.health_check(), timeout=_CHECK_TIMEOUT)
                return {"status": "reachable" if ok else "unreachable", "healthy": ok}
            except TimeoutError:
                return {"status": "timeout", "healthy": False}
        # Fallback: if the client has no health_check, assume healthy when present
        return {"status": "present", "healthy": True}

    async def _check_dashboard(self) -> dict[str, Any]:
        task = getattr(self._state, "dashboard_monitor_task", None)
        if task is None:
            return {"status": "not_started", "healthy": False}
        ok = not task.done()
        return {"status": "running" if ok else "stopped", "healthy": ok}

    async def _check_guardian(self) -> dict[str, Any]:
        guardian = getattr(self._state, "guardian_agent", None)
        task = getattr(self._state, "guardian_task", None)
        if guardian is None or task is None:
            return {"status": "not_started", "healthy": False}
        ok = guardian._running and not task.done()
        return {"status": "running" if ok else "stopped", "healthy": ok}

    async def _check_auto_correction(self) -> dict[str, Any]:
        loop = getattr(self._state, "auto_correction", None)
        if loop is None:
            return {"status": "not_started", "healthy": False}
        task = getattr(loop, "_task", None)
        monitoring = getattr(loop, "_status", {}).get("monitoring", False)
        ok = monitoring and task is not None and not task.done()
        return {"status": "monitoring" if ok else "stopped", "healthy": ok}

    async def _check_workers(self) -> dict[str, Any]:
        manager = getattr(self._state, "worker_manager", None)
        if manager is None:
            return {"status": "not_started", "healthy": False}

        infos = manager.list_workers()
        all_running = all(info.status == "running" for info in infos)
        worker_statuses = {info.name: info.status for info in infos}
        return {
            "status": "all_running" if all_running else "partial",
            "healthy": all_running,
            "workers": worker_statuses,
        }

    async def _check_file_locks(self) -> dict[str, Any]:
        from backend.core.file_locks import FileLockManager

        manager = FileLockManager()
        tmp_file = Path(tempfile.gettempdir()) / f"nexus_health_lock_{time.time()}.tmp"
        try:
            await asyncio.wait_for(
                manager.acquire_write_lock(str(tmp_file), "health-check", timeout=_CHECK_TIMEOUT),
                timeout=_CHECK_TIMEOUT,
            )
            manager.release_lock(str(tmp_file), "health-check")
            return {"status": "functional", "healthy": True}
        except TimeoutError:
            return {"status": "timeout", "healthy": False}
        except Exception as exc:
            return {"status": f"error: {exc}", "healthy": False}
        finally:
            # Best-effort cleanup
            try:
                tmp_file.unlink(missing_ok=True)
            except Exception as exc:
                logger.debug("Failed to remove temporary health file: %s", exc)
