"""SWARM Coordinator — selects the operational mode and dispatches work.

The Coordinator never executes code; it dispatches REQUEST messages to the
right agents and waits for responses. It also enforces the anti-loop rule:
if the same (sender, type) message has been sent more than N times in a
run, the Coordinator aborts the run with a clear error.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from backend.swarm.communication.message_bus import MessageBus
from backend.swarm.core.types import (
    AgentMessage,
    AgentRole,
    MessageType,
    OperationalMode,
    SwarmStrategy,
)
from backend.swarm.modes.mode_registry import OPERATIONAL_MODES, get_mode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------

_MODE_KEYWORDS: dict[OperationalMode, tuple[str, ...]] = {
    OperationalMode.ARCHITECTURE: (
        "architect",
        "architecture",
        "design system",
        "system design",
        "structure",
        "module",
        "components",
        "trade-off",
        "tradeoff",
        "adr",
        "decision record",
    ),
    OperationalMode.INVESTIGATION: (
        "investigate",
        "explore",
        "understand",
        "summarise codebase",
        "how does",
        "what does",
        "where is",
        "find files",
        "locate",
    ),
    OperationalMode.IMPLEMENTATION: (
        "implement",
        "build",
        "create",
        "add feature",
        "scaffold",
        "refactor",
        "restructure",
        "wire up",
        "integrate",
    ),
    OperationalMode.REVIEW: (
        "review",
        "audit",
        "check code",
        "inspect",
        "peer review",
    ),
    OperationalMode.BUGFIX: (
        "bug",
        "fix",
        "broken",
        "crash",
        "error in",
        "failing test",
        "regression",
        "broken behaviour",
        "not working",
    ),
    OperationalMode.PLANNING: (
        "plan",
        "roadmap",
        "steps",
        "phases",
        "milestones",
        "schedule",
        "breakdown",
    ),
    OperationalMode.RESEARCH: (
        "research",
        "look up",
        "find docs",
        "best practice",
        "tutorial",
        "library comparison",
        "vs ",
        "which is better",
    ),
}


@dataclass
class CoordinatorDecision:
    """The Coordinator's decision for a run."""

    mode: OperationalMode
    strategy: SwarmStrategy
    confidence: float
    rationale: str
    detected_signals: list[str] = field(default_factory=list)


def detect_mode(objective: str) -> CoordinatorDecision:
    """Heuristically detect the operational mode from the user's objective."""
    lowered = (objective or "").lower()
    if not lowered.strip():
        return CoordinatorDecision(
            mode=OperationalMode.INVESTIGATION,
            strategy=SwarmStrategy.ENSEMBLE,
            confidence=0.0,
            rationale="Empty objective — defaulting to investigation.",
        )

    scores: Counter[OperationalMode] = Counter()
    signals: dict[OperationalMode, list[str]] = {m: [] for m in OPERATIONAL_MODES}

    for mode, keywords in _MODE_KEYWORDS.items():
        for kw in keywords:
            if kw in lowered:
                scores[mode] += 1
                if len(signals[mode]) < 3:
                    signals[mode].append(kw)

    if not scores:
        # No keyword hit — fall back to a length / structural heuristic.
        if len(lowered.split()) < 12:
            return CoordinatorDecision(
                mode=OperationalMode.INVESTIGATION,
                strategy=SwarmStrategy.ENSEMBLE,
                confidence=0.2,
                rationale="Short objective with no mode markers — defaulting to investigation.",
            )
        return CoordinatorDecision(
            mode=OperationalMode.PLANNING,
            strategy=SwarmStrategy.DIVIDE,
            confidence=0.2,
            rationale="Longer objective with no mode markers — defaulting to planning.",
        )

    mode, top_score = scores.most_common(1)[0]
    total = sum(scores.values()) or 1
    confidence = min(1.0, top_score / max(1, total) + 0.1 * (top_score - 1))
    return CoordinatorDecision(
        mode=mode,
        strategy=get_mode(mode).default_strategy,
        confidence=round(confidence, 3),
        rationale=f"Detected {top_score} signal(s) for {mode.value}: {signals[mode]}",
        detected_signals=signals[mode],
    )


# ---------------------------------------------------------------------------
# Anti-loop guard
# ---------------------------------------------------------------------------

DEFAULT_LOOP_THRESHOLD = 4


class AntiLoopGuard:
    """Tracks repeated (sender, type) signatures and aborts on threshold."""

    def __init__(self, threshold: int = DEFAULT_LOOP_THRESHOLD) -> None:
        self._threshold = threshold
        self._counts: Counter[tuple[str, str]] = Counter()

    def check(self, message: AgentMessage) -> tuple[bool, int]:
        """Return (ok, count). When ``ok`` is False, the run must abort."""
        key = (message.sender, message.type.value)
        self._counts[key] += 1
        return self._counts[key] <= self._threshold, self._counts[key]

    def reset(self) -> None:
        self._counts.clear()


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class Coordinator:
    """High-level SWARM coordinator — mode detection + dispatch.

    The actual agent *execution* is delegated to the Orchestrator; this
    class is responsible for:
    - picking the operational mode & strategy
    - building the request message
    - enforcing the anti-loop rule
    - publishing status updates
    """

    def __init__(self, message_bus: MessageBus | None = None) -> None:
        self._bus = message_bus
        self._guard = AntiLoopGuard()

    @property
    def bus(self) -> MessageBus | None:
        return self._bus

    @bus.setter
    def bus(self, value: MessageBus | None) -> None:
        self._bus = value
        self._guard.reset()

    def decide(
        self, objective: str, explicit_mode: OperationalMode | None = None
    ) -> CoordinatorDecision:
        """Return the CoordinatorDecision for an objective."""
        if explicit_mode is not None:
            return CoordinatorDecision(
                mode=explicit_mode,
                strategy=get_mode(explicit_mode).default_strategy,
                confidence=1.0,
                rationale=f"Explicit mode requested: {explicit_mode.value}",
            )
        return detect_mode(objective)

    async def publish_status(self, content: str, payload: dict[str, Any] | None = None) -> None:
        if not self._bus:
            return
        msg = AgentMessage(
            sender=AgentRole.COORDINATOR.value,
            recipient="*",
            type=MessageType.STATUS,
            content=content,
            payload=payload or {},
        )
        try:
            await self._bus.publish(msg)
        except Exception as exc:
            logger.debug("publish_status failed: %s", exc)

    def guard_message(self, message: AgentMessage) -> tuple[bool, int]:
        return self._guard.check(message)

    def reset_guard(self) -> None:
        self._guard.reset()


__all__ = [
    "Coordinator",
    "CoordinatorDecision",
    "AntiLoopGuard",
    "detect_mode",
]
