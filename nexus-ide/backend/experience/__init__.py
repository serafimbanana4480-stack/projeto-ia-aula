"""NEXUS IDE Experience Bus & Trace Lake.

FASE 2 — Every interaction is captured as a structured :class:`ExperienceTrace`.
FASE 3 — Traces are persisted in a searchable :class:`TraceLake`.

The Experience Bus is the central nervous system for self-evolution: it
collects structured traces, publishes them to the EventBus, and persists
them to the TraceLake for later analysis by the Evolution Engine.

Typical flow::

    USER → DASHBOARD → API → ORCHESTRATOR → ROUTER → PLANNER → AGENTS
         → TOOLS → EXECUTION → OBSERVATIONS → MEMORY → VERIFIER → RESULT
         → EXPERIENCE BUS (capture) → TRACE LAKE (store) → EVOLUTION ENGINE
"""
from __future__ import annotations

from backend.experience.bus import ExperienceBus, get_experience_bus
from backend.experience.lake import TraceLake, get_trace_lake
from backend.experience.models import (
    ComponentKind,
    ExperienceTrace,
    ModelInfo,
    TaskCategory,
    TraceEvaluation,
    TraceMetrics,
    TraceResult,
    TrajectoryEntry,
)

__all__ = [
    "ExperienceBus",
    "TraceLake",
    "ExperienceTrace",
    "TrajectoryEntry",
    "ModelInfo",
    "TraceResult",
    "TraceMetrics",
    "TraceEvaluation",
    "TaskCategory",
    "ComponentKind",
    "get_experience_bus",
    "get_trace_lake",
]
