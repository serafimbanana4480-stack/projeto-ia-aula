"""Single source of truth mapping :class:`AgentName` â†’ :class:`AgentBase` instance.

The registry is constructed once at process startup and reused across requests.
Tests can inject a custom registry via :func:`set_registry`.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from typing import Any

from backend.agents.base import AgentBase
from backend.models.api import AgentName

AgentRegistry = Mapping[AgentName, AgentBase]

# Agent class map â€” instances are created lazily on first resolve().
_AGENT_CLASSES: dict[AgentName, Any] = {}


def _get_agent_classes() -> dict[AgentName, Any]:
    """Return the mapping of agent names to their classes.

    Importing is deferred until the first call so that heavy agent
    modules (e.g. ``architect``, ``coder``) don't slow down startup.
    """
    global _AGENT_CLASSES
    if _AGENT_CLASSES:
        return _AGENT_CLASSES

    # Deferred imports â€” only executed on first registry use.
    from backend.agents.advisor import AdvisorAgent
    from backend.agents.analyzer import AnalyzerAgent
    from backend.agents.architect import ArchitectAgent
    from backend.agents.architect_complexity import ArchitectComplexityAgent
    from backend.agents.architect_design import ArchitectDesignAgent
    from backend.agents.bug_hunter_runtime import BugHunterRuntimeAgent
    from backend.agents.bug_hunter_static import BugHunterStaticAgent
    from backend.agents.coder import CoderAgent
    from backend.agents.dashboard_agent import DashboardAgent
    from backend.agents.debugger import DebuggerAgent
    from backend.agents.documenter import DocumenterAgent
    from backend.agents.guardian import NexusGuardianAgent
    from backend.agents.meta_analyzer import MetaAnalyzerAgent
    from backend.agents.micro import MicroAgent
    from backend.agents.nexus_primary import NexusPrimaryAgent
    from backend.agents.optimizer import OptimizerAgent
    from backend.agents.overseer import OverseerAgent
    from backend.agents.planner import PlannerAgent
    from backend.agents.refactor_clean import RefactorCleanAgent
    from backend.agents.refactor_performance import RefactorPerformanceAgent
    from backend.agents.researcher import ResearcherAgent
    from backend.agents.researcher_web import ResearcherWebAgent
    from backend.agents.reviewer import ReviewerAgent
    from backend.agents.supervisor import SupervisorAgent
    from backend.agents.test_runner_e2e import TestRunnerE2EAgent
    from backend.agents.test_runner_unit import TestRunnerUnitAgent

    _AGENT_CLASSES = {
        "NEXUS": NexusPrimaryAgent,
        "PLANNER": PlannerAgent,
        "ARCHITECT": ArchitectAgent,
        "ARCHITECT_DESIGN": ArchitectDesignAgent,
        "ARCHITECT_COMPLEXITY": ArchitectComplexityAgent,
        "RESEARCHER": ResearcherAgent,
        "RESEARCHER_WEB": ResearcherWebAgent,
        "CODER": CoderAgent,
        "REVIEWER": ReviewerAgent,
        "ANALYZER": AnalyzerAgent,
        "DEBUGGER": DebuggerAgent,
        "DOCUMENTER": DocumenterAgent,
        "OPTIMIZER": OptimizerAgent,
        "REFACTOR_PERFORMANCE": RefactorPerformanceAgent,
        "REFACTOR_CLEAN": RefactorCleanAgent,
        "MICRO": MicroAgent,
        "DASHBOARD": DashboardAgent,
        "SUPERVISOR": SupervisorAgent,
        "ADVISOR": AdvisorAgent,
        "OVERSEER": OverseerAgent,
        "GUARDIAN": NexusGuardianAgent,
        "TEST_RUNNER_UNIT": TestRunnerUnitAgent,
        "TEST_RUNNER_E2E": TestRunnerE2EAgent,
        "BUG_HUNTER_STATIC": BugHunterStaticAgent,
        "BUG_HUNTER_RUNTIME": BugHunterRuntimeAgent,
        "META_ANALYZER": MetaAnalyzerAgent,
    }
    return _AGENT_CLASSES


@functools.lru_cache(maxsize=1)
def build_default_registry() -> dict[AgentName, AgentBase]:
    """Construct the standard set of agents. Call once at app startup.

    Because agents are instantiated lazily, this returns a thin proxy
    dict.  The first ``resolve()`` call triggers the real import and
    instantiation.  This keeps startup time low while preserving the
    existing interface.

    Cached with ``lru_cache`` so repeated calls are free.
    """
    classes = _get_agent_classes()
    return _LazyRegistry(classes)


_registry_instance: AgentRegistry | None = None


def get_registry(app=None) -> AgentRegistry:
    """Return the agent registry, building it lazily on first access.

    When ``app`` is provided the registry is also attached to
    ``app.state.registry`` so downstream code can read it directly.
    """
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = build_default_registry()
    if app is not None and not hasattr(app.state, "registry"):
        app.state.registry = _registry_instance
    return _registry_instance


def resolve(registry: AgentRegistry, name: AgentName) -> AgentBase:
    """Return the agent for ``name`` or fall back to CODER.

    ROUTER is never user-invocable; route it to CODER so the
    system still produces useful output instead of 500-ing.
    DASHBOARD is invocable for metrics queries.
    """
    if name in registry:
        return registry[name]
    return registry["CODER"]


def register_agent(name: AgentName, agent: AgentBase) -> None:
    """Register a concrete agent instance in the global registry.

    Used by modules such as ``backend.agents.supervisor`` that need to
    inject agents at import time.
    """
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = build_default_registry()
    # If the registry is still a lazy proxy, force materialisation of the
    # internal dict so we can mutate it safely.
    if isinstance(_registry_instance, _LazyRegistry):
        _registry_instance._instances[name] = agent
    else:
        _registry_instance[name] = agent


class _LazyRegistry(dict):
    """Proxy dict that instantiates agents on first access."""

    def __init__(self, classes: dict[AgentName, Any]) -> None:
        import threading

        self._classes = classes
        self._instances: dict[AgentName, AgentBase] = {}
        self._lock = threading.Lock()
        # Pre-populate keys so ``in`` checks work without instantiation
        super().__init__({k: None for k in classes})

    def __getitem__(self, key: AgentName) -> AgentBase:
        with self._lock:
            if key not in self._instances:
                cls = self._classes.get(key)
                if cls is None:
                    raise KeyError(key)
                self._instances[key] = cls()
            return self._instances[key]

    def __contains__(self, key: object) -> bool:
        return key in self._classes

    def __len__(self) -> int:
        return len(self._classes)

    def __iter__(self):
        return iter(self._classes)

    def keys(self):
        return self._classes.keys()

    def values(self):
        return [self[k] for k in self._classes]

    def items(self):
        return [(k, self[k]) for k in self._classes]

    def get(self, key: AgentName, default=None):  # type: ignore[override]
        if key in self._classes:
            return self[key]
        return default
