"""NEXUS — the primary agent that talks to the user and owns the task.

Phase 2 documented the shape of the old system: a fixed cast (ARCHITECT →
PLANNER → CODER → DEBUGGER) was spawned for every request because a routing
table said so, and the user watched a relay race between agents that each
saw a fraction of the problem.

NEXUS replaces the cast with one persistent agent. It has the union of the
tools the specialists had, so there is nothing a specialist could do that it
must delegate. Delegation still exists — it is just no longer the default
(see :mod:`backend.runtime.spawn_policy`).

The specialists are intentionally left registered: they are still reachable
through an explicit mode and through approved delegation. This class does not
replace them, it stops them from being mandatory.
"""

from __future__ import annotations

import os

from .base import AgentAction, AgentBase

#: Model tier for the primary agent. It has to be strong enough to both write
#: code and hold a conversation, so it defaults to the coder tier rather than
#: to a fast/nano tier.
PRIMARY_MODEL_KEY = os.environ.get("NEXUS_PRIMARY_MODEL_KEY", "coder").strip() or "coder"


class NexusPrimaryAgent(AgentBase):
    """Single user-facing agent with the full tool surface."""

    name = "NEXUS"
    model_key = PRIMARY_MODEL_KEY
    prompt_file = "nexus_primary"
    supported_actions = {
        # observe
        AgentAction.READ_FILE,
        AgentAction.READ_FILE_ABSOLUTE,
        AgentAction.LIST_DIR,
        AgentAction.LIST_DIR_ABSOLUTE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.SEARCH_SYMBOLS,
        AgentAction.INDEX_SYMBOLS,
        AgentAction.READ_DOCS,
        AgentAction.RECALL_CONTEXT,
        AgentAction.MCP_PROJECT_CONTEXT,
        AgentAction.MCP_IMPACT_ANALYSIS,
        # act
        AgentAction.WRITE_FILE,
        AgentAction.WRITE_FILE_ABSOLUTE,
        AgentAction.EXECUTE_CODE,
        AgentAction.RUN_SHELL,
        AgentAction.SCAFFOLD_PROJECT,
        AgentAction.FORMAT_CODE,
        # verify
        AgentAction.RUN_TESTS,
        AgentAction.RUN_LINT,
        AgentAction.TYPE_CHECK,
        # reach out
        AgentAction.SEARCH_WEB,
        AgentAction.FETCH_URL,
        AgentAction.SEARCH_DOCS,
        AgentAction.STORE_MEMORY,
        # delegate — gated by the spawn policy, never automatic
        AgentAction.SPAWN_TASK,
        AgentAction.CONSULT_AGENT,
    }
