"""Single source of truth mapping :class:`AgentName` → :class:`AgentBase` instance.

The registry is constructed once at process startup and reused across requests.
Tests can inject a custom registry via :func:`set_registry`.
"""

from __future__ import annotations

from collections.abc import Mapping

from backend.agents.analyzer import AnalyzerAgent
from backend.agents.architect import ArchitectAgent
from backend.agents.architect_complexity import ArchitectComplexityAgent
from backend.agents.architect_design import ArchitectDesignAgent
from backend.agents.base import AgentBase
from backend.agents.bug_hunter_runtime import BugHunterRuntimeAgent
from backend.agents.bug_hunter_static import BugHunterStaticAgent
from backend.agents.coder import CoderAgent
from backend.agents.dashboard_agent import DashboardAgent
from backend.agents.debugger import DebuggerAgent
from backend.agents.documenter import DocumenterAgent
from backend.agents.micro import MicroAgent
from backend.agents.optimizer import OptimizerAgent
from backend.agents.refactor_clean import RefactorCleanAgent
from backend.agents.refactor_performance import RefactorPerformanceAgent
from backend.agents.researcher import ResearcherAgent
from backend.agents.test_runner_e2e import TestRunnerE2EAgent
from backend.agents.test_runner_unit import TestRunnerUnitAgent
from backend.agents.guardian import NexusGuardianAgent
from backend.agents.meta_analyzer import MetaAnalyzerAgent
from backend.agents.overseer import OverseerAgent
from backend.agents.supervisor import SupervisorAgent
from backend.models.api import AgentName

AgentRegistry = Mapping[AgentName, AgentBase]


def build_default_registry() -> dict[AgentName, AgentBase]:
    """Construct the standard set of agents. Call once at app startup."""
    return {
        "ARCHITECT": ArchitectAgent(),
        "ARCHITECT_DESIGN": ArchitectDesignAgent(),
        "ARCHITECT_COMPLEXITY": ArchitectComplexityAgent(),
        "RESEARCHER": ResearcherAgent(),
        "CODER": CoderAgent(),
        "ANALYZER": AnalyzerAgent(),
        "DEBUGGER": DebuggerAgent(),
        "DOCUMENTER": DocumenterAgent(),
        "OPTIMIZER": OptimizerAgent(),
        "REFACTOR_PERFORMANCE": RefactorPerformanceAgent(),
        "REFACTOR_CLEAN": RefactorCleanAgent(),
        "MICRO": MicroAgent(),
        "DASHBOARD": DashboardAgent(),
        "SUPERVISOR": SupervisorAgent(),
        "GUARDIAN": NexusGuardianAgent(),
        "TEST_RUNNER_UNIT": TestRunnerUnitAgent(),
        "TEST_RUNNER_E2E": TestRunnerE2EAgent(),
        "BUG_HUNTER_STATIC": BugHunterStaticAgent(),
        "BUG_HUNTER_RUNTIME": BugHunterRuntimeAgent(),
        "META_ANALYZER": MetaAnalyzerAgent(),
    }


def resolve(registry: AgentRegistry, name: AgentName) -> AgentBase:
    """Return the agent for ``name`` or fall back to CODER.

    ROUTER is never user-invocable; route it to CODER so the
    system still produces useful output instead of 500-ing.
    DASHBOARD is invocable for metrics queries.
    """
    if name in registry:
        return registry[name]
    return registry["CODER"]
