"""Spawn policy: a subagent is an expensive operation, not the default.

The previous architecture spawned a fixed cast (ARCHITECT → PLANNER → CODER
→ DEBUGGER) for every request because a table said so. This module replaces
that with an explicit gate: the primary agent proposes work, and the policy
answers *whether delegating it is actually better than doing it inline*.

The default answer is ``PRIMARY_AGENT_ONLY``. A proposal must clear every
condition below to be delegated:

1. the work is genuinely independent of what the primary is doing;
2. it can run in parallel with the primary or with its siblings;
3. it has enough context to start now;
4. it cannot collide with another worker's write scope;
5. its expected duration justifies the fixed spawn overhead;
6. the primary could not simply do it with one or two tool calls;
7. it has a concrete objective;
8. it has a checkable definition of done.

Backpressure is part of the policy, not an afterthought: once
``max_parallel_workers`` useful workers exist, further proposals are
declined even if they are individually reasonable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SpawnVerdict(StrEnum):
    SPAWN = "spawn"
    PRIMARY_AGENT_ONLY = "primary_agent_only"
    QUEUE = "queue"


@dataclass(frozen=True)
class SubagentProposal:
    """A concrete, bounded unit of delegated work."""

    name: str
    objective: str
    definition_of_done: str = ""
    read_scope: frozenset[str] = frozenset()
    write_scope: frozenset[str] = frozenset()
    depends_on: frozenset[str] = frozenset()
    #: Estimated wall-clock seconds. Below ``MIN_USEFUL_SECONDS`` the fixed
    #: cost of a worker (context transfer, model warm-up, result merge)
    #: exceeds the benefit.
    estimated_seconds: float = 0.0
    context_ready: bool = True
    #: True when the primary would need many sequential tool calls anyway.
    requires_deep_exploration: bool = False


@dataclass(frozen=True)
class SpawnDecision:
    verdict: SpawnVerdict
    reason: str
    failed_conditions: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.verdict is SpawnVerdict.SPAWN


@dataclass
class SpawnPolicy:
    """Evaluate delegation proposals against live worker state."""

    max_parallel_workers: int = 3
    #: Delegating anything shorter than this loses to doing it inline.
    min_useful_seconds: float = 20.0
    #: Write scopes currently owned by live workers, keyed by worker name.
    active_write_scopes: dict[str, frozenset[str]] = field(default_factory=dict)
    #: Objectives already being investigated, to avoid duplicate work.
    active_objectives: dict[str, str] = field(default_factory=dict)
    completed_tasks: set[str] = field(default_factory=set)

    @property
    def live_workers(self) -> int:
        return len(self.active_write_scopes)

    def evaluate(self, proposal: SubagentProposal) -> SpawnDecision:
        failed: list[str] = []

        if not proposal.objective.strip():
            failed.append("no concrete objective")
        if not proposal.definition_of_done.strip():
            failed.append("no definition of done")
        if not proposal.context_ready:
            failed.append("context not ready")

        unmet = proposal.depends_on - self.completed_tasks
        if unmet:
            return SpawnDecision(
                verdict=SpawnVerdict.QUEUE,
                reason=f"waiting for {', '.join(sorted(unmet))}",
                failed_conditions=("dependencies not satisfied",),
            )

        conflict = self._write_conflict(proposal.write_scope)
        if conflict is not None:
            return SpawnDecision(
                verdict=SpawnVerdict.QUEUE,
                reason=(
                    f"write scope overlaps worker {conflict!r}; serialising "
                    "instead of racing on the same files"
                ),
                failed_conditions=("write scope conflict",),
            )

        duplicate = self._duplicate_objective(proposal.objective)
        if duplicate is not None:
            return SpawnDecision(
                verdict=SpawnVerdict.PRIMARY_AGENT_ONLY,
                reason=f"worker {duplicate!r} is already investigating this",
                failed_conditions=("duplicate work",),
            )

        if not proposal.requires_deep_exploration and (
            proposal.estimated_seconds < self.min_useful_seconds
        ):
            failed.append(
                f"estimated {proposal.estimated_seconds:.0f}s < "
                f"{self.min_useful_seconds:.0f}s spawn overhead"
            )

        if failed:
            return SpawnDecision(
                verdict=SpawnVerdict.PRIMARY_AGENT_ONLY,
                reason="the primary agent handles this directly: "
                + "; ".join(failed),
                failed_conditions=tuple(failed),
            )

        if self.live_workers >= self.max_parallel_workers:
            return SpawnDecision(
                verdict=SpawnVerdict.QUEUE,
                reason=(
                    f"{self.live_workers} workers already active "
                    f"(cap {self.max_parallel_workers}); queued"
                ),
                failed_conditions=("backpressure",),
            )

        return SpawnDecision(
            verdict=SpawnVerdict.SPAWN,
            reason=(
                f"independent work, ~{proposal.estimated_seconds:.0f}s, "
                "no write-scope overlap"
            ),
        )

    # -- worker bookkeeping -------------------------------------------
    def register(self, proposal: SubagentProposal) -> None:
        self.active_write_scopes[proposal.name] = proposal.write_scope
        self.active_objectives[proposal.name] = _normalise(proposal.objective)

    def release(self, name: str, *, completed: bool = True) -> None:
        self.active_write_scopes.pop(name, None)
        self.active_objectives.pop(name, None)
        if completed:
            self.completed_tasks.add(name)

    # -- helpers -------------------------------------------------------
    def _write_conflict(self, write_scope: frozenset[str]) -> str | None:
        if not write_scope:
            return None
        for name, owned in self.active_write_scopes.items():
            if owned & write_scope:
                return name
        return None

    def _duplicate_objective(self, objective: str) -> str | None:
        target = _normalise(objective)
        if not target:
            return None
        for name, existing in self.active_objectives.items():
            if existing == target:
                return name
        return None


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


__all__ = [
    "SpawnDecision",
    "SpawnPolicy",
    "SpawnVerdict",
    "SubagentProposal",
]
