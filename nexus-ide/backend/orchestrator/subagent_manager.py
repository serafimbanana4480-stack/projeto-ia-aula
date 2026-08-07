"""Subagent Manager — orchestrates subagent phases via AgentLifecycleManager.

Responsibilities:
- Spawns subagent phases through AgentLifecycleManager with per-phase budgets
- Fits large task contexts into each phase's context budget before spawning
- Retries transient failures with exponential backoff, up to the phase's limit
- Publishes lifecycle events to AgentBus topics (subagent.<phase>.complete/failed)
- Saves per-subagent checkpoints for crash recovery, keyed so they can be found

FOUR BEHAVIOURS THAT WERE MISSING

1. RETRIES. `SubagentPhaseConfig.max_retries` was declared, asserted in tests,
   and never read. RESEARCH claimed two retries and got zero; one flaky
   provider call failed the whole phase.

2. RESUMABLE CHECKPOINTS. Every call minted a fresh `uuid4()` subagent id and
   then looked up a checkpoint under that brand-new id, so `get_latest` could
   never return anything. The resume branch was unreachable code. Ids are now
   derived from (mission, phase, objective), which is what makes a re-run of
   the same work recognisable as the same work.

3. HONEST TOKEN ACCOUNTING. `tokens_used = len(str(output))` counted
   characters, overstating usage roughly fourfold and making every figure
   derived from it wrong.

4. CONTEXT BUDGETING. Context was forwarded verbatim however large it was.
   See `context_budget.py` for why that fails specifically on the large,
   detailed tasks subagents exist to handle.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.core.agent_bus import BusMessage, get_agent_bus
from backend.core.agent_lifecycle import AgentLifecycleManager
from backend.orchestrator.context_budget import (
    BudgetReport,
    estimate_tokens,
    fit_context,
    measure_context,
)
from backend.orchestrator.subagent_checkpoint import SubagentCheckpoint, SubagentCheckpointStore
from backend.orchestrator.subagent_registry import SubagentPhaseConfig, get_subagent_phase

logger = logging.getLogger(__name__)

#: Failures worth trying again: a provider hiccup, a dropped socket, a timeout.
#: Deliberately narrow — retrying a `ValueError` or a `TypeError` burns the
#: budget three times over on a bug that will reproduce identically.
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ConnectionError,
    OSError,
)


@dataclass
class SubagentResult:
    subagent_id: str
    phase: str
    success: bool
    output: Any = None
    error: str | None = None
    tokens_used: int = 0
    duration_seconds: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    retries: int = 0
    #: How the input context had to be reshaped to fit. `None` when no context
    #: was supplied. `report.degraded` tells a caller whether this phase
    #: answered on complete information or on a trimmed view of it.
    context_report: BudgetReport | None = None
    #: True when state from an earlier incomplete run was folded back in.
    resumed: bool = False


def derive_subagent_id(phase: str, objective: str, mission_id: str = "") -> str:
    """Stable id for a (mission, phase, objective) triple.

    Checkpoint recovery only works if the same logical unit of work maps to the
    same id across process restarts — which a random uuid, by construction,
    never does. Hashing the inputs keeps ids stable while staying short enough
    to read in a log line. A collision between genuinely different objectives
    is not a correctness problem: the worst case is an old context being merged
    in *behind* the fresh one, which the merge order already handles.
    """
    digest = hashlib.sha1(
        f"{mission_id}|{phase.upper()}|{objective}".encode(),
        usedforsecurity=False,
    ).hexdigest()[:10]
    return f"subagent-{phase.lower()}-{digest}"


class SubagentManager:
    """Manage subagent phases through AgentLifecycleManager + AgentBus."""

    def __init__(
        self,
        lifecycle: AgentLifecycleManager | None = None,
        bus: Any | None = None,
        checkpoint_store: SubagentCheckpointStore | None = None,
    ) -> None:
        if lifecycle is None:
            # Fail fast. The old fallback built an
            # `AgentLifecycleManager(registry=None, llm_client=None)`, so every
            # phase spawned against a null LLM client and failed silently
            # downstream. A manager without a lifecycle can never run a phase;
            # refuse to exist instead of pretending.
            raise ValueError(
                "SubagentManager requires an AgentLifecycleManager; "
                "construct one with a real registry and llm_client and inject it."
            )
        self._lifecycle = lifecycle
        self._bus = bus or get_agent_bus()
        self._checkpoints = checkpoint_store or SubagentCheckpointStore()
        self._results: dict[str, SubagentResult] = {}

    async def run_phase(
        self,
        phase: str,
        objective: str,
        context: dict[str, Any] | None = None,
        mission_id: str = "",
        fn: Callable[[], Awaitable[Any]] | None = None,
    ) -> SubagentResult:
        """Execute a single subagent phase, with budgeting and retries.

        Args:
            phase: One of RESEARCH, DESIGN, BUILD, VERIFY.
            objective: Task description for the phase.
            context: Optional state dict forwarded to the agent instance. Large
                contexts are fitted to the phase's `context_budget` rather than
                passed through; see `context_budget.fit_context`.
            mission_id: Parent mission identifier for grouping.
            fn: Optional async callable. When provided it is executed directly
                instead of the auto-resolved registry agent.

        Returns:
            SubagentResult describing the outcome, including how the context
            was budgeted and how many attempts were needed.
        """
        phase = phase.upper()
        cfg = get_subagent_phase(phase)
        if cfg is None:
            raise ValueError(f"Unknown subagent phase: {phase}")

        subagent_id = derive_subagent_id(phase, objective, mission_id)
        started_at = datetime.now(UTC)

        merged_context, resumed = self._merge_checkpoint(subagent_id, phase, context)

        # Size the phase to the work *before* budgeting it, so a large task
        # gets a proportionally larger allowance instead of being trimmed down
        # to a budget that was chosen for a small one.
        task_tokens = measure_context(merged_context) + estimate_tokens(objective)
        cfg = cfg.scaled_for(task_tokens)

        fitted_context, report = fit_context(
            merged_context,
            cfg.context_budget,
            priorities=cfg.context_priorities,
        )

        logger.info(
            "Subagent phase started | phase=%s id=%s mission=%s task_tokens=%d "
            "budget=%d degraded=%s resumed=%s",
            phase,
            subagent_id,
            mission_id,
            task_tokens,
            cfg.context_budget,
            report.degraded,
            resumed,
        )

        result = SubagentResult(
            subagent_id=subagent_id,
            phase=phase,
            success=False,
            started_at=started_at,
            context_report=report,
            resumed=resumed,
        )

        instance_id = await self._attempt_with_retries(
            cfg=cfg,
            objective=objective,
            context=fitted_context,
            mission_id=mission_id,
            fn=fn,
            result=result,
        )

        result.completed_at = datetime.now(UTC)
        result.duration_seconds = (result.completed_at - started_at).total_seconds()

        await self._publish(
            topic=cfg.bus_topic_complete if result.success else cfg.bus_topic_failed,
            subagent_id=subagent_id,
            instance_id=instance_id,
            phase=phase,
            success=result.success,
            output_preview=str(result.output)[:500] if result.output else "",
            error=result.error or "",
            duration_seconds=result.duration_seconds,
            retries=result.retries,
            context_degraded=report.degraded,
            priority=3 if result.success else 4,
        )

        self._save_checkpoint(
            subagent_id=subagent_id,
            phase=phase,
            instance_id=instance_id,
            objective=objective,
            context=fitted_context,
            mission_id=mission_id,
            result=result,
        )

        self._results[subagent_id] = result
        logger.info(
            "Subagent phase finished | phase=%s id=%s success=%s retries=%d tokens=%d",
            phase,
            subagent_id,
            result.success,
            result.retries,
            result.tokens_used,
        )
        return result

    # ── Execution ────────────────────────────────────────────────────────

    async def _attempt_with_retries(
        self,
        *,
        cfg: SubagentPhaseConfig,
        objective: str,
        context: dict[str, Any],
        mission_id: str,
        fn: Callable[[], Awaitable[Any]] | None,
        result: SubagentResult,
    ) -> str:
        """Run the phase, retrying transient failures. Returns the last id.

        Each attempt spawns a fresh lifecycle instance. Reusing one would mean
        a retry inherits the failed attempt's terminal state, so the second run
        would return the first run's error immediately without doing any work.
        """
        attempts = max(1, cfg.max_retries + 1)
        instance_id = ""

        for attempt in range(attempts):
            instance_id = await self._lifecycle.spawn(
                agent_type=cfg.agent_type,
                objective=objective,
                context=dict(context),
                mission_id=mission_id,
                token_budget=cfg.token_budget,
                time_budget_seconds=int(cfg.timeout),
            )

            try:
                if fn is not None:
                    output = await asyncio.wait_for(fn(), timeout=cfg.timeout)
                else:
                    # `_wait_for_agent` polls against its own deadline, so it
                    # needs no outer `wait_for`. Two nested timers on the same
                    # duration race, and the loser's cancellation surfaces as a
                    # confusing traceback rather than a clean timeout.
                    output = await self._wait_for_agent(instance_id, cfg.timeout)

                result.output = output
                result.success = True
                result.error = None
                # Tokens, not characters. `estimate_tokens` is the same
                # heuristic used to build the budget, so usage and budget are
                # at least measured on the same scale.
                result.tokens_used = estimate_tokens(output)

                status = self._lifecycle.get_status(instance_id)
                if status is not None:
                    status.context["output"] = output
                await self._lifecycle.complete(
                    instance_id, output=str(output), tokens_used=result.tokens_used
                )
                return instance_id

            except TimeoutError:
                # On 3.11+ `asyncio.TimeoutError` is an alias of the builtin,
                # so one clause covers `wait_for` and `_wait_for_agent` alike.
                error = f"Timeout after {cfg.timeout}s"
                await self._lifecycle.fail(instance_id, error=error)
                result.error = error
                logger.warning(
                    "Subagent attempt timed out | phase=%s attempt=%d/%d",
                    cfg.phase,
                    attempt + 1,
                    attempts,
                )
            except RETRYABLE_EXCEPTIONS as exc:
                await self._lifecycle.fail(instance_id, error=str(exc))
                result.error = str(exc)
                logger.warning(
                    "Subagent attempt failed (retryable) | phase=%s attempt=%d/%d error=%s",
                    cfg.phase,
                    attempt + 1,
                    attempts,
                    exc,
                )
            except Exception as exc:
                # Deterministic failure: a second identical attempt produces a
                # second identical failure, so stop and report.
                await self._lifecycle.fail(instance_id, error=str(exc))
                result.error = str(exc)
                logger.exception(
                    "Subagent phase failed (not retryable) | phase=%s error=%s", cfg.phase, exc
                )
                return instance_id

            if attempt < attempts - 1:
                result.retries += 1
                # Exponential backoff: a provider that just rate-limited is not
                # going to be ready again in the same millisecond.
                await asyncio.sleep(cfg.retry_backoff_seconds * (2**attempt))

        return instance_id

    async def _wait_for_agent(self, instance_id: str, timeout: float) -> Any:
        # Monotonic, not wall clock: an NTP correction mid-run must not make a
        # healthy agent look like it blew its deadline.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self._lifecycle.get_status(instance_id)
            if status is None:
                return ""
            if status.is_terminal():
                return status.context.get("output", "")
            await asyncio.sleep(0.05)
        raise TimeoutError(f"Agent instance {instance_id} did not complete within {timeout}s")

    # ── Checkpointing ────────────────────────────────────────────────────

    def _merge_checkpoint(
        self,
        subagent_id: str,
        phase: str,
        context: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], bool]:
        """Fold state from an earlier incomplete run into the new context.

        Fresh values win on key collisions: the caller knows the current world,
        the checkpoint only knows the world as it stood at the crash.
        """
        checkpoint = self._checkpoints.get_latest(subagent_id)
        if checkpoint is None or checkpoint.completed:
            return dict(context or {}), False

        logger.info("Resuming subagent from checkpoint | phase=%s id=%s", phase, subagent_id)
        merged: dict[str, Any] = dict(checkpoint.state.get("context", {}) or {})
        merged.update(context or {})
        return merged, True

    def _save_checkpoint(
        self,
        *,
        subagent_id: str,
        phase: str,
        instance_id: str,
        objective: str,
        context: dict[str, Any],
        mission_id: str,
        result: SubagentResult,
    ) -> None:
        checkpoint = SubagentCheckpoint(
            checkpoint_id=f"ckpt-{subagent_id}",
            subagent_id=subagent_id,
            phase=phase,
            state={
                "instance_id": instance_id,
                "objective": objective,
                "context": context,
                "mission_id": mission_id,
                "output": result.output,
                "error": result.error,
                "success": result.success,
                "tokens_used": result.tokens_used,
                "duration_seconds": result.duration_seconds,
                "retries": result.retries,
                "context_report": (
                    result.context_report.to_dict() if result.context_report else None
                ),
            },
            completed=result.success,
        )
        self._checkpoints.save(checkpoint)

    # ── Events ───────────────────────────────────────────────────────────

    async def _publish(
        self,
        *,
        topic: str,
        subagent_id: str,
        instance_id: str,
        phase: str,
        success: bool,
        output_preview: str = "",
        error: str = "",
        duration_seconds: float = 0.0,
        retries: int = 0,
        context_degraded: bool = False,
        priority: int = 3,
    ) -> None:
        payload: dict[str, Any] = {
            "subagent_id": subagent_id,
            "phase": phase,
            "instance_id": instance_id,
            "success": success,
            "retries": retries,
            "context_degraded": context_degraded,
        }
        if output_preview:
            payload["output_preview"] = output_preview
        if error:
            payload["error"] = error
        if duration_seconds:
            payload["duration_seconds"] = duration_seconds

        await self._bus.publish(
            topic,
            BusMessage(
                message_id=uuid.uuid4().hex[:16],
                topic=topic,
                source_agent="SUBAGENT_MANAGER",
                target_agents=[],
                payload=payload,
                priority=priority,
                ttl_seconds=3600,
            ),
        )

    # ── Introspection ────────────────────────────────────────────────────

    def get_result(self, subagent_id: str) -> SubagentResult | None:
        return self._results.get(subagent_id)

    def get_recent_results(self, limit: int = 50) -> list[dict[str, Any]]:
        """Most recent phase results, newest first — dashboard telemetry."""
        recent = sorted(self._results.values(), key=lambda r: r.started_at, reverse=True)[:limit]
        return [
            {
                "subagent_id": r.subagent_id,
                "phase": r.phase,
                "success": r.success,
                "error": r.error,
                "tokens_used": r.tokens_used,
                "duration_seconds": r.duration_seconds,
                "retries": r.retries,
                "resumed": r.resumed,
                "context_degraded": bool(r.context_report and r.context_report.degraded),
                "started_at": r.started_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in recent
        ]

    def get_stats(self) -> dict[str, Any]:
        total = len(self._results)
        successful = sum(1 for r in self._results.values() if r.success)
        retried = sum(1 for r in self._results.values() if r.retries > 0)
        degraded = sum(
            1
            for r in self._results.values()
            if r.context_report is not None and r.context_report.degraded
        )
        return {
            "total_subagents": total,
            "successful": successful,
            "failed": total - successful,
            "success_rate": successful / total if total > 0 else 0.0,
            "retried": retried,
            # A high degraded count means phase context budgets are too small
            # for the work being handed to them — a tuning signal that was
            # previously invisible.
            "context_degraded": degraded,
            "total_tokens": sum(r.tokens_used for r in self._results.values()),
        }
