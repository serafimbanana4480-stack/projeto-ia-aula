"""DASHBOARD AGENT — autonomous system monitor and metrics interpreter.

Model: qwen2.5-coder:1.5b (DASHBOARD tier) on the configured Ollama instance.
Prompt: config/prompts/dashboard.md
See ARCHITECTURE.md §3.9 and §9.

Runs an independent background loop:
  - every 10s: scrape metrics, detect anomalies, emit events, raise alerts
  - every 5min: produce session summary, assess routing quality, recommendations
  - on demand: answer natural-language questions about metrics and health

Includes circuit breaker: if Ollama is unavailable, the loops back off
exponentially instead of spamming errors.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import statistics
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.tools.ollama_client import ChatMessage

from .base import AgentAction, AgentBase, AgentRequest

logger = logging.getLogger(__name__)


@dataclass
class _CircuitBreaker:
    """Prevents repeated calls to a failing service.

    After `failure_threshold` consecutive failures, the breaker opens and
    refuses calls for `reset_timeout_seconds`. After that, it allows one
    probe call. If that succeeds, the breaker closes again.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        reset_timeout_seconds: float = 60.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout_seconds
        self._consecutive_failures = 0
        self._last_failure_time: float = 0.0
        self._open = False

    @property
    def is_open(self) -> bool:
        """Whether the circuit breaker is currently open (blocking calls)."""
        if not self._open:
            return False
        if time.time() - self._last_failure_time > self._reset_timeout:
            logger.info("Circuit breaker: reset timeout elapsed, allowing probe")
            self._open = False
            return False
        return True

    def record_success(self) -> None:
        """Record a successful call."""
        self._consecutive_failures = 0
        self._open = False

    def record_failure(self) -> None:
        """Record a failed call."""
        self._consecutive_failures += 1
        self._last_failure_time = time.time()
        if self._consecutive_failures >= self._failure_threshold:
            self._open = True
            logger.warning(
                "Circuit breaker OPEN after %d consecutive failures "
                "(will retry in %.0fs)",
                self._consecutive_failures,
                self._reset_timeout,
            )


@dataclass
class Alert:
    """Structured alert emitted by the dashboard agent."""

    id: str
    severity: str  # info, warning, alert, critical
    source: str
    message: str
    metric: str
    value: float
    threshold: float
    timestamp: str
    recommendation: str = ""


