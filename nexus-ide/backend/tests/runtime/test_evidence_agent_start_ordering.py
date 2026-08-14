"""Evidence: agent start-up is unbounded and unordered.

Reproduces the reported symptom "agents start out of order / the last agent
starts first" without a browser, by observing the swarm strategies directly.

Two independent defects are asserted here:

1. ``SwarmOrchestrator`` fans out with a bare ``asyncio.gather`` and has no
   concurrency bound, so N agents all enter their first LLM call before any
   of them completes ("agent storm").
2. There is no ordering guarantee at all: the observed start order is the
   order in which each coroutine happens to reach its first await, which is
   not the declared order.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.orchestrator.swarm import SwarmOrchestrator


class _RecordingAgent:
    """Minimal AgentBase stand-in that records its own lifecycle."""

    def __init__(self, name: str, timeline: list[tuple[str, str]], delay: float) -> None:
        self.name = name
        self._timeline = timeline
        self._delay = delay

    async def run(self, req: Any):  # noqa: ANN001, ANN201 - duck-typed
        self._timeline.append(("start", self.name))
        await asyncio.sleep(self._delay)
        self._timeline.append(("end", self.name))
        yield f"{self.name} done"


def _swarm(timeline: list[tuple[str, str]], names: list[str], delays: dict[str, float]):
    registry = {n: _RecordingAgent(n, timeline, delays[n]) for n in names}
    swarm = SwarmOrchestrator(
        llm_client=object(),
        registry=registry,  # type: ignore[arg-type]
        event_bus=None,
        max_agents=len(names),
    )

    async def _merge(*args: Any, **kwargs: Any) -> str:
        return "merged"

    swarm._merge_with_llm = _merge  # type: ignore[assignment]
    return swarm


@pytest.mark.asyncio
async def test_swarm_respects_a_concurrency_bound() -> None:
    """Five agents must not all be in-flight at once by default."""
    names = [f"AGENT_{i}" for i in range(5)]
    timeline: list[tuple[str, str]] = []
    swarm = _swarm(timeline, names, {n: 0.02 for n in names})

    await swarm._ensemble("objective", "sess", names, ".")

    # Peak parallelism observed on the timeline.
    peak = 0
    live = 0
    for kind, _ in timeline:
        live += 1 if kind == "start" else -1
        peak = max(peak, live)

    assert peak < len(names), (
        f"all {len(names)} agents were in flight simultaneously (peak={peak}); "
        "the swarm has no max_parallel bound, so every extra agent is an "
        "unbounded provider call."
    )


@pytest.mark.asyncio
async def test_agent_start_events_follow_declared_order() -> None:
    """The last declared agent must not appear to start first.

    This asserts on the ``agent_started`` events the chat stream renders —
    the exact signal the user reads as "which agent started when". A slow
    context build inside the first agent must not let a later agent's start
    event overtake it.
    """
    names = [f"AGENT_{i}" for i in range(5)]
    timeline: list[tuple[str, str]] = []
    swarm = _swarm(timeline, names, {n: 0.01 for n in names})

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    swarm.event_queue = queue

    # The declared-first agent is the slowest to produce its first token,
    # which is what a provider handshake or context build looks like.
    original = swarm.registry["AGENT_0"].run  # type: ignore[union-attr]

    async def slow_start(req: Any):  # noqa: ANN001, ANN201
        await asyncio.sleep(0.005)
        async for token in original(req):
            yield token

    swarm.registry["AGENT_0"].run = slow_start  # type: ignore[union-attr,assignment]

    await swarm._ensemble("objective", "sess", names, ".")

    emitted: list[str] = []
    while not queue.empty():
        payload = queue.get_nowait()
        if payload.get("type") == "agent_started":
            emitted.append(str(payload.get("agent")))

    assert emitted == names, (
        f"declared order was {names} but the UI received start events in "
        f"{emitted}: start-up order is not controlled by the scheduler."
    )
