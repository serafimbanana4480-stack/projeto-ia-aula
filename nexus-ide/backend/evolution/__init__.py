"""Self-Evolution Engine package.

Components:
    - ChampionRegistry: versioned component lifecycle (champion/challenger/etc.)
    - FailureMiner: classifies failures from traces into prioritised categories
    - Arena: runs champion-vs-challenger experiments
    - RegressionGuard: hard gates for promotion
    - Rollback: automatic revert on production degradation
    - EvolutionEngine: orchestrates the full evolution cycle
    - Evolvers: prompt, skill, workflow, tool, memory, code, model
    - SkillDiscovery: auto-discovers skills from trajectories
"""
from __future__ import annotations

from backend.evolution.arena import Arena, BenchmarkRunner
from backend.evolution.engine import EvolutionConfig, EvolutionEngine
from backend.evolution.evolvers import (
    BaseEvolver,
    Candidate,
    CodeEvolver,
    MemoryEvolver,
    ModelEvolver,
    PromptEvolver,
    SkillEvolver,
    ToolEvolver,
    WorkflowEvolver,
    get_all_evolvers,
    get_evolver,
)
from backend.evolution.failure_miner import FailureMiner
from backend.evolution.registry import (
    ChampionRegistry,
    ComponentStatus,
    ComponentVersion,
    EvolutionResult,
    Experiment,
    ExperimentStatus,
    FailureCategory,
    FailurePriority,
)
from backend.evolution.regression_guard import GateReport, GateResult, RegressionGuard
from backend.evolution.rollback import RollbackEvent, RollbackManager
from backend.evolution.skill_discovery import SkillDiscovery
from backend.evolution.skill_writer import SkillProposal, SkillWriter

__all__ = [
    "Arena",
    "BaseEvolver",
    "BenchmarkRunner",
    "Candidate",
    "ChampionRegistry",
    "CodeEvolver",
    "ComponentStatus",
    "ComponentVersion",
    "EvolutionConfig",
    "EvolutionEngine",
    "EvolutionResult",
    "Experiment",
    "ExperimentStatus",
    "FailureCategory",
    "FailureMiner",
    "FailurePriority",
    "GateReport",
    "GateResult",
    "MemoryEvolver",
    "ModelEvolver",
    "PromptEvolver",
    "RegressionGuard",
    "RollbackEvent",
    "RollbackManager",
    "SkillDiscovery",
    "SkillEvolver",
    "SkillProposal",
    "SkillWriter",
    "ToolEvolver",
    "WorkflowEvolver",
    "get_all_evolvers",
    "get_evolver",
]
