"""SWARM Operational Modes.

Each mode declares:
- objective
- the set of agents involved (in order)
- the workflow
- the expected output

Adding a new mode = adding one entry to ``OPERATIONAL_MODES``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.swarm.core.types import AgentRole, OperationalMode, SwarmStrategy, WorkflowState


@dataclass
class OperationalModeSpec:
    """A single mode's spec."""

    mode: OperationalMode
    label: str
    description: str
    objective: str
    agents: list[AgentRole]
    default_strategy: SwarmStrategy
    workflow: list[WorkflowState] = field(default_factory=list)
    max_iterations: int = 6
    requires_approval: bool = True
    uses_rag: bool = True
    uses_research: bool = False
    expected_output: str = ""


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

OPERATIONAL_MODES: dict[OperationalMode, OperationalModeSpec] = {
    OperationalMode.ARCHITECTURE: OperationalModeSpec(
        mode=OperationalMode.ARCHITECTURE,
        label="Architecture",
        description="Design system structure, evaluate trade-offs, emit ADRs.",
        objective="Produce an architectural design with rationale and decision record.",
        agents=[
            AgentRole.COORDINATOR,
            AgentRole.INVESTIGATOR,
            AgentRole.ARCHITECT,
            AgentRole.REVIEWER,
        ],
        default_strategy=SwarmStrategy.DEBATE,
        workflow=[
            WorkflowState.PROPOSED,
            WorkflowState.DISCUSSED,
            WorkflowState.VALIDATED,
            WorkflowState.COMPLETED,
        ],
        max_iterations=1000,
        uses_rag=True,
        uses_research=False,
        expected_output="Design summary + ADR + reviewed trade-offs.",
    ),
    OperationalMode.INVESTIGATION: OperationalModeSpec(
        mode=OperationalMode.INVESTIGATION,
        label="Investigation",
        description="Read the codebase via RAG, summarise what exists, surface constraints.",
        objective="Produce an evidence-backed report on the relevant code areas.",
        agents=[
            AgentRole.COORDINATOR,
            AgentRole.INVESTIGATOR,
            AgentRole.ARCHITECT,
        ],
        default_strategy=SwarmStrategy.ENSEMBLE,
        workflow=[WorkflowState.PROPOSED, WorkflowState.COMPLETED],
        max_iterations=4,
        uses_rag=True,
        uses_research=False,
        expected_output="Cited findings from the codebase with file paths and line ranges.",
    ),
    OperationalMode.IMPLEMENTATION: OperationalModeSpec(
        mode=OperationalMode.IMPLEMENTATION,
        label="Implementation",
        description="Plan and emit a proposal for code changes, with safe approval flow.",
        objective="Emit an APPROVED proposal ready for a human or CI to apply.",
        agents=[
            AgentRole.COORDINATOR,
            AgentRole.INVESTIGATOR,
            AgentRole.ARCHITECT,
            AgentRole.IMPLEMENTER,
            AgentRole.REVIEWER,
        ],
        default_strategy=SwarmStrategy.PIPELINE,
        workflow=[
            WorkflowState.PROPOSED,
            WorkflowState.DISCUSSED,
            WorkflowState.VALIDATED,
            WorkflowState.APPROVED,
            WorkflowState.IMPLEMENTING,
            WorkflowState.IMPLEMENTED,
            WorkflowState.REVIEWING,
            WorkflowState.COMPLETED,
        ],
        max_iterations=6,
        requires_approval=True,
        uses_rag=True,
        uses_research=False,
        expected_output="Approved proposal with file-level changes and a Reviewer verdict.",
    ),
    OperationalMode.REVIEW: OperationalModeSpec(
        mode=OperationalMode.REVIEW,
        label="Review",
        description="Independently review code or text and produce findings + scores.",
        objective="Produce a ReviewReport with findings, severity, and the 4 quality scores.",
        agents=[AgentRole.COORDINATOR, AgentRole.INVESTIGATOR, AgentRole.REVIEWER],
        default_strategy=SwarmStrategy.ENSEMBLE,
        workflow=[WorkflowState.PROPOSED, WorkflowState.COMPLETED],
        max_iterations=3,
        uses_rag=True,
        uses_research=False,
        expected_output="ReviewReport with 8-axis findings.",
    ),
    OperationalMode.BUGFIX: OperationalModeSpec(
        mode=OperationalMode.BUGFIX,
        label="Bugfix",
        description="Investigate → propose a fix → reviewer validates → approved patch.",
        objective="Produce a minimal, reviewed fix for a reported bug.",
        agents=[
            AgentRole.COORDINATOR,
            AgentRole.INVESTIGATOR,
            AgentRole.IMPLEMENTER,
            AgentRole.REVIEWER,
        ],
        default_strategy=SwarmStrategy.PIPELINE,
        workflow=[
            WorkflowState.PROPOSED,
            WorkflowState.VALIDATED,
            WorkflowState.APPROVED,
            WorkflowState.IMPLEMENTING,
            WorkflowState.IMPLEMENTED,
            WorkflowState.REVIEWING,
            WorkflowState.COMPLETED,
        ],
        max_iterations=1000,
        uses_rag=True,
        uses_research=False,
        expected_output="Approved fix proposal with cited root cause.",
    ),
    OperationalMode.PLANNING: OperationalModeSpec(
        mode=OperationalMode.PLANNING,
        label="Planning",
        description="Produce a structured execution plan, no code changes.",
        objective="Emit a multi-step plan with agents, dependencies, deliverables.",
        agents=[
            AgentRole.COORDINATOR,
            AgentRole.INVESTIGATOR,
            AgentRole.ARCHITECT,
        ],
        default_strategy=SwarmStrategy.DIVIDE,
        workflow=[WorkflowState.PROPOSED, WorkflowState.COMPLETED],
        max_iterations=4,
        uses_rag=True,
        uses_research=False,
        expected_output="Execution plan with steps, agents, dependencies.",
    ),
    OperationalMode.RESEARCH: OperationalModeSpec(
        mode=OperationalMode.RESEARCH,
        label="Research",
        description="External research with multiple authoritative sources.",
        objective="Produce a structured, source-cited research summary.",
        agents=[
            AgentRole.COORDINATOR,
            AgentRole.RESEARCHER,
            AgentRole.ARCHITECT,
        ],
        default_strategy=SwarmStrategy.ENSEMBLE,
        workflow=[WorkflowState.PROPOSED, WorkflowState.COMPLETED],
        max_iterations=4,
        uses_rag=False,
        uses_research=True,
        expected_output="Multi-source research summary with citations.",
    ),
}


def get_mode(mode: OperationalMode) -> OperationalModeSpec:
    if mode not in OPERATIONAL_MODES:
        raise KeyError(f"Unknown operational mode: {mode!r}")
    return OPERATIONAL_MODES[mode]


def all_modes() -> list[OperationalModeSpec]:
    return list(OPERATIONAL_MODES.values())


def to_dict() -> dict[str, dict[str, Any]]:
    """Serialise all modes for the API."""
    out: dict[str, dict[str, Any]] = {}
    for mode, spec in OPERATIONAL_MODES.items():
        out[mode.value] = {
            "label": spec.label,
            "description": spec.description,
            "objective": spec.objective,
            "agents": [a.value for a in spec.agents],
            "default_strategy": spec.default_strategy.value,
            "workflow": [s.value for s in spec.workflow],
            "max_iterations": spec.max_iterations,
            "requires_approval": spec.requires_approval,
            "uses_rag": spec.uses_rag,
            "uses_research": spec.uses_research,
            "expected_output": spec.expected_output,
        }
    return out


__all__ = [
    "OperationalModeSpec",
    "OPERATIONAL_MODES",
    "get_mode",
    "all_modes",
    "to_dict",
]