class DashboardAgent(AgentBase):
    name = "DASHBOARD"
    model_key = "dashboard"
    prompt_file = "dashboard"
    supported_actions = {
        AgentAction.CONSULT_AGENT,
        AgentAction.RECALL_CONTEXT,
        AgentAction.STORE_MEMORY,
        AgentAction.ANALYZE_DATA,
    }

    def __init__(self) -> None:
        super().__init__()
        self._monitor_breaker = _CircuitBreaker(failure_threshold=3, reset_timeout_seconds=120.0)
        self._summary_breaker = _CircuitBreaker(failure_threshold=3, reset_timeout_seconds=300.0)
        self._history: deque[dict[str, Any]] = deque(maxlen=1000)
        self._alerts: deque[Alert] = deque(maxlen=100)
        self._rolling_minutes = 5
        self._last_alert_time: dict[str, float] = {}

    ALERT_DEBOUNCE_SECONDS = 900  # 15 minutes

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        """On-demand Q&A about metrics using the ReAct loop.

        The agent can now consult specialist agents (e.g. ANALYZER, DEBUGGER)
        and recall/store memories, making dashboard responses context-aware and
        autonomously actionable.
        """
        metrics_context = await self._build_metrics_context()
        # Enrich the user query with current metrics so the ReAct loop has the
        # latest snapshot available even if it does not call any tools.
        enriched_query = (
            f"CURRENT SYSTEM METRICS:\n{metrics_context}\n\n"
            f"USER QUESTION:\n{request.query}"
        )
        enriched_request = AgentRequest(
            session_id=request.session_id,
            query=enriched_query,
            client=request.client,
            history=request.history,
            context=request.context,
            max_iterations=request.max_iterations,
            enable_thinking=request.enable_thinking,
            project_path=request.project_path,
        )
        async for token in self._run_react_loop(enriched_request):
            yield token

    async def monitor_loop(self) -> None:
        """Background loop. Starts at backend boot, never exits."""
        while True:
            try:
                if self._monitor_breaker.is_open:
                    await asyncio.sleep(10)
                    continue

                snapshot = await self._collect_metrics()
                self._history.append(snapshot)

                alerts = self._detect_anomalies(snapshot, list(self._history))
                for alert in alerts:
                    self._alerts.append(alert)
                    self._emit_alert(alert)

                self._monitor_breaker.record_success()

            except Exception as exc:
                self._monitor_breaker.record_failure()
                if not self._monitor_breaker.is_open:
                    logger.debug("Monitor loop error: %s", exc)

            await asyncio.sleep(10)

    async def session_summary_loop(self) -> None:
        """Lower-frequency loop producing 5-minute summaries."""
        while True:
            try:
                if self._summary_breaker.is_open:
                    await asyncio.sleep(300)
                    continue

                summary = await self._produce_summary()
                if summary:
                    logger.info(
                        "Dashboard summary | messages=%d | routing_score=%.2f | alerts=%d",
                        summary.get("total_messages", 0),
                        summary.get("routing_quality_score", 0.0),
                        len([a for a in self._alerts if a.severity in ("alert", "critical")]),
                    )
                    self._emit_summary(summary)

                self._summary_breaker.record_success()

            except Exception as exc:
                self._summary_breaker.record_failure()
                if not self._summary_breaker.is_open:
                    logger.debug("Summary loop error: %s", exc)

            await asyncio.sleep(300)

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    async def _collect_metrics(self) -> dict[str, Any]:
        """Collect current metrics from all available sources."""
        snapshot: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "status": "nominal",
        }

        try:
            from backend.observability.metrics_collector import get_metrics_collector
            collector = get_metrics_collector()
            ms = await collector.get_snapshot()
            snapshot.update({
                "cpu_percent": ms.cpu_percent,
                "ram_percent": ms.ram_percent,
                "disk_percent": ms.disk_percent,
                "tokens_per_second": ms.tokens_per_second,
                "active_model": ms.active_model,
                "active_sessions": ms.active_sessions,
                "queue_depth": ms.queue_depth,
                "requests_total": ms.requests_total,
                "requests_successful": ms.requests_successful,
                "requests_failed": ms.requests_failed,
                "avg_latency_ms": ms.avg_latency_ms,
                "uptime_seconds": ms.uptime_seconds,
            })
        except Exception as exc:
            logger.warning("Failed to collect system metrics: %s", exc)
            snapshot["collector_error"] = str(exc)

        try:
            from backend.persistence.db import get_message_statistics
            stats = await asyncio.to_thread(get_message_statistics)
            snapshot["message_stats"] = stats
        except Exception as exc:
            logger.warning("Failed to get message stats: %s", exc)
            snapshot["message_stats_error"] = str(exc)

        try:
            db_stats = await asyncio.to_thread(self._collect_db_stats)
            snapshot["db_stats"] = db_stats
        except Exception as exc:
            logger.warning("Failed to collect DB stats: %s", exc)
            snapshot["db_stats_error"] = str(exc)

        return snapshot

    def _collect_db_stats(self) -> dict[str, Any]:
        """Collect recent DB activity statistics."""
        from backend.persistence.db import get_db

        stats: dict[str, Any] = {}
        with get_db() as conn:
            # Recent tool executions
            try:
                rows = conn.execute(
                    "SELECT tool_name, success, COUNT(*) AS cnt, AVG(duration_ms) AS avg_ms "
                    "FROM tool_executions WHERE created_at > datetime('now', '-5 minutes') "
                    "GROUP BY tool_name, success"
                ).fetchall()
                stats["recent_tools"] = [dict(r) for r in rows]
            except Exception:
                stats["recent_tools"] = []

            # Recent routing decisions
            try:
                rows = conn.execute(
                    "SELECT tier_chosen, COUNT(*) AS cnt, AVG(confidence) AS avg_confidence "
                    "FROM routing_decisions WHERE created_at > datetime('now', '-5 minutes') "
                    "GROUP BY tier_chosen"
                ).fetchall()
                stats["recent_routing"] = [dict(r) for r in rows]
            except Exception:
                stats["recent_routing"] = []

            # Error rate from messages (approximate via tool_executions)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS total, "
                    "SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed "
                    "FROM tool_executions WHERE created_at > datetime('now', '-5 minutes')"
                ).fetchone()
                if row:
                    total = row["total"] or 0
                    failed = row["failed"] or 0
                    stats["tool_error_rate"] = failed / max(1, total)
            except Exception:
                stats["tool_error_rate"] = 0.0

        return stats

    # ------------------------------------------------------------------
    # Anomaly detection
    # ------------------------------------------------------------------

    def _should_alert(self, metric: str, severity: str) -> bool:
        key = f"{severity}:{metric}"
        now = time.time()
        last = self._last_alert_time.get(key, 0.0)
        if now - last < self.ALERT_DEBOUNCE_SECONDS:
            return False
        self._last_alert_time[key] = now
        return True

    def _detect_anomalies(self, snapshot: dict[str, Any], history: list[dict[str, Any]]) -> list[Alert]:
        """Detect anomalies in the current snapshot."""
        alerts: list[Alert] = []
        now = snapshot.get("timestamp", datetime.now(UTC).isoformat())

        # Threshold-based alerts
        cpu = snapshot.get("cpu_percent", 0) or 0
        if cpu > 90 and self._should_alert("cpu_percent", "critical"):
            alerts.append(self._make_alert("critical", "cpu_percent", cpu, 90, "CPU usage critically high", now))
        elif cpu > 75 and self._should_alert("cpu_percent", "alert"):
            alerts.append(self._make_alert("alert", "cpu_percent", cpu, 75, "CPU usage elevated", now))

        ram = snapshot.get("ram_percent", 0) or 0
        if ram > 90 and self._should_alert("ram_percent", "critical"):
            alerts.append(self._make_alert("critical", "ram_percent", ram, 90, "Memory usage critically high", now))
        elif ram > 80 and self._should_alert("ram_percent", "alert"):
            alerts.append(self._make_alert("alert", "ram_percent", ram, 80, "Memory usage elevated", now))

        disk = snapshot.get("disk_percent", 0) or 0
        if disk > 90 and self._should_alert("disk_percent", "critical"):
            alerts.append(self._make_alert("critical", "disk_percent", disk, 90, "Disk usage critically high", now))
        elif disk > 80 and self._should_alert("disk_percent", "alert"):
            alerts.append(self._make_alert("alert", "disk_percent", disk, 80, "Disk usage elevated", now))

        # Latency alert
        latency = snapshot.get("avg_latency_ms", 0) or 0
        if latency > 5000 and self._should_alert("avg_latency_ms", "alert"):
            alerts.append(self._make_alert("alert", "avg_latency_ms", latency, 5000, "Average latency very high", now))

        # Error rate alert
        error_rate = snapshot.get("db_stats", {}).get("tool_error_rate", 0) or 0
        if error_rate > 0.25 and self._should_alert("tool_error_rate", "alert"):
            alerts.append(self._make_alert("alert", "tool_error_rate", error_rate, 0.25, "Tool error rate elevated", now))

        # Statistical anomaly: z-score over rolling window
        for metric in ("cpu_percent", "ram_percent", "avg_latency_ms"):
            if self._should_alert(metric, "warning"):
                z_alert = self._zscore_alert(metric, snapshot, history, now)
                if z_alert:
                    alerts.append(z_alert)

        # Determine overall status
        if any(a.severity == "critical" for a in alerts):
            snapshot["status"] = "critical"
        elif any(a.severity == "alert" for a in alerts):
            snapshot["status"] = "alert"
        elif any(a.severity == "warning" for a in alerts):
            snapshot["status"] = "warning"
        else:
            snapshot["status"] = "nominal"

        return alerts

    def _make_alert(
        self,
        severity: str,
        metric: str,
        value: float,
        threshold: float,
        message: str,
        timestamp: str,
        recommendation: str = "",
    ) -> Alert:
        if not recommendation:
            recommendation = self._default_recommendation(metric, severity)
        return Alert(
            id=f"{metric}-{int(time.time() * 1000)}",
            severity=severity,
            source="dashboard",
            message=message,
            metric=metric,
            value=value,
            threshold=threshold,
            timestamp=timestamp,
            recommendation=recommendation,
        )

    def _default_recommendation(self, metric: str, severity: str) -> str:
        if metric == "cpu_percent":
            return "Reduce concurrent agent runs or switch to lighter models."
        if metric == "ram_percent":
            return "Close unused sessions or restart memory-heavy services."
        if metric == "disk_percent":
            return "Free up disk space or archive old logs/sessions."
        if metric == "avg_latency_ms":
            return "Check LLM provider health or enable fallback models."
        if metric == "tool_error_rate":
            return "Review recent tool failures and agent instructions."
        return "Investigate the affected component."

    def _zscore_alert(
        self,
        metric: str,
        snapshot: dict[str, Any],
        history: list[dict[str, Any]],
        timestamp: str,
    ) -> Alert | None:
        """Detect statistical outliers using z-score over recent history."""
        values = [h.get(metric) for h in history[-60:] if h.get(metric) is not None]
        current = snapshot.get(metric)
        if current is None or len(values) < 10:
            return None

        try:
            mean = statistics.mean(values)
            stdev = statistics.stdev(values)
        except Exception:
            return None

        if stdev == 0:
            return None

        z_score = (current - mean) / stdev
        if z_score > 2.5:
            return self._make_alert(
                severity="warning",
                metric=metric,
                value=current,
                threshold=mean + 2 * stdev,
                message=f"{metric} is {z_score:.1f} standard deviations above recent average",
                timestamp=timestamp,
                recommendation=f"Investigate spike in {metric}; consider recent load changes.",
            )
        return None

    # ------------------------------------------------------------------
    # Summaries and interpretation
    # ------------------------------------------------------------------

    async def _produce_summary(self) -> dict[str, Any] | None:
        """Produce a 5-minute session and routing quality summary."""
        try:
            from backend.persistence.db import get_message_statistics
            stats = await asyncio.to_thread(get_message_statistics)
        except Exception:
            stats = {}

        if not stats.get("total_messages", 0):
            return None

        routing_score = await self._compute_routing_quality_score()

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "total_messages": stats.get("total_messages", 0),
            "sessions_with_messages": stats.get("sessions_with_messages", 0),
            "avg_latency_ms": stats.get("avg_latency_ms", 0),
            "routing_quality_score": routing_score,
            "active_alerts": len([a for a in self._alerts if a.severity in ("alert", "critical")]),
            "recent_alert_count": len(self._alerts),
        }

    async def _compute_routing_quality_score(self) -> float:
        """Heuristic routing quality score 0-1 based on recent DB data."""

        def _query() -> float:
            from backend.persistence.db import get_db

            try:
                with get_db() as conn:
                    row = conn.execute(
                        "SELECT AVG(confidence) AS avg_confidence, COUNT(*) AS cnt "
                        "FROM routing_decisions WHERE created_at > datetime('now', '-30 minutes')"
                    ).fetchone()
                    if not row or row["cnt"] == 0:
                        return 0.0
                    confidence = row["avg_confidence"] or 0
                    return round(min(1.0, max(0.0, confidence)), 2)
            except Exception:
                return 0.0

        try:
            return await asyncio.to_thread(_query)
        except Exception:
            return 0.0

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    def _emit_alert(self, alert: Alert) -> None:
        """Emit an alert to the event bus and log it."""
        if alert.severity in ("alert", "critical"):
            logger.warning(
                "[%s] %s: %s (%.2f > %.2f)",
                alert.severity.upper(),
                alert.metric,
                alert.message,
                alert.value,
                alert.threshold,
            )
        else:
            logger.info("[DASHBOARD] %s: %s", alert.metric, alert.message)

        try:
            from backend.core.agent_bus import BusMessage, get_agent_bus

            bus = get_agent_bus()
            asyncio.create_task(
                bus.publish(
                    "system.alert",
                    BusMessage(
                        message_id=alert.id,
                        topic="system.alert",
                        source_agent="DASHBOARD",
                        target_agents=[],
                        payload={
                            "severity": alert.severity,
                            "metric": alert.metric,
                            "message": alert.message,
                            "value": alert.value,
                            "threshold": alert.threshold,
                            "recommendation": alert.recommendation,
                            "timestamp": alert.timestamp,
                        },
                        priority=4 if alert.severity == "critical" else 3,
                    ),
                )
            )
        except Exception as exc:
            logger.debug("Failed to emit dashboard alert to bus: %s", exc)

    def _emit_summary(self, summary: dict[str, Any]) -> None:
        """Emit a periodic summary to the event bus."""
        try:
            from backend.core.agent_bus import BusMessage, get_agent_bus

            bus = get_agent_bus()
            asyncio.create_task(
                bus.publish(
                    "system.summary",
                    BusMessage(
                        message_id=f"summary-{int(time.time())}",
                        topic="system.summary",
                        source_agent="DASHBOARD",
                        target_agents=[],
                        payload=summary,
                        priority=2,
                    ),
                )
            )
        except Exception as exc:
            logger.debug("Failed to emit dashboard summary to bus: %s", exc)

    # ------------------------------------------------------------------
    # On-demand context building
    # ------------------------------------------------------------------

    async def _build_metrics_context(self) -> str:
        """Build a rich text context for on-demand metric Q&A."""
        snapshot = await self._collect_metrics()
        history = list(self._history)

        parts = [
            "CURRENT SYSTEM SNAPSHOT",
            f"Status: {snapshot.get('status', 'unknown')}",
            f"CPU: {snapshot.get('cpu_percent', 'n/a')}%",
            f"RAM: {snapshot.get('ram_percent', 'n/a')}%",
            f"Disk: {snapshot.get('disk_percent', 'n/a')}%",
            f"Active sessions: {snapshot.get('active_sessions', 'n/a')}",
            f"Queue depth: {snapshot.get('queue_depth', 'n/a')}",
            f"Avg latency: {snapshot.get('avg_latency_ms', 'n/a')}ms",
            f"Tokens/s: {snapshot.get('tokens_per_second', 'n/a')}",
            f"Requests: {snapshot.get('requests_total', 0)} total, "
            f"{snapshot.get('requests_successful', 0)} ok, "
            f"{snapshot.get('requests_failed', 0)} failed",
            "",
            "MESSAGE STATISTICS",
            str(snapshot.get("message_stats", {})),
            "",
            "DB ACTIVITY (last 5 min)",
            str(snapshot.get("db_stats", {})),
            "",
            "ACTIVE ALERTS",
            str([self._alert_to_dict(a) for a in list(self._alerts)[-10:]]),
        ]

        # Add trend context
        if history:
            recent = history[-30:]
            cpu_values = [h.get("cpu_percent") for h in recent if h.get("cpu_percent") is not None]
            ram_values = [h.get("ram_percent") for h in recent if h.get("ram_percent") is not None]
            if cpu_values:
                with contextlib.suppress(Exception):
                    parts.extend([
                        "",
                        "TRENDS (last ~5 min)",
                        f"CPU avg: {statistics.mean(cpu_values):.1f}%, max: {max(cpu_values):.1f}%",
                        f"RAM avg: {statistics.mean(ram_values):.1f}%, max: {max(ram_values):.1f}%" if ram_values else "",
                    ])

        return "\n".join(parts)

    def _alert_to_dict(self, alert: Alert) -> dict[str, Any]:
        return {
            "id": alert.id,
            "severity": alert.severity,
            "metric": alert.metric,
            "message": alert.message,
            "value": alert.value,
            "threshold": alert.threshold,
            "recommendation": alert.recommendation,
            "timestamp": alert.timestamp,
        }

    # ------------------------------------------------------------------
    # Public inspection API
    # ------------------------------------------------------------------

    def get_alerts(
        self,
        severity: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent alerts, optionally filtered by severity."""
        alerts = list(self._alerts)
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return [self._alert_to_dict(a) for a in alerts[-limit:]]

    def get_latest_snapshot(self) -> dict[str, Any] | None:
        """Return the most recent metrics snapshot."""
        return dict(self._history[-1]) if self._history else None

    def get_health_score(self) -> float:
        """Compute an overall health score 0-1."""
        if not self._history:
            return 1.0
        snapshot = self._history[-1]
        score = 1.0
        cpu = snapshot.get("cpu_percent", 0) or 0
        ram = snapshot.get("ram_percent", 0) or 0
        disk = snapshot.get("disk_percent", 0) or 0
        latency = snapshot.get("avg_latency_ms", 0) or 0

        if cpu > 90:
            score -= 0.3
        elif cpu > 75:
            score -= 0.15
        if ram > 90:
            score -= 0.25
        elif ram > 80:
            score -= 0.1
        if disk > 90:
            score -= 0.2
        elif disk > 80:
            score -= 0.1
        if latency > 5000:
            score -= 0.2
        elif latency > 2000:
            score -= 0.1

        error_rate = snapshot.get("db_stats", {}).get("tool_error_rate", 0) or 0
        if error_rate > 0.25:
            score -= 0.2
        elif error_rate > 0.1:
            score -= 0.1

        return round(max(0.0, min(1.0, score)), 2)
