"""DASHBOARD AGENT — always-on monitor on a dedicated Ollama instance.

Model: qwen3.5:4b on port 11435 (see `config/models.yaml` -> dashboard).
Prompt: config/prompts/dashboard.md
See ARCHITECTURE.md §3.9 and §9.

Runs an independent background loop:
  - every 10s: scrape metrics, detect anomalies, emit events
  - every 5min: produce session summary, assess routing quality
  - on demand: answer natural-language questions about metrics
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from .base import AgentBase, AgentRequest

logger = logging.getLogger(__name__)


class DashboardAgent(AgentBase):
    name = "DASHBOARD"
    model_key = "dashboard"
    prompt_file = "dashboard"
    supported_actions = set()

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
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
            {"role": "system", "content": f"You are a system monitoring assistant. Use the following data to answer questions:\n{context}"},
            {"role": "user", "content": request.query},
        ]

        try:
            if request.client:
                async for chunk in request.client.chat_stream(
                    model=self.model_key or "qwen3:4b",
                    messages=messages,
                ):
                    yield chunk
            else:
                yield "Dashboard agent: no Ollama client available. " + context
        except Exception as exc:
            logger.error("Dashboard agent error: %s", exc)
            yield f"Error querying dashboard: {exc}"

    async def monitor_loop(self) -> None:
        """Background loop. Starts at backend boot, never exits."""
        while True:
            try:
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

            except Exception as exc:
                logger.debug("Monitor loop error: %s", exc)

            await asyncio.sleep(10)

    async def session_summary_loop(self) -> None:
        """Lower-frequency loop producing 5-minute summaries."""
        while True:
            try:
                from backend.persistence.db import get_message_statistics
                stats = get_message_statistics()
                if stats.get("total_messages", 0) > 0:
                    logger.info(
                        "Session summary: %d messages, avg latency %.0fms",
                        stats.get("total_messages", 0),
                        stats.get("avg_latency_ms", 0),
                    )
            except Exception as exc:
                logger.debug("Summary loop error: %s", exc)

            await asyncio.sleep(300)
