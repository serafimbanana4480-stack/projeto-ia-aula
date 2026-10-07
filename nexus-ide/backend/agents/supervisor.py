"""Supervisor agent — monitors all agent activity and suggests improvements.

The supervisor watches:
1. Tool execution success/failure rates
2. File operations (creates, modifies, deletes)
3. Code quality indicators
4. Security concerns
5. Performance bottlenecks

It runs asynchronously and can be consulted by other agents
or triggered automatically after significant operations.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from backend.agents.base import AgentBase, AgentRequest
from backend.persistence.db import get_session

logger = logging.getLogger(__name__)


class SupervisorAgent(AgentBase):
    """Supervisor agent that monitors and improves all agent work."""

    name = "SUPERVISOR"
    model_key = "fast"
    prompt_file = "supervisor"
    supported_actions = set()

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run supervisor analysis on the current session or project."""
        logger.info("[SUPERVISOR] Analysing session %s", request.session_id)

        # Gather session statistics
        stats = self._gather_session_stats(request.session_id)
        stats_context = (
            f"SESSION STATISTICS:\n{json.dumps(stats, indent=2, default=str)}\n\n"
        )
        logger.info("[SUPERVISOR] Session stats: %s", stats_context.strip())
        enriched_request = AgentRequest(
            session_id=request.session_id,
            query=stats_context + f"User query: {request.query}",
            client=request.client,
            history=request.history,
            context=request.context,
            max_iterations=request.max_iterations,
            enable_thinking=request.enable_thinking,
            project_path=request.project_path,
            autonomous=request.autonomous,
        )

        async for token in self._run_react_loop(enriched_request):
            yield token

    def _gather_session_stats(self, session_id: str) -> dict[str, Any]:
        """Collect statistics about a session."""
        session = get_session(session_id)
        stats: dict[str, Any] = {
            "session_id": session_id,
            "exists": session is not None,
        }
        if session:
            stats["message_count"] = session.get("message_count", 0)
            stats["mode"] = session.get("mode", "unknown")
            stats["latency_avg_ms"] = session.get("latency_avg_ms", 0)
        return stats


# Register the supervisor so it can be consulted
def register_supervisor(registry: dict[str, AgentBase]) -> None:
    """Add SupervisorAgent to the agent registry."""
    from backend.orchestrator.registry import register_agent

    supervisor = SupervisorAgent()
    register_agent(supervisor.name, supervisor)
    registry[supervisor.name] = supervisor
    logger.info("Supervisor agent registered")
