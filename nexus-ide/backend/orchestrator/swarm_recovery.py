"""Swarm Recovery Strategies — pre-defined recovery patterns for each failure category.

Applied automatically when signature matches known pattern.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RecoveryContext:
    objective: str
    session_id: str
    project_path: str = "."
    failed_agent: str = ""
    error_output: str = ""
    max_retries: int = 3
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryStep:
    action: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryResult:
    recovered: bool
    steps_executed: list[str] = field(default_factory=list)
    final_output: str = ""
    error: str | None = None


class SwarmRecoveryStrategies:
    """Pre-defined recovery patterns for each failure category."""

    RECOVERY_PLAYBOOKS = {
        "agent_timeout": [
            {"action": "retry_with_larger_budget", "params": {"token_multiplier": 2, "time_multiplier": 1.5}},
            {"action": "split_into_smaller_subtasks", "params": {"max_subtask_tokens": 8000}},
            {"action": "use_faster_model", "params": {"model_key": "fast"}},
        ],
        "tool_execution_failed": [
            {"action": "retry_with_debugger_first", "params": {}},
            {"action": "fallback_to_alternative_tool", "params": {}},
        ],
        "context_overflow": [
            {"action": "enable_context_compression", "params": {}},
            {"action": "split_into_smaller_subtasks", "params": {"max_subtask_tokens": 4000}},
        ],
        "contradiction_detected": [
            {"action": "run_debate_strategy_with_moderator", "params": {"moderator": "ANALYZER"}},
            {"action": "escalate_to_meta_analyzer", "params": {}},
        ],
        "synthesis_failed": [
            {"action": "retry_with_structured_output", "params": {}},
            {"action": "fallback_to_concatenation", "params": {}},
        ],
        "quality_gate_failed": [
            {"action": "run_fix_cycle", "params": {"max_iterations": 3}},
            {"action": "rollback_and_escalate", "params": {}},
        ],
        "resource_exhaustion": [
            {"action": "isolate_failing_agent", "params": {}},
            {"action": "retry_with_ensemble_for_redundancy", "params": {}},
            {"action": "fallback_to_single_agent", "params": {"agent": "CODER"}},
        ],
        "cascading_failure": [
            {"action": "isolate_failing_agent", "params": {}},
            {"action": "retry_with_ensemble_for_redundancy", "params": {}},
            {"action": "fallback_to_single_agent", "params": {"agent": "CODER"}},
        ],
    }

    async def execute_recovery(self, diagnosis: Any, context: RecoveryContext) -> RecoveryResult:
        category = getattr(diagnosis, "failure_category", "unknown")
        playbook = self.RECOVERY_PLAYBOOKS.get(category, [{"action": "escalate_to_meta_analyzer", "params": {}}])
        steps_executed: list[str] = []
        for step in playbook:
            result = await self._execute_step(step, context)
            steps_executed.append(step["action"])
            if result.recovered:
                return result
        return RecoveryResult(recovered=False, steps_executed=steps_executed, error="All recovery steps failed")

    async def _execute_step(self, step: RecoveryStep, context: RecoveryContext) -> RecoveryResult:
        action = step.get("action", "")
        params = step.get("params", {})
        try:
            if action == "retry_with_larger_budget":
                return await self._retry_with_larger_budget(context, params)
            if action == "split_into_smaller_subtasks":
                return await self._split_into_smaller_subtasks(context, params)
            if action == "use_faster_model":
                return await self._use_faster_model(context, params)
            if action == "retry_with_debugger_first":
                return await self._retry_with_debugger_first(context, params)
            if action == "enable_context_compression":
                return await self._enable_context_compression(context, params)
            if action == "run_debate_strategy_with_moderator":
                return await self._run_debate_strategy(context, params)
            if action == "escalate_to_meta_analyzer":
                return await self._escalate_to_meta_analyzer(context, params)
            if action == "run_fix_cycle":
                return await self._run_fix_cycle(context, params)
            if action == "rollback_and_escalate":
                return await self._rollback_and_escalate(context, params)
            if action == "isolate_failing_agent":
                return await self._isolate_failing_agent(context, params)
            if action == "fallback_to_single_agent":
                return await self._fallback_to_single_agent(context, params)
            if action == "retry_with_ensemble_for_redundancy":
                return await self._retry_with_ensemble(context, params)
            if action == "fallback_to_concatenation":
                return await self._fallback_to_concatenation(context, params)
            if action == "retry_with_structured_output":
                return await self._retry_with_structured_output(context, params)
        except Exception as exc:
            logger.exception("Recovery step %s failed: %s", action, exc)
        return RecoveryResult(recovered=False, steps_executed=[action])

    async def _retry_with_larger_budget(self, context: RecoveryContext, params: dict[str, Any]) -> RecoveryResult:
        return RecoveryResult(recovered=False, steps_executed=["retry_with_larger_budget"])

    async def _split_into_smaller_subtasks(self, context: RecoveryContext, params: dict[str, Any]) -> RecoveryResult:
        return RecoveryResult(recovered=False, steps_executed=["split_into_smaller_subtasks"])

    async def _use_faster_model(self, context: RecoveryContext, params: dict[str, Any]) -> RecoveryResult:
        return RecoveryResult(recovered=False, steps_executed=["use_faster_model"])

    async def _retry_with_debugger_first(self, context: RecoveryContext, params: dict[str, Any]) -> RecoveryResult:
        return RecoveryResult(recovered=False, steps_executed=["retry_with_debugger_first"])

    async def _enable_context_compression(self, context: RecoveryContext, params: dict[str, Any]) -> RecoveryResult:
        return RecoveryResult(recovered=False, steps_executed=["enable_context_compression"])

    async def _run_debate_strategy(self, context: RecoveryContext, params: dict[str, Any]) -> RecoveryResult:
        return RecoveryResult(recovered=False, steps_executed=["run_debate_strategy_with_moderator"])

    async def _escalate_to_meta_analyzer(self, context: RecoveryContext, params: dict[str, Any]) -> RecoveryResult:
        try:
            import uuid

            from backend.core.agent_bus import BusMessage, get_agent_bus
            bus = get_agent_bus()
            await bus.publish(
                "auto_correction.status",
                BusMessage(
                    message_id=f"recovery-{uuid.uuid4().hex[:12]}",
                    source_agent="SWARM_RECOVERY",
                    payload={
                        "action": "escalate",
                        "objective": context.objective,
                        "session_id": context.session_id,
                        "error": context.error_output,
                    },
                ),
            )
        except Exception:
            logger.debug("Escalation to META_ANALYZER failed", exc_info=True)
        return RecoveryResult(recovered=False, steps_executed=["escalate_to_meta_analyzer"])

    async def _run_fix_cycle(self, context: RecoveryContext, params: dict[str, Any]) -> RecoveryResult:
        return RecoveryResult(recovered=False, steps_executed=["run_fix_cycle"])

    async def _rollback_and_escalate(self, context: RecoveryContext, params: dict[str, Any]) -> RecoveryResult:
        return RecoveryResult(recovered=False, steps_executed=["rollback_and_escalate"])

    async def _isolate_failing_agent(self, context: RecoveryContext, params: dict[str, Any]) -> RecoveryResult:
        return RecoveryResult(recovered=False, steps_executed=["isolate_failing_agent"])

    async def _fallback_to_single_agent(self, context: RecoveryContext, params: dict[str, Any]) -> RecoveryResult:
        return RecoveryResult(recovered=False, steps_executed=["fallback_to_single_agent"])

    async def _retry_with_ensemble(self, context: RecoveryContext, params: dict[str, Any]) -> RecoveryResult:
        return RecoveryResult(recovered=False, steps_executed=["retry_with_ensemble_for_redundancy"])

    async def _fallback_to_concatenation(self, context: RecoveryContext, params: dict[str, Any]) -> RecoveryResult:
        return RecoveryResult(recovered=False, steps_executed=["fallback_to_concatenation"])

    async def _retry_with_structured_output(self, context: RecoveryContext, params: dict[str, Any]) -> RecoveryResult:
        return RecoveryResult(recovered=False, steps_executed=["retry_with_structured_output"])
