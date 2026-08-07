"""Subagent Runner — DEPRECATED, kept for backwards compatibility only.

**Do not use for new code.** Use `subagent_manager.SubagentManager` instead.
This module coexisted with the manager as a second, divergent subagent
system (its own `SubagentResult` dataclass with different fields, its own
retry logic, no checkpoints, no lifecycle integration, no bus events). The
only production instantiation was in `autonomous_improvement_orchestrator`,
where it was created and never called. It remains importable so existing
tests and introspection callers keep working, but it emits a
`DeprecationWarning` on construction.

Historical docstring follows.

Subagents:
- RESEARCH: analyzes codebase, extracts patterns, consults KB
- DESIGN: proposes improvements, validates with PreFlight
- BUILD: applies changes via healer or swarm
- VERIFY: runs quality gates, decides rollback or commit

Each subagent runs as an asyncio.Task with:
- Isolated token budget, taken from `subagent_registry`
- Individual timeout
- Retry with exponential backoff for transient failures
- Failure isolation (one failing agent doesn't block others)

BUDGETS COME FROM THE REGISTRY

This module used to carry its own `SUBAGENTS` dict duplicating every number in
`subagent_registry.SUBAGENT_PHASES`. Both copies happened to agree, which is
the dangerous state for duplicated configuration: it looks correct right up
until someone tunes one of them and a phase quietly behaves differently
depending on which entry point launched it. `budget_for_phase` now reads the
registry, and `SUBAGENTS` is retained only as a read-only view for callers that
still introspect it.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.orchestrator.context_budget import estimate_tokens
from backend.orchestrator.subagent_registry import SUBAGENT_PHASES

logger = logging.getLogger(__name__)

#: Same narrow set the manager retries on. A deterministic bug re-run three
#: times is three times the cost and the same failure.
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ConnectionError,
    OSError,
)


@dataclass
class SubagentResult:
    subagent_id: str
    name: str
    success: bool
    output: Any
    error: str | None = None
    tokens_used: int = 0
    duration_seconds: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    retries: int = 0


@dataclass
class SubagentBudget:
    max_tokens: int = 4000
    max_seconds: float = 60.0
    max_retries: int = 1
    retry_backoff_seconds: float = 1.0


def budget_for_phase(name: str) -> SubagentBudget:
    """Resolve a phase's budget from the registry, with a safe default."""
    cfg = SUBAGENT_PHASES.get(name.upper())
    if cfg is None:
        return SubagentBudget()
    return SubagentBudget(
        max_tokens=cfg.token_budget,
        max_seconds=cfg.timeout,
        max_retries=cfg.max_retries,
        retry_backoff_seconds=cfg.retry_backoff_seconds,
    )


