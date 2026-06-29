"""Reusable skill manifest contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SkillValidationRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1_000)
    command: str | None = Field(default=None, max_length=1_000)
    required: bool = True


class SkillStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


class SkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0", min_length=1)
    skill_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(default="0.1.0", min_length=1, max_length=64)
    domain: str = Field(min_length=1, max_length=128)
    status: SkillStatus = SkillStatus.DRAFT
    description: str = Field(default="", max_length=2_000)
    compatible_agents: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    templates: list[str] = Field(default_factory=list)
    best_practices: list[str] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)
    troubleshooting: list[str] = Field(default_factory=list)
    validation_rules: list[SkillValidationRule] = Field(default_factory=list)
    usage_count: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator(
        "compatible_agents",
        "required_tools",
        "workflows",
        "templates",
        "best_practices",
        "anti_patterns",
        "troubleshooting",
    )
    @classmethod
    def string_lists_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("list values must be unique")
        return value
