"""Per-run telemetry: where the time actually goes.

The reported symptom is "the agent thinks for ~2 minutes and does nothing".
Answering that needs measurements, not opinions, so a run records every
lifecycle instant exactly once and derives four headline latencies:

``time_to_first_token``
    First byte of visible assistant output.
``time_to_first_action``
    First externally observable act (a tool call, a status update that
    reflects real work, a subagent start) — not merely text.
``time_to_first_tool_call``
    First tool invocation.
``time_to_first_useful_work``
    First act that changed or inspected the project: a file read, a file
    change, a command, or a test. Text and planning do not count.

All instants come from :func:`time.monotonic`, so the numbers stay correct
across NTP corrections and are unaffected by Windows wall-clock granularity.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class RunPhase(StrEnum):
    """Coarse phases, each measured separately so a slow one is visible."""

    RECEIVED = "received"
    ROUTING = "routing"
    CONTEXT_BUILD = "context_build"
    PLANNING = "planning"
    MODEL_REQUEST = "model_request"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    FINISHED = "finished"


class BlockedOn(StrEnum):
    """What the run is waiting for, so the UI never shows a bare spinner."""

    WORKING = "working"
    WAITING_MODEL = "waiting_model"
    WAITING_TOOL = "waiting_tool"
    WAITING_WORKER = "waiting_worker"
    WAITING_DEPENDENCY = "waiting_dependency"
    WAITING_USER = "waiting_user"
    TESTING = "testing"
    BLOCKED = "blocked"


@dataclass
class RunTelemetry:
    """Mutable telemetry for one run. Every ``mark_*`` is idempotent."""

    run_id: str
    started_at: float = field(default_factory=time.monotonic)
    started_wall: float = field(default_factory=time.time)

    # Milestones (seconds since run start; ``None`` means "never happened").
    time_to_first_token: float | None = None
    time_to_first_action: float | None = None
    time_to_first_tool_call: float | None = None
    time_to_first_useful_work: float | None = None
    total_duration: float | None = None

    # Cumulative time per phase.
    phase_durations: dict[str, float] = field(default_factory=dict)
    _phase: RunPhase | None = None
    _phase_entered: float = 0.0

    # Counters.
    tool_calls: int = 0
    files_read: int = 0
    files_changed: int = 0
    commands_run: int = 0
    tests_run: int = 0
    retries: int = 0
    parser_failures: int = 0
    agent_failures: int = 0
    recovered_failures: int = 0
    agents_spawned: int = 0
    parallelism_peak: int = 0
    subagents_declined: int = 0

    blocked_on: BlockedOn = BlockedOn.WORKING

    # -- clock ---------------------------------------------------------
    def _elapsed(self) -> float:
        return time.monotonic() - self.started_at

    # -- phases --------------------------------------------------------
    def enter_phase(self, phase: RunPhase) -> None:
        now = time.monotonic()
        if self._phase is not None:
            self.phase_durations[self._phase.value] = (
                self.phase_durations.get(self._phase.value, 0.0) + now - self._phase_entered
            )
        self._phase = phase
        self._phase_entered = now

    def finish(self) -> None:
        self.enter_phase(RunPhase.FINISHED)
        if self.total_duration is None:
            self.total_duration = self._elapsed()

    # -- milestones ----------------------------------------------------
    def _mark_action(self) -> None:
        if self.time_to_first_action is None:
            self.time_to_first_action = self._elapsed()

    def mark_first_token(self) -> None:
        if self.time_to_first_token is None:
            self.time_to_first_token = self._elapsed()

    def mark_tool_call(self, *, useful: bool = False) -> None:
        self.tool_calls += 1
        self._mark_action()
        if self.time_to_first_tool_call is None:
            self.time_to_first_tool_call = self._elapsed()
        if useful and self.time_to_first_useful_work is None:
            self.time_to_first_useful_work = self._elapsed()

    def mark_useful_work(self) -> None:
        self._mark_action()
        if self.time_to_first_useful_work is None:
            self.time_to_first_useful_work = self._elapsed()

    def mark_file_read(self, count: int = 1) -> None:
        self.files_read += count
        self.mark_useful_work()

    def mark_file_changed(self, count: int = 1) -> None:
        self.files_changed += count
        self.mark_useful_work()

    def mark_command(self) -> None:
        self.commands_run += 1
        self.mark_useful_work()

    def mark_test_run(self, count: int = 1) -> None:
        self.tests_run += count
        self.mark_useful_work()

    def mark_subagent_started(self, live_count: int) -> None:
        self.agents_spawned += 1
        self.parallelism_peak = max(self.parallelism_peak, live_count)
        self._mark_action()

    def mark_subagent_declined(self) -> None:
        self.subagents_declined += 1

    def mark_retry(self) -> None:
        self.retries += 1

    def mark_parser_failure(self) -> None:
        self.parser_failures += 1

    def mark_agent_failure(self, *, recovered: bool = False) -> None:
        self.agent_failures += 1
        if recovered:
            self.recovered_failures += 1

    # -- export --------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        data = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        data["blocked_on"] = self.blocked_on.value
        data["elapsed"] = self._elapsed()
        return data


@dataclass
class ProgressReport:
    """Progress derived from real task state — never an invented percentage."""

    total: int
    completed: int
    running: int
    pending: int
    failed: int = 0
    label: str = ""

    @property
    def percent(self) -> int | None:
        """``None`` when there is nothing countable yet.

        A caller that receives ``None`` must render the status label, not
        ``0%``. Showing 0% for minutes is what made the UI look frozen.
        """
        if self.total <= 0:
            return None
        return round(100 * self.completed / self.total)

    def render(self) -> str:
        percent = self.percent
        if percent is None:
            return self.label or "a trabalhar…"
        return f"{self.completed}/{self.total} ({percent}%)"


__all__ = ["BlockedOn", "ProgressReport", "RunPhase", "RunTelemetry"]
