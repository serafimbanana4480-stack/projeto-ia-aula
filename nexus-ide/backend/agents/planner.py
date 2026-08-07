"""PLANNER -- decomposes goals and coordinates specialist input.

The planner is deliberately a coordination agent: it recalls relevant project
context, delegates unknowns to RESEARCHER and failures to DEBUGGER, then emits
an ordered plan that can be executed by the orchestrator.
"""

from __future__ import annotations

from .base import AgentAction, AgentBase


class PlannerAgent(AgentBase):
    """Turn a user objective into an evidence-backed, verifiable work plan."""

    name = "PLANNER"
    model_key = "coder"
    prompt_file = "planner"
    supported_actions = {
        AgentAction.CONSULT_AGENT,
        AgentAction.RECALL_CONTEXT,
        AgentAction.STORE_MEMORY,
        AgentAction.EXECUTE_CODE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.READ_FILE,
    }
