"""Agent-to-Agent protocol contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MessagePriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskType(StrEnum):
    ROUTING = "routing"
    PLANNING = "planning"
    CODING = "coding"
    DEBUGGING = "debugging"
    ANALYSIS = "analysis"
    OPTIMIZATION = "optimization"
    DOCUMENTATION = "documentation"
    RESEARCH = "research"
    VALIDATION = "validation"
    MEMORY = "memory"
    COMMUNICATION = "communication"
    TESTING = "testing"
    SUPERVISION = "supervision"
    SKILL_CREATION = "skill_creation"
    GENERAL = "general"


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


class A2AMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0", min_length=1)
    message_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    source_agent: str = Field(min_length=1, max_length=128)
    target_agent: str = Field(min_length=1, max_length=128)
    priority: MessagePriority = MessagePriority.MEDIUM
    task_type: TaskType = TaskType.GENERAL
    context_hash: str = Field(min_length=1, max_length=128)
    memory_refs: list[str] = Field(default_factory=list)
    requires_validation: bool = True
    deadline: datetime | None = None
    retry_count: int = Field(default=0, ge=0)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    parent_message_id: str | None = Field(default=None, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_hash: str = ""
    trace_id: str | None = Field(default=None, max_length=128)
    span_id: str | None = Field(default=None, max_length=128)
    permissions: list[str] = Field(default_factory=list)
    expected_response_schema: str | None = Field(default=None, max_length=256)
    ttl_seconds: int | None = Field(default=None, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("memory_refs", "permissions")
    @classmethod
    def string_lists_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("list values must be unique")
        return value

    @model_validator(mode="after")
    def populate_or_validate_payload_hash(self) -> A2AMessage:
        expected = canonical_payload_hash(self.payload)
        if not self.payload_hash:
            self.payload_hash = expected
            return self
        if self.payload_hash != expected:
            raise ValueError("payload_hash does not match payload")
        return self

    @model_validator(mode="after")
    def validate_deadline(self) -> A2AMessage:
        if self.deadline is not None and self.deadline <= self.created_at:
            raise ValueError("deadline must be after created_at")
        return self
