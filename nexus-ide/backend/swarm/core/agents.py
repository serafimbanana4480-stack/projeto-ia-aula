"""SWARM agent definitions — each role's objective, responsibilities, contracts.

The 6 roles are mapped to underlying NEXUS agents in :mod:`backend.agents`.
Adding a new role = adding one entry here and one mapping in ``AGENT_BINDINGS``.
"""

from __future__ import annotations

from backend.swarm.core.types import (
    AgentDefinition,
    AgentRole,
    MessageType,
)

# ---------------------------------------------------------------------------
# Agent contract catalogue
# ---------------------------------------------------------------------------

AGENT_DEFINITIONS: dict[AgentRole, AgentDefinition] = {
    AgentRole.COORDINATOR: AgentDefinition(
        role=AgentRole.COORDINATOR,
        label="Coordinator",
        objective=(
            "Decompose the user objective, select the operational mode, dispatch "
            "tasks to the right agents, manage state, and synthesise the final answer."
        ),
        responsibilities=[
            "Detect the appropriate operational mode from the objective",
            "Break down the objective into a sequence of agent tasks",
            "Pass relevant context (RAG evidence, prior decisions) to each agent",
            "Resolve conflicts between agents",
            "Detect and break infinite loops",
            "Compute the final quality scores",
        ],
        limitations=[
            "Cannot read source files directly — must request from INVESTIGATOR",
            "Cannot write code — must request from IMPLEMENTER",
            "Cannot perform external research — must request from RESEARCHER",
        ],
        input_messages=[MessageType.REQUEST, MessageType.RESPONSE, MessageType.STATUS],
        output_messages=[
            MessageType.REQUEST,
            MessageType.PROPOSAL,
            MessageType.STATUS,
            MessageType.RESPONSE,
        ],
        memory_layers=["short_term", "decision", "architecture"],
        maps_to="ARCHITECT",  # closest underlying agent for fallback
    ),
    AgentRole.ARCHITECT: AgentDefinition(
        role=AgentRole.ARCHITECT,
        label="Architect",
        objective=(
            "Produce architectural designs, propose system structure, evaluate "
            "trade-offs, and select the best option with clear rationale."
        ),
        responsibilities=[
            "Design module structure and data flow",
            "Evaluate alternatives and produce a decision record",
            "Surface risks and constraints",
            "Produce architecture-decision records (ADRs)",
        ],
        limitations=[
            "Does not write code",
            "Does not perform external research",
            "Does not change files",
        ],
        input_messages=[MessageType.REQUEST, MessageType.EVIDENCE, MessageType.RESEARCH],
        output_messages=[MessageType.RESPONSE, MessageType.PROPOSAL, MessageType.EVIDENCE],
        memory_layers=["decision", "architecture", "long_term"],
        maps_to="ARCHITECT",
    ),
    AgentRole.RESEARCHER: AgentDefinition(
        role=AgentRole.RESEARCHER,
        label="Researcher",
        objective=(
            "Gather authoritative external information — official docs, APIs, "
            "library references, best practices — and produce a structured summary."
        ),
        responsibilities=[
            "Query multiple sources (≥2) for any non-trivial claim",
            "Prefer official sources (docs, GitHub, MDN, library references)",
            "Quote URLs and snippets",
            "Produce a confidence-tagged summary",
        ],
        limitations=[
            "Does not write code",
            "Does not change files",
            "Does not modify the codebase",
        ],
        input_messages=[MessageType.REQUEST],
        output_messages=[MessageType.RESEARCH, MessageType.EVIDENCE],
        memory_layers=["long_term", "project"],
        maps_to="RESEARCHER",
    ),
    AgentRole.INVESTIGATOR: AgentDefinition(
        role=AgentRole.INVESTIGATOR,
        label="Investigator",
        objective=(
            "Read the local codebase via RAG, summarise what exists, locate the "
            "specific files/symbols relevant to the objective, and surface constraints."
        ),
        responsibilities=[
            "Run hybrid RAG queries (semantic + keyword)",
            "Return cited file paths and line ranges",
            "Identify integration points and side-effects",
            "Surface existing tests and conventions",
        ],
        limitations=[
            "Does not write code",
            "Does not change files",
            "Does not perform external research",
        ],
        input_messages=[MessageType.REQUEST],
        output_messages=[MessageType.EVIDENCE, MessageType.RESPONSE],
        memory_layers=["short_term", "long_term", "project"],
        maps_to="ANALYZER",
    ),
    AgentRole.IMPLEMENTER: AgentDefinition(
        role=AgentRole.IMPLEMENTER,
        label="Implementer",
        objective=(
            "Produce a concrete implementation plan as a Proposal. Never write to "
            "disk until the proposal has been validated and approved."
        ),
        responsibilities=[
            "Emit a Proposal with explicit file-level changes",
            "Justify each change with cited evidence/decisions",
            "Stay within the agreed score thresholds",
            "Run only after APPROVAL — never autonomously",
        ],
        limitations=[
            "Cannot write files without APPROVAL",
            "Cannot decide architecture alone (must cite Architect decisions)",
            "Cannot claim evidence that was not provided",
        ],
        input_messages=[
            MessageType.REQUEST,
            MessageType.EVIDENCE,
            MessageType.APPROVAL,
            MessageType.REJECTION,
        ],
        output_messages=[MessageType.PROPOSAL, MessageType.STATUS, MessageType.RESPONSE],
        memory_layers=["short_term", "decision", "project"],
        maps_to="CODER",
    ),
    AgentRole.REVIEWER: AgentDefinition(
        role=AgentRole.REVIEWER,
        label="Reviewer",
        objective=(
            "Independently inspect proposals and outputs for bugs, security issues, "
            "performance, style, tests, and architectural consistency. Score the four "
            "quality axes (quality, confidence, risk, complexity)."
        ),
        responsibilities=[
            "Run static checks (read files referenced by the proposal)",
            "Surface findings categorised by severity",
            "Compute QualityScores",
            "Produce a review report attached to the proposal",
        ],
        limitations=[
            "Cannot write code",
            "Cannot change files",
            "Cannot approve a proposal — only COORDINATOR approves",
        ],
        input_messages=[MessageType.PROPOSAL, MessageType.RESPONSE, MessageType.EVIDENCE],
        output_messages=[MessageType.REVIEW, MessageType.REJECTION, MessageType.APPROVAL],
        memory_layers=["decision", "architecture", "long_term"],
        maps_to="REVIEWER",
    ),
}


# Mapping SWARM role → underlying NEXUS agent name (used by orchestrator)
AGENT_BINDINGS: dict[AgentRole, str] = {
    role: defn.maps_to for role, defn in AGENT_DEFINITIONS.items()
}


def get_definition(role: AgentRole) -> AgentDefinition:
    """Return the definition for a role, raising if unknown."""
    if role not in AGENT_DEFINITIONS:
        raise KeyError(f"Unknown SWARM agent role: {role!r}")
    return AGENT_DEFINITIONS[role]


def all_roles() -> list[AgentRole]:
    """Return all defined roles in a stable order."""
    return list(AGENT_DEFINITIONS.keys())


__all__ = ["AGENT_DEFINITIONS", "AGENT_BINDINGS", "get_definition", "all_roles"]
