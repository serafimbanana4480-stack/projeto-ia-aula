"""Subagent phase registry — the single source of truth for phase budgets.

Each phase (RESEARCH, DESIGN, BUILD, VERIFY) declares:
- agent_type: the AgentBase name to resolve from the AgentRegistry
- timeout / token_budget / context_budget / max_retries: resource limits
- bus_topic_complete / bus_topic_failed: AgentBus topics for lifecycle events

WHY THIS FILE IS AUTHORITATIVE

The same four budgets used to be declared twice: here as `SubagentPhaseConfig`
dataclasses, and again in `SubagentRunner.SUBAGENTS` as a dict of dicts holding
identical numbers. Two copies of a tuning table drift the moment anyone tunes
one of them, and the resulting bug — a phase behaving differently depending on
which entry point started it — is close to invisible. `SubagentRunner` now
reads from here, so there is one place to change a budget.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from backend.orchestrator.context_budget import Priority

#: Ceiling applied when scaling a phase for a large task. Without it, a caller
#: handing over a very large context would scale the budget past what any
#: provider accepts, converting a recoverable trim into a hard API error.
MAX_SCALE = 2.5


@dataclass(frozen=True)
class SubagentPhaseConfig:
    phase: str
    agent_type: str
    timeout: float = 60.0
    token_budget: int = 4000
    max_retries: int = 1
    bus_topic_complete: str = ""
    bus_topic_failed: str = ""
    #: Tokens the *input* context may occupy. Separate from `token_budget`
    #: (which governs the whole exchange) because a phase can legitimately want
    #: to read a great deal and answer briefly — VERIFY reads a full diff and
    #: replies with a verdict — or the reverse. Collapsing the two forces every
    #: phase into the same read/write ratio.
    context_budget: int = 3000
    #: Seconds before the first retry. Each subsequent attempt doubles it.
    retry_backoff_seconds: float = 1.0
    #: Phase-specific overrides merged over `context_budget.DEFAULT_PRIORITIES`.
    #: A key that is disposable in one phase is load-bearing in another: test
    #: failures are noise to RESEARCH and the entire point of VERIFY.
    context_priorities: dict[str, Priority] | None = None

    def scaled_for(self, task_tokens: int) -> SubagentPhaseConfig:
        """Return a copy with budgets grown to suit a larger task.

        Fixed budgets meant a one-line objective and a twenty-file refactor
        were allotted exactly the same time and tokens. The small task wasted
        its allowance; the large one hit a timeout that looked like a crash.

        Scaling is sub-linear (square root): doubling the input multiplies the
        budget by about 1.41. Large tasks genuinely need more room, but the
        extra material is usually repetitive — more files of the same shape —
        so cost should not track size one-for-one. Budgets only ever grow; a
        small task keeps the configured floor.
        """
        if task_tokens <= self.context_budget:
            return self

        ratio = (task_tokens / self.context_budget) ** 0.5
        scale = min(MAX_SCALE, ratio)
        return replace(
            self,
            timeout=round(self.timeout * scale, 1),
            token_budget=int(self.token_budget * scale),
            context_budget=int(self.context_budget * scale),
        )


SUBAGENT_PHASES: dict[str, SubagentPhaseConfig] = {
    "RESEARCH": SubagentPhaseConfig(
        phase="RESEARCH",
        agent_type="RESEARCHER",
        timeout=120.0,
        token_budget=8000,
        max_retries=2,
        bus_topic_complete="subagent.research.complete",
        bus_topic_failed="subagent.research.failed",
        # Reads widely, reports concisely — most of its budget is input.
        context_budget=6000,
        retry_backoff_seconds=1.0,
        context_priorities={
            "search_results": Priority.HIGH,
            "documentation": Priority.HIGH,
            "diff": Priority.LOW,
            "test_failures": Priority.LOW,
        },
    ),
    "DESIGN": SubagentPhaseConfig(
        phase="DESIGN",
        agent_type="ARCHITECT_DESIGN",
        timeout=180.0,
        token_budget=12000,
        max_retries=1,
        bus_topic_complete="subagent.design.complete",
        bus_topic_failed="subagent.design.failed",
        # Produces a plan, so it needs more room to write than to read.
        context_budget=7000,
        retry_backoff_seconds=2.0,
        context_priorities={
            "requirements": Priority.CRITICAL,
            "constraints": Priority.CRITICAL,
            "previous_output": Priority.HIGH,
        },
    ),
    "BUILD": SubagentPhaseConfig(
        phase="BUILD",
        agent_type="CODER",
        timeout=300.0,
        token_budget=16000,
        max_retries=2,
        bus_topic_complete="subagent.build.complete",
        bus_topic_failed="subagent.build.failed",
        # The heaviest reader: the plan plus every file it must touch.
        context_budget=10000,
        retry_backoff_seconds=2.0,
        context_priorities={
            "plan": Priority.CRITICAL,
            "files": Priority.HIGH,
            "diff": Priority.HIGH,
        },
    ),
    "VERIFY": SubagentPhaseConfig(
        phase="VERIFY",
        agent_type="REVIEWER",
        timeout=180.0,
        token_budget=8000,
        max_retries=1,
        bus_topic_complete="subagent.verify.complete",
        bus_topic_failed="subagent.verify.failed",
        # Reads the change and its fallout; answers with a verdict.
        context_budget=6000,
        retry_backoff_seconds=1.0,
        context_priorities={
            "diff": Priority.CRITICAL,
            "test_failures": Priority.CRITICAL,
            "acceptance_criteria": Priority.CRITICAL,
            "search_results": Priority.LOW,
        },
    ),
}


def get_subagent_phase(phase: str) -> SubagentPhaseConfig | None:
    return SUBAGENT_PHASES.get(phase.upper())


def list_phases() -> list[str]:
    return list(SUBAGENT_PHASES.keys())
