"""Tests for versioned multi-agent contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.contracts import (
    A2AMessage,
    AgentCapability,
    AgentManifest,
    AgentPermissionProfile,
    MessagePriority,
    SkillManifest,
    SkillValidationRule,
    TaskType,
    ValidationResult,
    ValidationSeverity,
    ValidationStage,
)
from backend.contracts.a2a import canonical_payload_hash


class TestAgentManifest:
    def test_manifest_defaults_and_serialization(self) -> None:
        manifest = AgentManifest(
            agent_id="coder",
            name="CODER",
            role="Implements production-ready code",
            capabilities=[AgentCapability.CODING, AgentCapability.TESTING],
            supported_task_types=["coding", "testing"],
            allowed_tools=["read_file", "write_file"],
            preferred_model="qwen3-coder:30b",
            permission_profile=AgentPermissionProfile.WRITE_PROJECT,
            write_access=True,
        )

        dumped = manifest.model_dump()
        assert dumped["schema_version"] == "1.0"
        assert dumped["state"]["status"] == "idle"
        assert manifest.reputation_score == 0.5
        assert manifest.write_access is True

    def test_manifest_rejects_duplicate_capabilities(self) -> None:
        with pytest.raises(ValidationError, match="capabilities must be unique"):
            AgentManifest(
                agent_id="coder",
                name="CODER",
                role="Writes code",
                capabilities=[AgentCapability.CODING, AgentCapability.CODING],
                preferred_model="qwen3-coder:30b",
            )

    def test_manifest_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            AgentManifest(
                agent_id="coder",
                name="CODER",
                role="Writes code",
                preferred_model="qwen3-coder:30b",
                unknown=True,
            )


class TestA2AMessage:
    def test_message_populates_payload_hash(self) -> None:
        message = A2AMessage(
            message_id="msg-1",
            correlation_id="corr-1",
            source_agent="SUPERVISOR",
            target_agent="CODER",
            priority=MessagePriority.HIGH,
            task_type=TaskType.CODING,
            context_hash="ctx-123",
            payload={"task": "implement contracts", "risk": "low"},
            deadline=datetime.now(UTC) + timedelta(minutes=5),
            confidence_score=0.82,
        )

        assert message.payload_hash == canonical_payload_hash(message.payload)
        assert message.requires_validation is True
        assert message.retry_count == 0

    def test_message_rejects_payload_hash_mismatch(self) -> None:
        with pytest.raises(ValidationError, match="payload_hash does not match payload"):
            A2AMessage(
                message_id="msg-1",
                correlation_id="corr-1",
                source_agent="SUPERVISOR",
                target_agent="CODER",
                context_hash="ctx-123",
                payload={"task": "x"},
                payload_hash="invalid",
            )

    def test_message_rejects_past_deadline(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError, match="deadline must be after created_at"):
            A2AMessage(
                message_id="msg-1",
                correlation_id="corr-1",
                source_agent="SUPERVISOR",
                target_agent="CODER",
                context_hash="ctx-123",
                created_at=now,
                deadline=now - timedelta(seconds=1),
            )

    def test_message_rejects_duplicate_memory_refs(self) -> None:
        with pytest.raises(ValidationError, match="list values must be unique"):
            A2AMessage(
                message_id="msg-1",
                correlation_id="corr-1",
                source_agent="SUPERVISOR",
                target_agent="CODER",
                context_hash="ctx-123",
                memory_refs=["mem-1", "mem-1"],
            )


class TestValidationResult:
    def test_passed_validation_result(self) -> None:
        result = ValidationResult(
            validation_id="val-1",
            stage=ValidationStage.SECURITY,
            passed=True,
            severity=ValidationSeverity.INFO,
            subject_id="task-1",
            confidence_score=0.9,
        )

        assert result.passed is True
        assert result.stage == ValidationStage.SECURITY

    def test_failed_validation_requires_message(self) -> None:
        with pytest.raises(ValidationError, match="failed validation results require a message"):
            ValidationResult(
                validation_id="val-1",
                stage=ValidationStage.SYNTAX,
                passed=False,
                subject_id="task-1",
            )

    def test_passed_validation_cannot_be_critical(self) -> None:
        with pytest.raises(ValidationError, match="passed validation results cannot have critical"):
            ValidationResult(
                validation_id="val-1",
                stage=ValidationStage.SECURITY,
                passed=True,
                severity=ValidationSeverity.CRITICAL,
                subject_id="task-1",
            )


class TestSkillManifest:
    def test_skill_manifest_with_validation_rules(self) -> None:
        skill = SkillManifest(
            skill_id="fastapi-security",
            name="FastAPI Security",
            domain="backend",
            compatible_agents=["CODER", "ANALYZER"],
            required_tools=["read_file", "execute_code"],
            workflows=["audit endpoints", "add tests"],
            validation_rules=[
                SkillValidationRule(
                    name="Run backend tests",
                    description="Backend tests must pass before promoting this skill",
                    command="pytest backend/tests",
                )
            ],
        )

        assert skill.status == "draft"
        assert skill.validation_rules[0].required is True
        assert skill.confidence_score == 0.5

    def test_skill_manifest_rejects_duplicate_required_tools(self) -> None:
        with pytest.raises(ValidationError, match="list values must be unique"):
            SkillManifest(
                skill_id="testing",
                name="Testing",
                domain="quality",
                required_tools=["execute_code", "execute_code"],
            )
