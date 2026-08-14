"""NEXUS primary-agent runtime.

A single persistent agent owns the task from start to finish, uses tools
directly, and delegates only when delegation demonstrably wins. The modules
here are deliberately small and dependency-light so the runtime can be
tested without a provider, a database, or a browser.
"""

from backend.runtime.events import (
    RunEventStream,
    RuntimeEvent,
    RuntimeEventType,
    dedupe_and_order,
)
from backend.runtime.scheduler import (
    RuntimeScheduler,
    RuntimeTask,
    RuntimeTaskStatus,
    SchedulerReport,
)
from backend.runtime.spawn_policy import (
    SpawnDecision,
    SpawnPolicy,
    SpawnVerdict,
    SubagentProposal,
)
from backend.runtime.telemetry import (
    BlockedOn,
    ProgressReport,
    RunPhase,
    RunTelemetry,
)

__all__ = [
    "BlockedOn",
    "ProgressReport",
    "RunEventStream",
    "RunPhase",
    "RunTelemetry",
    "RuntimeEvent",
    "RuntimeEventType",
    "RuntimeScheduler",
    "RuntimeTask",
    "RuntimeTaskStatus",
    "SchedulerReport",
    "SpawnDecision",
    "SpawnPolicy",
    "SpawnVerdict",
    "SubagentProposal",
    "dedupe_and_order",
]

from backend.runtime.primary import (  # noqa: E402  (re-export after base modules)
    AgentSignal,
    AgentSignalKind,
    Observation,
    PrimaryLoop,
    PrimaryOutcome,
    PrimaryPhase,
    PrimaryTurn,
    SteeringChannel,
    VerificationRequest,
    VerificationResult,
)
from backend.runtime.triage import (  # noqa: E402
    RequestClass,
    TriageDecision,
    triage_request,
)

__all__ += [
    "AgentSignal",
    "AgentSignalKind",
    "Observation",
    "PrimaryLoop",
    "PrimaryOutcome",
    "PrimaryPhase",
    "PrimaryTurn",
    "RequestClass",
    "SteeringChannel",
    "TriageDecision",
    "VerificationRequest",
    "VerificationResult",
    "triage_request",
]
