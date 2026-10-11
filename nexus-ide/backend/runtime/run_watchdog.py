"""Fase 1c — the run watchdog: what happens when a run stops making progress.

A run that stops reporting is the failure mode the rest of the runtime cannot
see on its own: the plan executor is waiting on a tool that will never return,
a provider is answering ``429`` forever, a loop is calling the same tool with
the same arguments, or the run is simply burning budget with nothing to show
for it. The watchdog is the only component that *looks* for that, on a timer,
from outside the run's own coroutine.

What it does
------------
Every ``interval_seconds`` (default 30) the watchdog asks the
:class:`~backend.runtime.run_coordinator.RunCoordinator` for the runs that still
own work and evaluates each one against four independent detectors:

* **stale heartbeat** — ``heartbeat_at`` is older than
  ``stale_heartbeat_seconds``. A run waiting for a *human* approval is exempt:
  waiting for a person is not a stall.
* **no progress** — accumulated ``usage.tool_calls`` did not move between two
  sweeps *and* the heartbeat is stale, i.e. nothing is happening at all.
* **repeated tool** — the same tool name appears
  ``repeated_tool_threshold`` times in the recent checkpoints, which is the
  loop symptom ("call the same thing again and hope").
* **budget / runtime exhausted** — ``budget_status().ok`` is ``False``, or the
  run has been non-terminal longer than ``max_runtime_seconds`` (its own
  ``budget.max_runtime_seconds`` when set, otherwise the configured ceiling).

The result of a decision is a :class:`WatchdogDecision`: an action from
:class:`WatchdogAction` plus the signals that produced it.

What it deliberately does NOT do
--------------------------------
The watchdog never performs a destructive action on its own. ``decide`` is
pure, and :meth:`RunWatchdog.apply` only performs the transitions the
coordinator itself considers safe for an external actor — ``PAUSE``
(``paused``), ``FAIL`` (``failed``) and ``RECOVER``
(``coordinator.restore()`` → ``recovering``). Everything else
(``RETRY``, ``CHANGE_STRATEGY``, ``CHANGE_MODEL``, ``CHANGE_AGENT``,
``REPLAN``, ``ESCALATE``) is *returned to the orchestrator* through the
``on_decision`` callback, because choosing a different model, agent or plan is
a strategy decision that needs the orchestrator's context, not a background
loop's guess.

And it never reaches ``COMPLETED``: a run is only completed by evidence
(:meth:`RunCoordinator.complete` enforces the definition of done), never by a
timer. :class:`WatchdogAction` has no member that can express it, so the
absence is structural rather than a convention someone has to remember.

Observability
-------------
Every decision is (1) written as a structured log line, (2) recorded as a
``run_checkpoints`` payload so it survives a restart and is readable next to
the run's other phase boundaries, and (3) emitted on the event bus when one is
wired. See :meth:`RunWatchdog._record` for the checkpoint phase fallback: the
``run_checkpoints.phase`` CHECK constraint is owned by the coordinator module
(Fase 1a) and has no ``watchdog`` member, so the assessment is stored under the
closest legal phase with the canonical name kept in the payload.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from backend.runtime.run_coordinator import (
    TERMINAL_RUN_STATES,
    BudgetVerdict,
    RunCoordinator,
    RunRecord,
    RunState,
)

logger = logging.getLogger(__name__)

__all__ = [
    "APPLIED_ACTIONS",
    "DEFAULT_MAX_RUNTIME_SECONDS",
    "DEFAULT_REPEATED_TOOL_THRESHOLD",
    "DEFAULT_STALE_HEARTBEAT_SECONDS",
    "DEFAULT_WATCHDOG_INTERVAL_SECONDS",
    "WATCHDOG_CHECKPOINT_PHASES",
    "RunWatchdog",
    "WatchdogAction",
    "WatchdogDecision",
    "WatchdogSignal",
    "get_watchdog",
    "start_watchdog",
    "stop_watchdog",
]

#: How often the watchdog looks at the runs. 30 s is often enough to catch a
#: wedged run within a turn and cheap enough to be noise in the logs.
DEFAULT_WATCHDOG_INTERVAL_SECONDS = 30.0

#: A run that has not refreshed ``heartbeat_at`` for this long is not working.
#: ``update_progress`` writes a heartbeat on every real step, and one tool call
#: is capped by ``TOOL_TIMEOUT_SECONDS`` (240 s by default), so five minutes is
#: past "one slow tool" and into "nothing is happening".
DEFAULT_STALE_HEARTBEAT_SECONDS = 300.0

#: Ceiling for a run with no ``budget.max_runtime_seconds`` of its own. A run
#: that has been non-terminal for an hour is either abandoned or looping.
DEFAULT_MAX_RUNTIME_SECONDS = 3600.0

#: How many checkpoints may name the same tool before the run is looping.
DEFAULT_REPEATED_TOOL_THRESHOLD = 3


class WatchdogAction(StrEnum):
    """What the watchdog concluded should happen to a stalled run.

    The members split in two, and the split is the contract:

    * ``PAUSE``, ``FAIL``, ``RECOVER`` — transitions the watchdog may apply
      itself through :meth:`RunWatchdog.apply`, because they are reversible or
      terminal-by-evidence moves the coordinator already authorises.
    * ``RETRY``, ``CHANGE_STRATEGY``, ``CHANGE_MODEL``, ``CHANGE_AGENT``,
      ``REPLAN``, ``ESCALATE`` — strategy decisions handed back to the
      orchestrator, which owns the plan, the model pool and the agent roster.

    There is deliberately no member that finishes a run. Progress is proven by
    the definition of done, never inferred by a timer.
    """

    RETRY = "retry"
    CHANGE_STRATEGY = "change_strategy"
    CHANGE_MODEL = "change_model"
    CHANGE_AGENT = "change_agent"
    REPLAN = "replan"
    RECOVER = "recover"
    PAUSE = "pause"
    ESCALATE = "escalate"
    FAIL = "fail"


#: The actions :meth:`RunWatchdog.apply` is allowed to perform.
APPLIED_ACTIONS = frozenset({WatchdogAction.PAUSE, WatchdogAction.FAIL, WatchdogAction.RECOVER})


class WatchdogSignal(StrEnum):
    """The observations a decision was built from (one decision may carry several)."""

    STALE_HEARTBEAT = "stale_heartbeat"
    NO_PROGRESS = "no_progress"
    REPEATED_TOOL = "repeated_tool"
    BUDGET_EXCEEDED = "budget_exceeded"
    MAX_RUNTIME_EXCEEDED = "max_runtime_exceeded"
    TASK_STALLED = "task_stalled"
    TASK_FAILED_UNEXPLAINED = "task_failed_unexplained"


#: Checkpoint phases to try when recording a decision, in order. ``watchdog``
#: is the canonical name; ``heartbeat`` is the legal fallback while the
#: ``run_checkpoints.phase`` CHECK constraint (owned by the coordinator module)
#: does not know about it. :meth:`RunWatchdog._record` reports which one won in
#: ``decision.details["checkpoint_phase"]``.
WATCHDOG_CHECKPOINT_PHASES: tuple[str, ...] = ("watchdog", "heartbeat")

#: Payload keys a checkpoint may use to name the tools a step called. Read
#: newest-first, so a producer only has to put its tool list under one of them.
_TOOL_NAME_KEYS: tuple[str, ...] = (
    "tool_calls",
    "recent_tools",
    "tools_used",
    "tools",
    "last_tools",
    "last_tool",
)

#: Runs waiting for a human are not stalled: nobody is supposed to be sending
#: heartbeats while a person decides.
_STALL_EXEMPT_STATES = frozenset({RunState.WAITING_APPROVAL})


def _as_utc(value: datetime) -> datetime:
    """Return *value* as an aware UTC datetime (naive is read as local time)."""
    return value.replace(tzinfo=UTC) if value.tzinfo is not None else value.astimezone(UTC)


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (``...Z`` included), or return ``None``.

    A timestamp that cannot be parsed is *not* an error: the run simply has no
    usable liveness signal, and the caller decides what that means.
    """
    if isinstance(value, datetime):
        return _as_utc(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return _as_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        logger.debug("Unparseable run timestamp %r", value)
        return None


def _age_seconds(value: Any, *, now: datetime) -> float | None:
    """Seconds between *value* and *now*; ``None`` when *value* is unusable."""
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _tool_names(payload: Any) -> list[str]:
    """Extract the tool names a checkpoint payload says were called."""
    if not isinstance(payload, Mapping):
        return []
    names: list[str] = []
    for key in _TOOL_NAME_KEYS:
        value = payload.get(key)
        items: Sequence[Any]
        if isinstance(value, str):
            items = (value,)
        elif isinstance(value, Mapping):
            items = tuple(str(name) for name in value if str(name))
        elif isinstance(value, Iterable) and not isinstance(value, bytes | bytearray):
            items = tuple(value)
        else:
            continue
        for item in items:
            name = str(item).strip()
            if name:
                names.append(name)
    return names


@dataclass(frozen=True)
class WatchdogDecision:
    """One watchdog verdict about a run (or one of its tasks).

    ``signals`` holds the observations that produced it, each a small dict
    (``{"signal": <WatchdogSignal value>, ...}``) so it can be logged, stored
    as a checkpoint payload and serialised without a second mapping.

    ``applies_itself`` is the honest statement of who acts next: ``True`` only
    for the transitions :meth:`RunWatchdog.apply` performs.
    """

    run_id: str
    action: WatchdogAction
    signals: tuple[Mapping[str, Any], ...] = ()
    reason: str = ""
    target_kind: str = "run"
    target_id: str = ""
    state_at_decision: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def applies_itself(self) -> bool:
        """Whether the watchdog may apply this decision on its own."""
        return self.action in APPLIED_ACTIONS

    @property
    def signal_names(self) -> list[str]:
        """The signal names in evaluation order."""
        return [str(signal.get("signal", "")) for signal in self.signals]

    def to_dict(self) -> dict[str, Any]:
        """A JSON-friendly view for logs, events and HTTP responses."""
        return {
            "run_id": self.run_id,
            "action": self.action.value,
            "signals": [dict(signal) for signal in self.signals],
            "reason": self.reason,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "state_at_decision": self.state_at_decision,
            "applies_itself": self.applies_itself,
            "details": dict(self.details),
        }


@dataclass
class _RunObservation:
    """What the previous sweep saw, so "nothing changed" is measurable."""

    tool_calls: int = 0
    updated_at: str = ""


class RunWatchdog:
    """Periodically evaluates active runs and records what should happen.

    Args:
        coordinator: The durable owner of run state. The watchdog only reads it
            (plus ``checkpoint``/``restore``/``transition`` for the recorded
            decisions and the applied ones).
        interval_seconds: Delay between sweeps.
        stale_heartbeat_seconds: Age after which a heartbeat is stale.
        max_runtime_seconds: Ceiling for runs with no
            ``budget.max_runtime_seconds`` of their own.
        repeated_tool_threshold: Occurrences of one tool that means "looping".
        task_manager: Optional ``AutonomousTaskManager``-shaped object. When
            present, stuck and unexplained-failed tasks are evaluated too;
            without it only runs are watched.
        event_bus: Optional event bus with ``async emit(Event)``. Best-effort.
        on_decision: Optional callback invoked with every decision — the hook
            the orchestrator uses to consume the ``CHANGE_*``/``REPLAN``/
            ``RETRY``/``ESCALATE`` decisions this module refuses to act on.
        clock: Injectable "now" (UTC aware). Tests use it to age a run without
            sleeping.
        run_limit: How many runs one sweep reads.
        decision_cooldown_seconds: Minimum spacing between two *recordings* of
            the same action for the same run. A run that stays stalled must not
            write a checkpoint (and a line of log, and an event) every sweep
            forever; ``None`` means ``max(interval, 60s)``.
    """

    def __init__(
        self,
        coordinator: RunCoordinator,
        *,
        interval_seconds: float = DEFAULT_WATCHDOG_INTERVAL_SECONDS,
        stale_heartbeat_seconds: float = DEFAULT_STALE_HEARTBEAT_SECONDS,
        max_runtime_seconds: float = DEFAULT_MAX_RUNTIME_SECONDS,
        repeated_tool_threshold: int = DEFAULT_REPEATED_TOOL_THRESHOLD,
        task_manager: Any | None = None,
        event_bus: Any | None = None,
        on_decision: Callable[[WatchdogDecision], None] | None = None,
        clock: Callable[[], datetime] | None = None,
        run_limit: int = 100,
        decision_cooldown_seconds: float | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if stale_heartbeat_seconds <= 0:
            raise ValueError("stale_heartbeat_seconds must be positive")
        if repeated_tool_threshold < 2:
            raise ValueError("repeated_tool_threshold must be at least 2")
        self._coordinator = coordinator
        self._interval = float(interval_seconds)
        self._stale_heartbeat = float(stale_heartbeat_seconds)
        self._max_runtime = float(max_runtime_seconds)
        self._repeat_threshold = int(repeated_tool_threshold)
        self._task_manager = task_manager
        self._event_bus = event_bus
        self._on_decision = on_decision
        self._clock = clock or (lambda: datetime.now(UTC))
        self._run_limit = int(run_limit)
        self._cooldown = float(
            decision_cooldown_seconds
            if decision_cooldown_seconds is not None
            else max(interval_seconds, 60.0)
        )

        self._observations: dict[str, _RunObservation] = {}
        self._recorded: dict[str, tuple[str, datetime]] = {}
        self._decisions: list[WatchdogDecision] = []
        self._counts: dict[str, int] = {"sweeps": 0, "decisions": 0, "applied": 0, "runs_seen": 0}
        self._stop = threading.Event()
        self._task: asyncio.Task[None] | None = None
        self._lock = threading.Lock()

    # ───── lifecycle ────────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        """Whether the background sweep loop is alive.

        ``_stop`` is checked first so a caller that just called :meth:`stop`
        sees ``False`` immediately, without waiting for the cancelled task to
        be reaped by the event loop.
        """
        return not self._stop.is_set() and self._task is not None and not self._task.done()

    @property
    def interval_seconds(self) -> float:
        return self._interval

    def start(self) -> asyncio.Task[None]:
        """Start the background sweep loop (no-op when already running).

        Must be called from a coroutine: the loop is an ``asyncio`` task on the
        caller's running loop.
        """
        with self._lock:
            if self.running:
                return self._task  # type: ignore[return-value]
            self._stop.clear()
            self._task = asyncio.create_task(self._loop(), name="run-watchdog")
        logger.info(
            "[WATCHDOG] started (interval=%.0fs stale_heartbeat=%.0fs "
            "max_runtime=%.0fs tasks=%s)",
            self._interval,
            self._stale_heartbeat,
            self._max_runtime,
            "yes" if self._task_manager is not None else "no",
        )
        return self._task

    def stop(self) -> None:
        """Ask the sweep loop to exit. Safe to call more than once."""
        self._stop.set()
        task = self._task
        if task is not None and not task.done():
            task.cancel()
        logger.info("[WATCHDOG] stopped")

    async def wait_closed(self) -> None:
        """Await the loop's exit after :meth:`stop` (used by tests/shutdown)."""
        task = self._task
        if task is None:
            return
        try:
            await task
        except asyncio.CancelledError:
            if task.cancelled():
                return  # our own stop() cancelled it: the expected ending
            raise  # the caller was cancelled; that is not ours to swallow
        except Exception:
            logger.debug("[WATCHDOG] loop ended with an error", exc_info=True)

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.evaluate_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A sweep must never kill the watchdog: the next one is the
                # one that finds the run nobody else could see.
                logger.exception("[WATCHDOG] sweep failed")
            try:
                await asyncio.wait_for(self._stop_waiter(), timeout=self._interval)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                raise

    async def _stop_waiter(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(min(0.25, self._interval))

    # ───── detection (pure) ─────────────────────────────────────────────

    def _signals_for(
        self, run: RunRecord, *, now: datetime
    ) -> tuple[list[dict[str, Any]], RunRecord]:
        """Collect every observation about *run*, together with a fresh read."""
        signals: list[dict[str, Any]] = []
        try:
            fresh = self._coordinator.get_run(run.run_id)
        except Exception:  # pragma: no cover - defensive: a read must not raise
            logger.exception("[WATCHDOG] could not re-read run %s", run.run_id)
            fresh = run
        record = fresh if fresh is not None else run

        heartbeat_age = _age_seconds(record.heartbeat_at, now=now)
        runtime_age = _age_seconds(record.created_at, now=now)
        usage: dict[str, Any] = {}
        verdict: BudgetVerdict | None = None
        try:
            verdict = self._coordinator.budget_status(record.run_id)
            usage = dict(verdict.usage)
        except Exception:  # pragma: no cover - defensive
            logger.exception("[WATCHDOG] could not read budget for run %s", record.run_id)

        if verdict is not None and not verdict.ok:
            signals.append(
                {
                    "signal": WatchdogSignal.BUDGET_EXCEEDED.value,
                    "exceeded": dict(verdict.exceeded),
                    "usage": usage,
                }
            )

        hard_runtime = record.budget.get("max_runtime_seconds")
        if (
            isinstance(hard_runtime, int | float)
            and not isinstance(hard_runtime, bool)
            and runtime_age is not None
            and runtime_age > float(hard_runtime)
        ):
            signals.append(
                {
                    "signal": WatchdogSignal.MAX_RUNTIME_EXCEEDED.value,
                    "limit": hard_runtime,
                    "runtime_seconds": round(runtime_age, 3),
                    "source": "budget.max_runtime_seconds",
                }
            )
        elif runtime_age is not None and runtime_age > self._max_runtime:
            # No per-run limit of its own: the configured ceiling still applies,
            # but a ceiling is an operator's question ("is this really still
            # wanted?") and not a hard stop, so it is answered with a pause.
            signals.append(
                {
                    "signal": WatchdogSignal.MAX_RUNTIME_EXCEEDED.value,
                    "limit": self._max_runtime,
                    "runtime_seconds": round(runtime_age, 3),
                    "source": "watchdog_ceiling",
                }
            )

        if heartbeat_age is None:
            signals.append(
                {
                    "signal": WatchdogSignal.STALE_HEARTBEAT.value,
                    "reason": "no heartbeat recorded",
                    "heartbeat_at": record.heartbeat_at,
                }
            )
        elif heartbeat_age > self._stale_heartbeat and record.state not in _STALL_EXEMPT_STATES:
            previous = self._observations.get(record.run_id)
            unchanged = (
                previous is not None
                and int(usage.get("tool_calls") or 0) <= previous.tool_calls
            )
            signals.append(
                {
                    "signal": WatchdogSignal.STALE_HEARTBEAT.value,
                    "heartbeat_age_seconds": round(heartbeat_age, 3),
                    "threshold_seconds": self._stale_heartbeat,
                    "usage_tool_calls": int(usage.get("tool_calls") or 0),
                    "unchanged_since_last_sweep": unchanged,
                }
            )
            if unchanged:
                signals.append(
                    {
                        "signal": WatchdogSignal.NO_PROGRESS.value,
                        "tool_calls": int(usage.get("tool_calls") or 0),
                        "note": "usage_tool_calls did not move between sweeps",
                    }
                )

        repeated = self._repeated_tools(record.run_id)
        if repeated:
            tool, count = repeated
            signals.append(
                {
                    "signal": WatchdogSignal.REPEATED_TOOL.value,
                    "tool": tool,
                    "occurrences": count,
                    "threshold": self._repeat_threshold,
                }
            )
        return signals, record

    def _repeated_tools(self, run_id: str) -> tuple[str, int] | None:
        """Return the most repeated recent tool, or ``None`` when none repeats.

        The evidence is the run's own checkpoints. When a producer does not
        record its tool calls there is nothing to read, and the watchdog falls
        back on the liveness signals instead of inventing a loop.
        """
        try:
            checkpoints = self._coordinator.list_checkpoints(run_id, limit=12)
        except Exception:  # pragma: no cover - defensive
            logger.exception("[WATCHDOG] could not read checkpoints for run %s", run_id)
            return None
        counts: dict[str, int] = {}
        for checkpoint in checkpoints:
            payload = checkpoint.payload
            if isinstance(payload, Mapping) and payload.get("watchdog"):
                continue  # never read our own writing as the run's tool history
            for name in _tool_names(payload):
                counts[name] = counts.get(name, 0) + 1
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            if count >= self._repeat_threshold:
                return name, count
        return None

    def _choose_action(
        self,
        record: RunRecord,
        signals: Sequence[Mapping[str, Any]],
        *,
        now: datetime,
        has_checkpoints: bool,
    ) -> tuple[WatchdogAction, str]:
        """Map the collected signals onto one action, most severe first.

        Ordering matters and is part of the contract: an exhausted budget is
        answered with ``FAIL`` before anything else is considered, because
        every other action spends more of the resource that ran out.
        """
        names = {str(signal.get("signal", "")) for signal in signals}

        if WatchdogSignal.BUDGET_EXCEEDED.value in names:
            exceeded = next(
                (signal.get("exceeded") for signal in signals if signal.get("exceeded")),
                {},
            )
            return WatchdogAction.FAIL, f"budget exceeded: {dict(exceeded or {})}"

        if WatchdogSignal.MAX_RUNTIME_EXCEEDED.value in names:
            hard = [
                signal
                for signal in signals
                if signal.get("source") == "budget.max_runtime_seconds"
            ]
            if hard:
                return (
                    WatchdogAction.FAIL,
                    f"run exceeded its max_runtime_seconds ({hard[0].get('limit')})",
                )

        if WatchdogSignal.STALE_HEARTBEAT.value in names:
            heartbeat_age = next(
                (
                    signal.get("heartbeat_age_seconds")
                    for signal in signals
                    if signal.get("heartbeat_age_seconds") is not None
                ),
                None,
            )
            age_text = (
                f"{heartbeat_age:.0f}s" if heartbeat_age is not None else "an unknown time"
            )
            retries_exhausted = record.retry_count >= 2
            escalate_after = self._stale_heartbeat * 3
            recover_after = self._stale_heartbeat * 5
            if record.state is RunState.PAUSED:
                # Nobody resumed a run the watchdog already parked: it needs a
                # human, not another pause.
                return (
                    WatchdogAction.ESCALATE,
                    "run stayed paused after a watchdog pause; nobody resumed it",
                )
            if (
                has_checkpoints
                and heartbeat_age is not None
                and heartbeat_age >= recover_after
            ):
                return (
                    WatchdogAction.RECOVER,
                    f"no heartbeat for {heartbeat_age:.0f}s; restoring the newest checkpoint",
                )
            if retries_exhausted or (
                heartbeat_age is not None and heartbeat_age >= escalate_after
            ):
                return (
                    WatchdogAction.ESCALATE,
                    "run stopped reporting progress and has no retries left",
                )
            return (
                WatchdogAction.PAUSE,
                f"no heartbeat for {age_text} (threshold {self._stale_heartbeat:.0f}s)",
            )

        if WatchdogSignal.REPEATED_TOOL.value in names:
            tool = next(
                (signal.get("tool") for signal in signals if signal.get("tool")), "?"
            )
            count = next(
                (
                    signal.get("occurrences")
                    for signal in signals
                    if signal.get("occurrences") is not None
                ),
                0,
            )
            if isinstance(count, int) and count >= self._repeat_threshold * 2:
                return (
                    WatchdogAction.REPLAN,
                    f"tool '{tool}' repeated {count} times with no progress; the plan needs rewriting",
                )
            return (
                WatchdogAction.CHANGE_STRATEGY,
                f"tool '{tool}' repeated {count} times; the current strategy is looping",
            )

        if WatchdogSignal.MAX_RUNTIME_EXCEEDED.value in names:
            ceiling = next(
                (signal for signal in signals if signal.get("limit") is not None), {}
            )
            return (
                WatchdogAction.PAUSE,
                f"run is non-terminal for {ceiling.get('runtime_seconds')}s "
                f"(ceiling {ceiling.get('limit')}s)",
            )

        # Unreachable with the detectors above: every signal kind is answered.
        # Kept as a pause rather than a pass so a new detector can never make
        # the watchdog silently ignore a run.
        return WatchdogAction.PAUSE, "watchdog could not classify the stall"

    def decide(self, run: RunRecord | str) -> WatchdogDecision | None:
        """Evaluate one run and return its decision, or ``None`` when healthy.

        Pure: it reads the coordinator but never writes to it, so the same run
        yields the same verdict twice in a row.
        """
        record = run if isinstance(run, RunRecord) else self._coordinator.get_run(str(run))
        if record is None:
            logger.debug("[WATCHDOG] unknown run %s", run)
            return None
        if record.state in TERMINAL_RUN_STATES:
            return None

        now = _as_utc(self._clock())
        signals, fresh = self._signals_for(record, now=now)
        if not signals:
            return None

        has_checkpoints = bool(self._has_checkpoints(fresh.run_id))
        action, reason = self._choose_action(fresh, signals, now=now, has_checkpoints=has_checkpoints)
        if action not in APPLIED_ACTIONS:  # CHANGE_*/RETRY/REPLAN/ESCALATE
            reason = f"{reason} (orchestrator decides)"
        return WatchdogDecision(
            run_id=fresh.run_id,
            action=action,
            signals=tuple(signals),
            reason=reason,
            target_kind="run",
            target_id=fresh.run_id,
            state_at_decision=fresh.state.value,
            details={
                "heartbeat_at": fresh.heartbeat_at,
                "created_at": fresh.created_at,
                "retry_count": fresh.retry_count,
                "budget": dict(fresh.budget),
            },
        )

    def _has_checkpoints(self, run_id: str) -> bool:
        try:
            return bool(self._coordinator.list_checkpoints(run_id, limit=1))
        except Exception:  # pragma: no cover - defensive
            return False

    # ───── recording + applying ─────────────────────────────────────────

    async def evaluate_once(self) -> list[WatchdogDecision]:
        """Run one sweep over the active runs (and tasks) and return decisions."""
        self._counts["sweeps"] += 1
        active = self._coordinator.list_runs(
            states=[state for state in RunState if state not in TERMINAL_RUN_STATES],
            limit=self._run_limit,
        )
        self._counts["runs_seen"] = len(active)
        decisions: list[WatchdogDecision] = [self._sweep_run(run) for run in active]
        decisions.extend(await self._sweep_tasks())
        decisions = [decision for decision in decisions if decision is not None]
        if decisions:
            self._counts["decisions"] += len(decisions)
        return decisions

    def _sweep_run(self, run: RunRecord) -> WatchdogDecision | None:
        """Decide, record, and apply what may be applied for one run."""
        decision = self.decide(run)
        if decision is None:
            self._observations.pop(run.run_id, None)
            return None
        self._remember(run, decision)
        self.remember_decision(decision)
        if self._within_cooldown(decision):
            # The same answer for the same run within the cooldown: the state
            # is already observable from the previous recording, so repeat it
            # in the log at debug level instead of writing another checkpoint.
            logger.debug(
                "[WATCHDOG] run=%s still %s (suppressed within %.0fs cooldown)",
                decision.run_id,
                decision.action.value,
                self._cooldown,
            )
            return decision
        self._record(decision)
        if decision.applies_itself:
            self.apply(decision)
        self._notify(decision)
        return decision

    def _within_cooldown(self, decision: WatchdogDecision) -> bool:
        """Whether the same action was recorded for this run very recently."""
        key = f"{decision.target_kind}:{decision.target_id}"
        previous = self._recorded.get(key)
        now = _as_utc(self._clock())
        if (
            previous is not None
            and previous[0] == decision.action.value
            and (now - previous[1]).total_seconds() < self._cooldown
        ):
            return True
        self._recorded[key] = (decision.action.value, now)
        return False

    def _remember(self, run: RunRecord, decision: WatchdogDecision) -> None:
        """Store what this sweep saw so the next one can detect "no change"."""
        try:
            verdict = self._coordinator.budget_status(run.run_id)
            tool_calls = int(verdict.usage.get("tool_calls") or 0)
        except Exception:  # pragma: no cover - defensive
            tool_calls = 0
        self._observations[run.run_id] = _RunObservation(
            tool_calls=tool_calls, updated_at=run.updated_at
        )

    def _record(self, decision: WatchdogDecision) -> None:
        """Make the decision durable and visible: log, checkpoint, event."""
        payload = {
            "watchdog": True,
            "watchdog_phase": "watchdog",
            "action": decision.action.value,
            "signals": [dict(signal) for signal in decision.signals],
            "reason": decision.reason,
            "state": decision.state_at_decision,
            "applies_itself": decision.applies_itself,
            "recorded_at": _as_utc(self._clock()).isoformat(timespec="seconds"),
        }
        logger.warning(
            "[WATCHDOG] run=%s action=%s state=%s signals=%s reason=%s",
            decision.run_id,
            decision.action.value,
            decision.state_at_decision,
            ",".join(decision.signal_names),
            decision.reason,
        )
        self.remember_decision(decision)
        phase = self._write_checkpoint(decision.run_id, payload)
        decision.details["checkpoint_phase"] = phase or ""

    def _write_checkpoint(self, run_id: str, payload: dict[str, Any]) -> str:
        """Persist the decision as a checkpoint; return the phase used.

        Tries :data:`WATCHDOG_CHECKPOINT_PHASES` in order and returns the first
        phase the coordinator accepted, or ``""`` when it accepted none (the
        run vanished, or the schema knows neither phase). A checkpoint is
        evidence, not a side effect: failing to write one is logged and never
        blocks the decision.
        """
        for phase in WATCHDOG_CHECKPOINT_PHASES:
            try:
                self._coordinator.checkpoint(run_id, phase=phase, payload=payload)
            except ValueError as exc:
                logger.debug(
                    "[WATCHDOG] checkpoint phase %r refused for run %s: %s", phase, run_id, exc
                )
                continue
            except Exception:
                logger.exception(
                    "[WATCHDOG] could not record checkpoint for run %s (phase=%s)", run_id, phase
                )
                return ""
            return phase
        logger.debug("[WATCHDOG] no usable checkpoint phase for run %s", run_id)
        return ""

    def apply(self, decision: WatchdogDecision) -> RunRecord | None:
        """Perform the one transition this decision authorises, if any.

        ``PAUSE`` → ``paused``, ``FAIL`` → ``failed``, ``RECOVER`` →
        ``coordinator.restore()`` (``recovering``). Any other action is refused
        and returned to the caller untouched: the watchdog does not pick a
        model, an agent or a plan, and it never completes a run. An illegal
        transition (someone else moved the run first) is logged and swallowed —
        the decision stays recorded, which is the audit trail.
        """
        if not decision.applies_itself:
            logger.info(
                "[WATCHDOG] run=%s action=%s handed back to the orchestrator",
                decision.run_id,
                decision.action.value,
            )
            return None
        try:
            if decision.action is WatchdogAction.RECOVER:
                checkpoint = self._coordinator.restore(decision.run_id)
                record = self._coordinator.get_run(decision.run_id)
                logger.info(
                    "[WATCHDOG] run=%s recovering from checkpoint %s (phase=%s)",
                    decision.run_id,
                    checkpoint.checkpoint_id,
                    checkpoint.phase,
                )
                self._counts["applied"] += 1
                return record
            target = {
                WatchdogAction.PAUSE: RunState.PAUSED,
                WatchdogAction.FAIL: RunState.FAILED,
            }[decision.action]
            current = self._coordinator.get_run(decision.run_id)
            if current is not None and current.state is target:
                # Already there (a previous sweep applied it): an illegal
                # transition is not a finding, so do not log one.
                logger.debug("[WATCHDOG] run=%s is already %s", decision.run_id, target.value)
                return current
            record = self._coordinator.transition(
                decision.run_id, target, reason=f"watchdog: {decision.reason}"
            )
        except Exception as exc:
            logger.warning(
                "[WATCHDOG] could not apply %s to run %s: %s",
                decision.action.value,
                decision.run_id,
                exc,
            )
            return None
        self._counts["applied"] += 1
        logger.info(
            "[WATCHDOG] run=%s %s -> %s (%s)",
            decision.run_id,
            decision.state_at_decision,
            record.state.value,
            decision.action.value,
        )
        return record

    def _notify(self, decision: WatchdogDecision) -> None:
        """Hand the decision to the orchestrator hook and the event bus."""
        if self._on_decision is not None:
            try:
                self._on_decision(decision)
            except Exception:
                logger.exception(
                    "[WATCHDOG] on_decision callback failed for run %s", decision.run_id
                )
        if self._event_bus is not None:
            self._emit_event(decision)

    def _emit_event(self, decision: WatchdogDecision) -> None:
        """Publish the decision on the observability bus, best-effort."""
        try:
            from backend.observability.event_system import Event, EventPriority, EventType

            priority = (
                EventPriority.CRITICAL
                if decision.action is WatchdogAction.FAIL
                else EventPriority.HIGH
                if decision.action in {WatchdogAction.ESCALATE, WatchdogAction.RECOVER}
                else EventPriority.NORMAL
            )
            event = Event(
                event_type=EventType.SYSTEM_WARNING,
                source="run_watchdog",
                priority=priority,
                payload=decision.to_dict(),
            )
            self._spawn_emit(event)
        except Exception:
            logger.debug("[WATCHDOG] event bus emission skipped", exc_info=True)

    def _spawn_emit(self, event: Any) -> None:
        """Emit on the running loop when there is one; never block the sweep."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._safe_emit(event))

    async def _safe_emit(self, event: Any) -> None:
        try:
            await self._event_bus.emit(event)  # type: ignore[union-attr]
        except Exception:
            logger.debug("[WATCHDOG] event bus emit failed", exc_info=True)

    # ───── tasks ────────────────────────────────────────────────────────

    async def _sweep_tasks(self) -> list[WatchdogDecision]:
        """Evaluate the autonomous tasks, when a manager is reachable.

        The manager is optional by design: the watchdog must still watch runs
        when the task scheduler is disabled (it is, by default, under pytest and
        in any deployment that turns background services off).
        """
        manager = self._task_manager
        if manager is None:
            return []
        decisions: list[WatchdogDecision] = []
        now = _as_utc(self._clock())
        try:
            tasks = await manager.get_tasks(limit=self._run_limit)
        except Exception:
            logger.debug("[WATCHDOG] task manager could not list tasks", exc_info=True)
            return []
        parked = self._parked_task_ids()
        for task in tasks:
            status = str(getattr(task, "status", "") or "")
            run_id = str((getattr(task, "metadata", None) or {}).get("run_id") or "")
            updated = getattr(task, "updated_at", None)
            age = _age_seconds(updated, now=now) if updated is not None else None
            if status in {"running", "retrying"} and age is not None and age > self._stale_heartbeat:
                decision = self._task_decision(
                    run_id=run_id,
                    task=task,
                    action=WatchdogAction.PAUSE,
                    signal=WatchdogSignal.TASK_STALLED,
                    reason=(
                        f"task {task.task_id} has been {status} for {age:.0f}s "
                        f"(threshold {self._stale_heartbeat:.0f}s)"
                    ),
                    extra={"status": status, "age_seconds": round(age, 3)},
                )
            elif status == "failed" and task.task_id not in parked:
                decision = self._task_decision(
                    run_id=run_id,
                    task=task,
                    action=WatchdogAction.ESCALATE,
                    signal=WatchdogSignal.TASK_FAILED_UNEXPLAINED,
                    reason=(
                        f"task {task.task_id} is FAILED with no dead-letter entry; "
                        "nothing explains the failure"
                    ),
                    extra={"status": status, "error": str(getattr(task, "error", "") or "")},
                )
            else:
                continue
            decisions.append(decision)
            # A task has no checkpoint stream of its own, so the structured log
            # and the event bus are the record; the decision stays in memory for
            # ``snapshot()``.
            logger.warning("[WATCHDOG] task=%s action=%s %s", decision.target_id, decision.action.value, decision.reason)
            self.remember_decision(decision)
            self._emit_event(decision)
        return decisions

    def _task_decision(
        self,
        *,
        run_id: str,
        task: Any,
        action: WatchdogAction,
        signal: WatchdogSignal,
        reason: str,
        extra: Mapping[str, Any],
    ) -> WatchdogDecision:
        return WatchdogDecision(
            run_id=run_id,
            action=action,
            signals=({"signal": signal.value, **dict(extra)},),
            reason=reason,
            target_kind="task",
            target_id=str(getattr(task, "task_id", "")),
            state_at_decision=str(getattr(task, "status", "") or ""),
            details={"task_name": str(getattr(task, "name", "") or "")},
        )

    def _parked_task_ids(self) -> set[str]:
        """Task ids that already have a dead-letter entry (any state)."""
        try:
            entries = self._coordinator.list_dead_letters(state=None, limit=self._run_limit)
        except Exception:
            logger.debug("[WATCHDOG] could not read dead letters", exc_info=True)
            return set()
        return {
            str(entry.get("task_id"))
            for entry in entries
            if str(entry.get("task_id") or "").strip()
        }

    # ───── observability ────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Counters and the recent decisions, for a dashboard or a test."""
        return {
            "running": self.running,
            "interval_seconds": self._interval,
            "decision_cooldown_seconds": self._cooldown,
            "stale_heartbeat_seconds": self._stale_heartbeat,
            "max_runtime_seconds": self._max_runtime,
            "repeated_tool_threshold": self._repeat_threshold,
            "counts": dict(self._counts),
            "watching_tasks": self._task_manager is not None,
            "decisions": [decision.to_dict() for decision in self._decisions[-25:]],
        }

    @property
    def decisions(self) -> list[WatchdogDecision]:
        """Every decision this instance produced (bounded ring kept in memory)."""
        return list(self._decisions)

    def remember_decision(self, decision: WatchdogDecision) -> None:
        """Keep a decision in the in-memory ring used by :meth:`snapshot`."""
        self._decisions.append(decision)
        if len(self._decisions) > 200:
            del self._decisions[:-200]


_watchdog_lock = threading.Lock()
_watchdog: RunWatchdog | None = None


def start_watchdog(coordinator: RunCoordinator, **kwargs: Any) -> RunWatchdog:
    """Start the process-wide watchdog and return it. Idempotent.

    A second call while one is running returns the *same* instance rather than
    starting a second loop: two watchdogs would apply opposite transitions to
    the same run and double-record every decision. Pass different kwargs to
    reconfigure only after :func:`stop_watchdog`.
    """
    global _watchdog
    with _watchdog_lock:
        if _watchdog is not None and _watchdog.running:
            return _watchdog
        watchdog = RunWatchdog(coordinator, **kwargs)
        watchdog.start()
        _watchdog = watchdog
        return watchdog


def get_watchdog() -> RunWatchdog | None:
    """Return the process-wide watchdog, if one was started."""
    return _watchdog


def stop_watchdog() -> None:
    """Stop the process-wide watchdog and forget it. Safe when none is running."""
    global _watchdog
    with _watchdog_lock:
        watchdog, _watchdog = _watchdog, None
    if watchdog is not None:
        watchdog.stop()
