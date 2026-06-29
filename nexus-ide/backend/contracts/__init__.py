"""Versioned multi-agent contracts for NEXUS IDE."""

from backend.contracts.a2a import A2AMessage, MessagePriority, TaskType
from backend.contracts.agent import (
    AgentCapability,
    AgentManifest,
    AgentPermissionProfile,
    AgentRuntimeState,
    AgentStatus,
)
from backend.contracts.skills import SkillManifest, SkillValidationRule
from backend.contracts.validation import ValidationResult, ValidationSeverity, ValidationStage

__all__ = [
    "A2AMessage",
    "AgentCapability",
    "AgentManifest",
    "AgentPermissionProfile",
    "AgentRuntimeState",
    "AgentStatus",
    "MessagePriority",
    "SkillManifest",
    "SkillValidationRule",
    "TaskType",
    "ValidationResult",
    "ValidationSeverity",
    "ValidationStage",
]
