"""DASHBOARD AGENT — always-on monitor on a dedicated Ollama instance.

Model: qwen2.5:3b (FAST tier) on port 11434 (see `config/models.yaml` -> dashboard).
Prompt: config/prompts/dashboard.md
See ARCHITECTURE.md §3.9 and §9.

Runs an independent background loop:
  - every 10s: scrape metrics, detect anomalies, emit events
  - every 5min: produce session summary, assess routing quality
  - on demand: answer natural-language questions about metrics

Includes circuit breaker: if Ollama is unavailable, the loops back off
exponentially instead of spamming errors.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

from backend.tools.ollama_client import ChatMessage

from .base import AgentBase, AgentRequest

logger = logging.getLogger(__name__)


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
        # Check if reset timeout has elapsed
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


class DashboardAgent(AgentBase):
    name = "DASHBOARD"
    model_key = "dashboard"
    prompt_file = "dashboard"
    supported_actions = set()

    def __init__(self) -> None:
        super().__init__()
        self._monitor_breaker = _CircuitBreaker(failure_threshold=3, reset_timeout_seconds=120.0)
        self._summary_breaker = _CircuitBreaker(failure_threshold=3, reset_timeout_seconds=300.0)

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        """On-demand Q&A about metrics.

        Fetches current system metrics and formats them as context,
        then uses the Ollama client to answer the user's question.
        """
        # Collect current metrics as context
        context_parts: list[str] = []

        try:
            from backend.observability.metrics_collector import collect_snapshot
            snapshot = collect_snapshot()
            context_parts.append(f"System Metrics: {snapshot}")
        except Exception as exc:
            logger.warning("Failed to collect metrics for dashboard: %s", exc)
            context_parts.append("System Metrics: unavailable")

        try:
            from backend.persistence.db import get_message_statistics
            stats = get_message_statistics()
            context_parts.append(f"Message Stats: {stats}")
        except Exception as exc:
            logger.warning("Failed to get message stats: %s", exc)

        context = "\n".join(context_parts)

        # Build messages for the model
        messages = [
            ChatMessage(role="system", content=f"You are a system monitoring assistant. Use the following data to answer questions:\n{context}"),
            ChatMessage(role="user", content=request.query),
        ]

        try:
            if request.client:
                async for chunk in request.client.chat_stream(
                    model=self.resolve_model_id(),
                    messages=messages,
                ):
                    yield chunk
            else:
                yield "Dashboard agent: no Ollama client available. " + context
        except Exception as exc:
            logger.error("Dashboard agent error: %s", exc)
            yield f"Error querying dashboard: {exc}"

    async def monitor_loop(self) -> None:
        """Background loop. Starts at backend boot, never exits.

        Uses circuit breaker to back off when Ollama is unavailable.
        """
        while True:
            try:
                if self._monitor_breaker.is_open:
                    # Circuit breaker is open — skip this cycle
                    await asyncio.sleep(10)
                    continue

                # Scrape metrics and detect anomalies
                from backend.observability.metrics_collector import collect_snapshot
                snapshot = collect_snapshot()

                # Check for anomalies (high CPU, low memory, etc.)
                if isinstance(snapshot, dict):
                    cpu = snapshot.get("cpu_percent", 0)
                    if cpu > 90:
                        logger.warning("High CPU detected: %.1f%%", cpu)

                    mem = snapshot.get("memory_percent", 0)
                    if mem > 90:
                        logger.warning("High memory usage: %.1f%%", mem)

                self._monitor_breaker.record_success()

            except Exception as exc:
                self._monitor_breaker.record_failure()
                if not self._monitor_breaker.is_open:
                    logger.debug("Monitor loop error: %s", exc)

            await asyncio.sleep(10)

    async def session_summary_loop(self) -> None:
        """Lower-frequency loop producing 5-minute summaries.

        Uses circuit breaker to back off when DB is unavailable.
        """
        while True:
            try:
                if self._summary_breaker.is_open:
                    # Circuit breaker is open — skip this cycle
                    await asyncio.sleep(300)
                    continue

                from backend.persistence.db import get_message_statistics
                stats = get_message_statistics()
                if stats.get("total_messages", 0) > 0:
                    logger.info(
                        "Session summary: %d messages, avg latency %.0fms",
                        stats.get("total_messages", 0),
                        stats.get("avg_latency_ms", 0),
                    )

                self._summary_breaker.record_success()

            except Exception as exc:
                self._summary_breaker.record_failure()
                if not self._summary_breaker.is_open:
                    logger.debug("Summary loop error: %s", exc)

            await asyncio.sleep(300)
