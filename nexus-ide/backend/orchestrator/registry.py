"""Single source of truth mapping :class:`AgentName` → :class:`AgentBase` instance.

The registry is constructed once at process startup and reused across requests.
Tests can inject a custom registry via :func:`set_registry`.
"""
from __future__ import annotations

from typing import Mapping

from backend.agents.analyzer import AnalyzerAgent
from backend.agents.architect import ArchitectAgent
from backend.agents.base import AgentBase
from backend.agents.coder import CoderAgent
from backend.agents.debugger import DebuggerAgent
from backend.agents.documenter import DocumenterAgent
from backend.agents.micro import MicroAgent
from backend.agents.optimizer import OptimizerAgent
from backend.agents.researcher import ResearcherAgent
from backend.models.api import AgentName

AgentRegistry = Mapping[AgentName, AgentBase]


def build_default_registry() -> dict[AgentName, AgentBase]:
    """Construct the standard set of agents. Call once at app startup."""
    return {
        "ARCHITECT":  ArchitectAgent(),
        "RESEARCHER": ResearcherAgent(),
        "CODER":      CoderAgent(),
        "ANALYZER":   AnalyzerAgent(),
        "DEBUGGER":   DebuggerAgent(),
        "DOCUMENTER": DocumenterAgent(),
        "OPTIMIZER":  OptimizerAgent(),
        "MICRO":      MicroAgent(),
    }


def resolve(registry: AgentRegistry, name: AgentName) -> AgentBase:
    """Return the agent for ``name`` or fall back to CODER.

    DASHBOARD and ROUTER are never user-invocable; route them to CODER so the
    system still produces useful output instead of 500-ing.
    """
    if name in registry:
        return registry[name]
    return registry["CODER"]