class SubagentRunner:
    """Executes specialized subagents with isolated budgets."""

    #: Read-only projection of the registry, kept for backwards compatibility
    #: with callers that inspect `SubagentRunner.SUBAGENTS`. Do not edit —
    #: change `subagent_registry.SUBAGENT_PHASES` instead.
    SUBAGENTS: dict[str, dict[str, Any]] = {
        phase: {
            "timeout": cfg.timeout,
            "tokens": cfg.token_budget,
            "retries": cfg.max_retries,
        }
        for phase, cfg in SUBAGENT_PHASES.items()
    }

    def __init__(self, llm_client: Any | None = None, registry: Any | None = None) -> None:
        warnings.warn(
            "SubagentRunner is deprecated; use SubagentManager "
            "(backend.orchestrator.subagent_manager) for all subagent execution.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.llm_client = llm_client
        self.registry = registry
        self._results: list[SubagentResult] = []

    async def run_subagent(
        self,
        name: str,
        fn: Any,
        budget: SubagentBudget | None = None,
    ) -> SubagentResult:
        """Run one subagent, retrying transient failures within its budget."""
        budget = budget or SubagentBudget()
        subagent_id = f"subagent-{name.lower()}-{uuid.uuid4().hex[:8]}"
        started_at = datetime.now(UTC)
        attempts = max(1, budget.max_retries + 1)
        retries = 0
        last_error = "unknown error"

        logger.info("Subagent started | name=%s id=%s attempts=%d", name, subagent_id, attempts)

        for attempt in range(attempts):
            try:
                output = await asyncio.wait_for(fn(), timeout=budget.max_seconds)
                completed_at = datetime.now(UTC)
                return SubagentResult(
                    subagent_id=subagent_id,
                    name=name,
                    success=True,
                    output=output,
                    # Measured from the output, not assumed from the budget.
                    # Reporting `budget.max_tokens` as consumption made every
                    # aggregate over these results meaningless — a subagent
                    # that returned one word "used" its entire allowance.
                    tokens_used=estimate_tokens(output),
                    duration_seconds=(completed_at - started_at).total_seconds(),
                    started_at=started_at,
                    completed_at=completed_at,
                    retries=retries,
                )
            except TimeoutError:
                # On 3.11+ `asyncio.TimeoutError` is an alias of the builtin,
                # so one clause covers `wait_for` and any provider timeout.
                last_error = f"Timeout after {budget.max_seconds}s"
                logger.warning(
                    "Subagent timeout | name=%s attempt=%d/%d timeout=%.1fs",
                    name,
                    attempt + 1,
                    attempts,
                    budget.max_seconds,
                )
            except RETRYABLE_EXCEPTIONS as exc:
                last_error = str(exc)
                logger.warning(
                    "Subagent failed (retryable) | name=%s attempt=%d/%d error=%s",
                    name,
                    attempt + 1,
                    attempts,
                    exc,
                )
            except Exception as exc:
                logger.exception("Subagent failed (not retryable) | name=%s error=%s", name, exc)
                completed_at = datetime.now(UTC)
                return SubagentResult(
                    subagent_id=subagent_id,
                    name=name,
                    success=False,
                    output=None,
                    error=str(exc),
                    tokens_used=0,
                    duration_seconds=(completed_at - started_at).total_seconds(),
                    started_at=started_at,
                    completed_at=completed_at,
                    retries=retries,
                )

            if attempt < attempts - 1:
                retries += 1
                await asyncio.sleep(budget.retry_backoff_seconds * (2**attempt))

        completed_at = datetime.now(UTC)
        return SubagentResult(
            subagent_id=subagent_id,
            name=name,
            success=False,
            output=None,
            error=last_error,
            tokens_used=0,
            duration_seconds=(completed_at - started_at).total_seconds(),
            started_at=started_at,
            completed_at=completed_at,
            retries=retries,
        )

    async def run_parallel(self, tasks: dict[str, Any]) -> dict[str, SubagentResult]:
        """Run several subagents concurrently; one failure never blocks the rest."""
        results: dict[str, SubagentResult] = {}
        coros = {
            name: self.run_subagent(name, fn, budget_for_phase(name))
            for name, fn in tasks.items()
        }

        raw = await asyncio.gather(*coros.values(), return_exceptions=True)
        for name, result in zip(coros.keys(), raw, strict=True):
            if isinstance(result, BaseException):
                results[name] = SubagentResult(
                    subagent_id=f"subagent-{name.lower()}-error",
                    name=name,
                    success=False,
                    output=None,
                    error=str(result),
                )
            else:
                results[name] = result
        self._results.extend(results.values())
        return results

    def get_stats(self) -> dict[str, Any]:
        total = len(self._results)
        successful = sum(1 for r in self._results if r.success)
        return {
            "total_runs": total,
            "successful": successful,
            "failed": total - successful,
            "success_rate": successful / total if total > 0 else 0.0,
            "retried": sum(1 for r in self._results if r.retries > 0),
            "total_tokens": sum(r.tokens_used for r in self._results),
        }
