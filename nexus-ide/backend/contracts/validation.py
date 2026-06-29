"""Validation pipeline result contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ValidationStage(StrEnum):
    SYNTAX = "syntax"
    SEMANTIC = "semantic"
    ARCHITECTURE = "architecture"
    SECURITY = "security"
    PERFORMANCE = "performance"
    LOGIC = "logic"
    CONTEXT = "context"
    DEPENDENCY = "dependency"


class ValidationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0", min_length=1)
    validation_id: str = Field(min_length=1, max_length=128)
    stage: ValidationStage
    passed: bool
    severity: ValidationSeverity = ValidationSeverity.INFO
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    subject_id: str = Field(min_length=1, max_length=256)
    agent_id: str | None = Field(default=None, max_length=128)
    task_id: str | None = Field(default=None, max_length=128)
    message: str = Field(default="", max_length=2_000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    remediation: str = Field(default="", max_length=5_000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def failed_results_need_message(self) -> ValidationResult:
        if not self.passed and not self.message:
            raise ValueError("failed validation results require a message")
        return self

    @model_validator(mode="after")
    def critical_results_cannot_pass(self) -> ValidationResult:
        if self.passed and self.severity == ValidationSeverity.CRITICAL:
            raise ValueError("passed validation results cannot have critical severity")
        return self
