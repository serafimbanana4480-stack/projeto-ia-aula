"""Specialized NEXUS agents.

One module per agent. All agents subclass `AgentBase` (see `base.py`).
"""

from backend.agents.architect_complexity import ArchitectComplexityAgent
from backend.agents.architect_design import ArchitectDesignAgent
from backend.agents.bug_hunter_runtime import BugHunterRuntimeAgent
from backend.agents.bug_hunter_static import BugHunterStaticAgent
from backend.agents.meta_analyzer import MetaAnalyzerAgent
from backend.agents.refactor_clean import RefactorCleanAgent
from backend.agents.refactor_performance import RefactorPerformanceAgent
from backend.agents.researcher_web import ResearcherWebAgent
from backend.agents.test_runner_e2e import TestRunnerE2EAgent
from backend.agents.test_runner_unit import TestRunnerUnitAgent

__all__ = [
    "ArchitectComplexityAgent",
    "ArchitectDesignAgent",
    "BugHunterRuntimeAgent",
    "BugHunterStaticAgent",
    "MetaAnalyzerAgent",
    "RefactorCleanAgent",
    "RefactorPerformanceAgent",
    "ResearcherWebAgent",
    "TestRunnerE2EAgent",
    "TestRunnerUnitAgent",
]
