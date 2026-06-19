"""Agent identity, capability and runtime-state contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentStatus(StrEnum):
    IDLE = "idle"
    BUSY = "busy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    FAILED = "failed"


class AgentCapability(StrEnum):
    ROUTING = "routing"
    ARCHITECTURE = "architecture"
    CODING = "coding"
    DEBUGGING = "debugging"
    ANALYSIS = "analysis"
    OPTIMIZATION = "optimization"
    DOCUMENTATION = "documentation"
    RESEARCH = "research"
    SUPERVISION = "supervision"
    META_REASONING = "meta_reasoning"
    MEMORY = "memory"
    COMMUNICATION = "communication"
    TESTING = "testing"
    SKILL_CREATION = "skill_creation"
    VALIDATION = "validation"
    DASHBOARD = "dashboard"


class AgentPermissionProfile(StrEnum):
    READ_ONLY = "read_only"
    WRITE_PROJECT = "write_project"
    TERMINAL_LIMITED = "terminal_limited"
    NETWORK_LIMITED = "network_limited"
    SANDBOX_EXECUTION = "sandbox_execution"
    HUMAN_APPROVED_PRIVILEGED = "human_approved_privileged"


class AgentRuntimeState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AgentStatus = AgentStatus.IDLE
    heartbeat_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    current_task_id: str | None = None
    load: float = Field(default=0.0, ge=0.0, le=1.0)
    health_score: float = Field(default=1.0, ge=0.0, le=1.0)
    failure_count: int = Field(default=0, ge=0)
    consecutive_failures: int = Field(default=0, ge=0)


class AgentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0", min_length=1)
    agent_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=500)
    version: str = Field(default="0.1.0", min_length=1, max_length=64)
    capabilities: list[AgentCapability] = Field(default_factory=list)
    supported_task_types: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    preferred_model: str = Field(min_length=1, max_length=128)
    fallback_models: list[str] = Field(default_factory=list)
    routing_cost: float = Field(default=1.0, ge=0.0)
    latency_budget_ms: int = Field(default=300_000, ge=1)
    confidence_baseline: float = Field(default=0.5, ge=0.0, le=1.0)
    reputation_score: float = Field(default=0.5, ge=0.0, le=1.0)
    failure_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    validation_requirements: list[str] = Field(default_factory=list)
    permission_profile: AgentPermissionProfile = AgentPermissionProfile.READ_ONLY
    sandbox_required: bool = False
    write_access: bool = False
    network_access: bool = False
    state: AgentRuntimeState = Field(default_factory=AgentRuntimeState)

    @field_validator("capabilities")
    @classmethod
    def capabilities_must_be_unique(cls, value: list[AgentCapability]) -> list[AgentCapability]:
        if len(value) != len(set(value)):
            raise ValueError("capabilities must be unique")
        return value

    @field_validator("supported_task_types", "allowed_tools", "fallback_models")
    @classmethod
    def string_lists_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("list values must be unique")
        return value
