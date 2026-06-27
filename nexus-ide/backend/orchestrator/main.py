"""FastAPI entry point for the NEXUS orchestrator.

Tier 1 exposes the critical vertical slice:

- ``GET  /health``                      liveness probe
- ``GET  /api/sessions/{id}/history``   conversation replay
- ``POST /api/chat``                    Server-Sent Events streaming

Remaining endpoints from ARCHITECTURE.md §7.3 (metrics, dashboard, files,
code-execution) are scheduled for later tiers.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request

# Sistemas Autónomos (Self-Monitoring, Self-Improvement, Auto-Config)
from backend.core.self_monitoring import SelfMonitor
from backend.core.self_improvement import SelfImprovement
from backend.core.auto_config import AutoConfig
from backend.llm.fallback_chain import LLMFallbackChain

# Inicializar sistemas autónomos
self_monitor = SelfMonitor()
self_improver = SelfImprovement()
auto_config = AutoConfig()
# providers_config commented - LLM fallback chain will be initialized in main_enhanced
llm_fallback_chain = None
