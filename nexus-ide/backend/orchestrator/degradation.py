"""Graceful degradation and escalation system for agent failures."""
from __future__ import annotations

import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from backend.observability.workflow_tracker import WorkflowTracker
from backend.orchestrator.events import EventBus, EventType, OrchestratorEvent

logger = logging.getLogger(__name__)


class AgentType(str, Enum):
    SPECIALIZED = "specialized"
    GENERAL = "general"
    FALLBACK = "fallback"


class EscalationLevel(str, Enum):
    NONE = "none"
    MONITOR = "monitor"
    REVIEW = "review"
    INTERVENTION = "intervention"


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay_ms: int = 1000
    max_delay_ms: int = 30000
    backoff_multiplier: float = 2.0
    jitter_ratio: float = 0.1
    retryable_errors: set[str] = field(default_factory=lambda: {
        "timeout", "connection_error", "rate_limit", "temporary_failure",
    })


@dataclass
class FallbackAttempt:
    attempt_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    agent_name: str = ""
    agent_type: AgentType = AgentType.SPECIALIZED
    timestamp: float = field(default_factory=time.time)
    error: str = ""
    success: bool = False
    duration_ms: float = 0.0


@dataclass
class DegradationPath:
    step_id: str = ""
    workflow_id: str = ""
    original_agent: str = ""
    attempts: list[FallbackAttempt] = field(default_factory=list)
    final_agent: str = ""
    final_status: str = "pending"
    escalation_level: EscalationLevel = EscalationLevel.NONE
    escalation_reason: str = ""
    started_at: float = field(default_factory=time.time)
    completed_at: float = 0.0


@dataclass
class EscalationEvent:
    escalation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    workflow_id: str = ""
    step_id: str = ""
    level: EscalationLevel = EscalationLevel.NONE
    reason: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    requires_action: bool = False


class DegradationManager:
    SPECIALIZED_AGENTS = {
        "ARCHITECT", "CODER", "DEBUGGER", "TESTER", "REVIEWER",
        "OPTIMIZER", "RESEARCHER", "DOCUMENTER"
    }
    GENERAL_AGENTS = {"MICRO", "FAST", "SMALL", "MEDIUM"}
    FALLBACK_AGENTS = {"NANO"}

    def __init__(
        self,
        event_bus: EventBus,
        workflow_tracker: WorkflowTracker,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._bus = event_bus
        self._tracker = workflow_tracker
        self._retry_policy = retry_policy or RetryPolicy()
        self._active_paths: dict[str, DegradationPath] = {}
        self._escalation_count = 0

    async def _publish_event(self, event_type: str, payload: dict[str, Any]) -> None:
        await self._bus.publish(OrchestratorEvent(
            event_type=EventType(event_type),
            source="degradation_manager",
            data=payload,
        ))

    def classify_agent(self, agent_name: str) -> AgentType:
        if agent_name in self.SPECIALIZED_AGENTS:
            return AgentType.SPECIALIZED
        elif agent_name in self.GENERAL_AGENTS:
            return AgentType.GENERAL
        else:
            return AgentType.FALLBACK

    def get_fallback_chain(self, agent_name: str) -> list[str]:
        agent_type = self.classify_agent(agent_name)
        if agent_type == AgentType.SPECIALIZED:
            specialized = list(self.SPECIALIZED_AGENTS - {agent_name})
            general = list(self.GENERAL_AGENTS)
            fallback = list(self.FALLBACK_AGENTS)
            return specialized + general + fallback
        elif agent_type == AgentType.GENERAL:
            general = list(self.GENERAL_AGENTS - {agent_name})
            fallback = list(self.FALLBACK_AGENTS)
            return general + fallback
        else:
            return []

    def _is_retryable_error(self, error_msg: str) -> bool:
        error_lower = error_msg.lower()
        return any(retryable in error_lower for retryable in self._retry_policy.retryable_errors)

    def _calculate_backoff_delay(self, attempt: int) -> int:
        delay_ms = self._retry_policy.base_delay_ms * (
            self._retry_policy.backoff_multiplier ** (attempt - 1)
        )
        delay_ms = min(delay_ms, self._retry_policy.max_delay_ms)
        jitter_ms = delay_ms * self._retry_policy.jitter_ratio
        jitter = random.uniform(-jitter_ms, jitter_ms)
        return int(max(0, delay_ms + jitter))

    def get_escalation_stats(self) -> dict[str, Any]:
        return {
            "total_escalations": self._escalation_count,
            "active_degradation_paths": len(self._active_paths),
        }

    def clear_degradation_path(self, step_id: str) -> None:
        if step_id in self._active_paths:
            del self._active_paths[step_id]
