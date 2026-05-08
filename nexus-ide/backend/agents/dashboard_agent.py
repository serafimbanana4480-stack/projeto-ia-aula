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
from typing import AsyncIterator

from .base import AgentBase, AgentRequest


class DashboardAgent(AgentBase):
    name = "DASHBOARD"
    model_key = "dashboard"
    prompt_file = "dashboard"
    supported_actions = set()

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """On-demand Q&A about metrics."""
        raise NotImplementedError

    async def monitor_loop(self) -> None:
        """Background loop. Starts at backend boot, never exits."""
        while True:  # pragma: no cover — stub
            # TODO: scrape Prometheus, detect anomalies, push to event bus
            await asyncio.sleep(10)

    async def session_summary_loop(self) -> None:
        """Lower-frequency loop producing 5-minute summaries."""
        while True:  # pragma: no cover — stub
            # TODO: produce rolling summary, update routing-quality score
            await asyncio.sleep(300)
