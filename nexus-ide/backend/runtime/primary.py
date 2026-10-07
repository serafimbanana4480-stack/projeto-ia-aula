"""The NEXUS primary agent loop: observe → act → tool → observe → test → report.

One agent owns the turn. It looks at the project, acts, uses tools, looks at
what its tools returned, verifies the result, and reports. No PLANNER,
ARCHITECT or CODER is created unless delegating demonstrably wins — that
decision belongs to :class:`~backend.runtime.spawn_policy.SpawnPolicy`, and
its default answer is ``PRIMARY_AGENT_ONLY``.

The loop is deliberately free of provider, database and HTTP dependencies.
Everything it talks to is injected:

``stream``
    ``(PrimaryTurn) -> AsyncIterator[AgentSignal]`` — the model turn.
``observe``
    ``(PrimaryTurn) -> Observation`` — the cheap, deterministic project
    snapshot that runs *before* the first model byte. This is what makes
    ``TIME_TO_FIRST_USEFUL_WORK`` small: the run has inspected something real
    before the provider has produced a token.
``verify``
    ``(VerificationRequest) -> VerificationResult`` — the test phase.
``run_subagent``
    ``(SubagentProposal) -> str`` — only ever called for proposals the spawn
    policy approved.

Every observable fact leaves through :class:`RunEventStream`, so the ordering
guarantees proven in phase 2 (``(run_id, seq)`` total order, replay after a
browser refresh) apply to the whole turn, not just to the parts that happen
to go through the old event bus.
"""

from __future__ import annotations

import asyncio
import contextlib
import difflib
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from backend.runtime.events import RunEventStream, RuntimeEvent, RuntimeEventType
from backend.runtime.reasoning import (
    ReasoningVisibility,
    bound_reasoning_text,
    join_collected_reasoning,
    reasoning_label_or_default,
    reasoning_visibility,
)
from backend.runtime.scheduler import RuntimeScheduler, RuntimeTask, RuntimeTaskStatus
from backend.runtime.spawn_policy import SpawnPolicy, SpawnVerdict, SubagentProposal
from backend.runtime.telemetry import BlockedOn, RunPhase, RunTelemetry

try:
    from backend.experience.bus import FakeBus
except (ImportError, AttributeError):
    FakeBus = None  # type: ignore[assignment-misc]

logger = logging.getLogger(__name__)

_experience_bus_cache: Any = None
_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 30.0
_MAX_PREVIOUS_ANSWER_CHARS = 12_000


def _configured_heartbeat_interval() -> float:
    """Read the operational heartbeat interval; zero explicitly disables it."""
    raw = os.environ.get("NEXUS_PRIMARY_HEARTBEAT_INTERVAL", "").strip()
    if not raw:
        return _DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    return max(0.0, value)


def _bounded_previous_answer(answer: str) -> str:
    """Keep follow-up context useful without growing the provider prompt unbounded."""
    if len(answer) <= _MAX_PREVIOUS_ANSWER_CHARS:
        return answer
    omitted = len(answer) - _MAX_PREVIOUS_ANSWER_CHARS
    return (
        f"[Início da resposta omitido: {omitted} caracteres.]\n"
        + answer[-_MAX_PREVIOUS_ANSWER_CHARS:]
    )


_MARKDOWN_HEADING = re.compile(
    r"(?m)^ {0,3}(?:#{1,6}\s+.+|\*\*[^*\n]+(?<!:)\*\*|\d{1,2}[.)]\s+.{1,180})\s*$"
)
_REPEATED_SECTION_SIMILARITY = 0.9
_REPEATED_PARAGRAPH_SIMILARITY = 0.94


def _heading_key(heading: str) -> str:
    text = re.sub(r"^\s*#+\s*", "", heading)
    text = re.sub(r"^\*\*|\*\*$", "", text).strip()
    return re.sub(r"\s+", " ", text).casefold()


def _normalized_paragraph(paragraph: str) -> str:
    return re.sub(r"\s+", " ", paragraph).strip().casefold()


def _near_duplicate_text(previous: str, candidate: str, threshold: float) -> bool:
    if previous == candidate:
        return True
    longer = max(len(previous), len(candidate))
    if not longer or min(len(previous), len(candidate)) / longer < threshold:
        return False
    return difflib.SequenceMatcher(None, previous, candidate).ratio() >= threshold


def _remove_repeated_markdown_sections(previous: str, continuation: str) -> str:
    """Drop near-identical sections or paragraphs a follow-up regenerated.

    Follow-up turns are buffered until completion, so a repeated section never
    flashes in the live answer before this filter can remove it. Only sections
    with an existing heading and strongly similar body are dropped; a genuine
    correction or addition under the same heading can still be shown. Repeated
    long paragraphs are also removed when a response has no useful headings.
    """
    previous_matches = list(_MARKDOWN_HEADING.finditer(previous))
    continuation_matches = list(_MARKDOWN_HEADING.finditer(continuation))
    result = continuation
    if previous_matches and continuation_matches:
        prior_sections: dict[str, list[str]] = {}
        for index, match in enumerate(previous_matches):
            end = (
                previous_matches[index + 1].start()
                if index + 1 < len(previous_matches)
                else len(previous)
            )
            key = _heading_key(match.group())
            body = _normalized_paragraph(previous[match.end() : end])
            if key:
                prior_sections.setdefault(key, []).append(body)

        preamble = continuation[: continuation_matches[0].start()].strip()
        kept: list[str] = [preamble] if preamble else []
        for index, match in enumerate(continuation_matches):
            end = (
                continuation_matches[index + 1].start()
                if index + 1 < len(continuation_matches)
                else len(continuation)
            )
            section = continuation[match.start() : end]
            prior_bodies = prior_sections.get(_heading_key(match.group()), [])
            new_body = _normalized_paragraph(section[match.end() - match.start() :])
            duplicate = any(
                _near_duplicate_text(old_body, new_body, _REPEATED_SECTION_SIMILARITY)
                for old_body in prior_bodies
            )
            if not duplicate:
                kept.append(section.rstrip())
        result = "\n\n".join(kept)

    prior_paragraphs = [
        _normalized_paragraph(part)
        for part in re.split(r"\n\s*\n", previous)
        if len(_normalized_paragraph(part)) >= 120
    ]
    paragraphs = re.split(r"\n\s*\n", result)
    kept_paragraphs: list[str] = []
    removed_paragraph = False
    for paragraph in paragraphs:
        normalized = _normalized_paragraph(paragraph)
        duplicate = len(normalized) >= 120 and any(
            _near_duplicate_text(old, normalized, _REPEATED_PARAGRAPH_SIMILARITY)
            for old in prior_paragraphs
        )
        if duplicate:
            removed_paragraph = True
        else:
            kept_paragraphs.append(paragraph.strip())
    if removed_paragraph:
        result = "\n\n".join(part for part in kept_paragraphs if part)
    return result

__all__ = [
    "AgentSignal",
    "AgentSignalKind",
    "Observation",
    "PrimaryLoop",
    "PrimaryOutcome",
    "PrimaryPhase",
    "PrimaryTurn",
    "SteeringChannel",
    "VerificationRequest",
    "VerificationResult",
]


class PrimaryPhase(StrEnum):
    OBSERVE = "observe"
    ACT = "act"
    TOOL = "tool"
    TEST = "test"
    REPORT = "report"


class AgentSignalKind(StrEnum):
    """What one chunk from the model turn means.

    The adapter that owns provider syntax (``<tool_call>``, ``<think>``, …)
    translates it into these; the loop never parses provider markup itself.
    """

    TOKEN = "token"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    #: The agent asks for a subagent. Subject to the spawn policy.
    DELEGATE = "delegate"
    ERROR = "error"


#: Tools whose completion means the project was actually inspected or changed,
#: as opposed to the model merely producing text. Drives
#: ``TIME_TO_FIRST_USEFUL_WORK``.
READ_TOOLS = frozenset(
    {
        "read_file", "read_file_absolute", "read_multiple_files",
        "read_multiple_files_absolute", "list_dir", "list_dir_absolute",
        "search_codebase", "search_in_files", "search_files_absolute",
        "search_symbols", "get_file_info", "get_file_info_absolute",
    }
)
WRITE_TOOLS = frozenset(
    {
        "write_file", "write_file_absolute", "append_file", "edit_file",
        "apply_patch", "delete_file", "scaffold_project", "format_code",
    }
)
COMMAND_TOOLS = frozenset({"run_shell", "execute_code"})
TEST_TOOLS = frozenset({"run_tests", "run_lint", "type_check"})
#: Plan/bookkeeping tools: real work for a long autonomous run (the todo list
#: is persisted state, not narration), but they emit PLAN_UPDATED, not file
#: or command events. ``sequential_thinking`` is useful work without a plan
#: payload.
PLAN_TOOLS = frozenset({"todo_write", "todo_list", "sequential_thinking"})


@dataclass(frozen=True)
class AgentSignal:
    kind: AgentSignalKind
    text: str = ""
    tool_name: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    ok: bool = True


@dataclass
class Observation:
    """What the run knows before it acts (or after a tool round)."""

    summary: str = ""
    facts: dict[str, Any] = field(default_factory=dict)
    #: Number of real files/directories inspected to produce this snapshot.
    #: Zero means nothing was read, and the loop will not claim useful work.
    files_inspected: int = 0


@dataclass
class PrimaryTurn:
    """The input to one observe→act→test cycle."""

    query: str
    cycle: int = 1
    observation: Observation | None = None
    #: Verbatim feedback from the previous cycle's failed verification.
    feedback: str = ""
    project_path: str = ""
    session_id: str = ""
    #: Guidance the user typed while the run was in flight.
    guidance: tuple[str, ...] = ()
    #: Assistant text already streamed to the user before a follow-up cycle.
    previous_answer: str = ""


@dataclass
class VerificationRequest:
    turn: PrimaryTurn
    changed_files: tuple[str, ...] = ()
    commands_run: int = 0
    forced: bool = False


@dataclass
class VerificationResult:
    ran: bool = False
    ok: bool = True
    summary: str = ""
    command: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubagentResult:
    name: str
    status: str
    output: str = ""
    error: str = ""


@dataclass
class PrimaryOutcome:
    run_id: str
    answer: str = ""
    cycles: int = 0
    changed_files: tuple[str, ...] = ()
    verification: VerificationResult = field(default_factory=VerificationResult)
    subagents: tuple[SubagentResult, ...] = ()
    declined_subagents: tuple[str, ...] = ()
    stopped: bool = False
    interrupted: bool = False
    failed: bool = False
    error: str = ""
    telemetry: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return not self.failed and not self.stopped and not self.interrupted


class SteeringChannel:
    """Cooperative STOP / CONTINUE, checked at every loop boundary.

    STOP is a pause, not a kill: the run stops at the next checkpoint and
    waits. CONTINUE resumes it with everything it had already learned, which
    is the whole point of a persistent primary agent — a restart would throw
    the observation away. ``abort`` is the hard variant for a client that
    disconnected.
    """

    MAX_GUIDANCE_MESSAGES = 3

    def __init__(self, *, pause_timeout: float = 300.0) -> None:
        self._paused = asyncio.Event()
        self._resumed = asyncio.Event()
        self._resumed.set()
        self._aborted = asyncio.Event()
        self._guidance: list[str] = []
        self._guidance_count = 0
        self._closed = False
        self.pause_timeout = pause_timeout

    # -- user actions --------------------------------------------------
    def stop(self) -> None:
        self._paused.set()
        self._resumed.clear()

    def cont(self, guidance: str = "") -> None:
        if guidance.strip():
            self.steer(guidance)
        self._paused.clear()
        self._resumed.set()

    def abort(self) -> None:
        self._aborted.set()
        self._resumed.set()

    def steer(self, guidance: str) -> bool:
        """Queue bounded user guidance while this run can still consume it."""
        cleaned = guidance.strip()
        if not cleaned or self._closed or self._guidance_count >= self.MAX_GUIDANCE_MESSAGES:
            return False
        self._guidance.append(cleaned)
        self._guidance_count += 1
        return True

    def close(self) -> None:
        """Reject steering once the run leaves its last work checkpoint."""
        self._closed = True

    @property
    def has_guidance(self) -> bool:
        return bool(self._guidance) and not self._closed

    # -- loop side -----------------------------------------------------
    @property
    def stop_requested(self) -> bool:
        return self._paused.is_set()

    @property
    def aborted(self) -> bool:
        return self._aborted.is_set()

    def drain_guidance(self) -> tuple[str, ...]:
        pending = tuple(self._guidance)
        self._guidance.clear()
        return pending

    async def wait_if_paused(self) -> bool:
        """Block while STOP is in effect. False means the run must end."""
        if self._aborted.is_set():
            return False
        if not self._paused.is_set():
            return True
        try:
            await asyncio.wait_for(self._resumed.wait(), timeout=self.pause_timeout)
        except TimeoutError:
            self._aborted.set()
            return False
        return not self._aborted.is_set()


StreamFactory = Callable[[PrimaryTurn], AsyncIterator[AgentSignal]]
Observer = Callable[[PrimaryTurn], Awaitable[Observation] | Observation]
Verifier = Callable[[VerificationRequest], Awaitable[VerificationResult] | VerificationResult]
SubagentRunner = Callable[[SubagentProposal], Awaitable[str]]


class PrimaryLoop:
    """One persistent agent, driven through observe → act → tool → test → report."""

    def __init__(
        self,
        *,
        run_id: str,
        query: str,
        stream: StreamFactory,
        observe: Observer | None = None,
        verify: Verifier | None = None,
        run_subagent: SubagentRunner | None = None,
        events: RunEventStream | None = None,
        telemetry: RunTelemetry | None = None,
        spawn_policy: SpawnPolicy | None = None,
        steering: SteeringChannel | None = None,
        session_id: str = "",
        project_path: str = "",
        agent_id: str = "NEXUS",
        max_cycles: int = 2,
        max_parallel_subagents: int = 3,
        experience_bus: Any = None,
        run_timeout: float = 0,
        heartbeat_interval_seconds: float | None = None,
        skill_activations: list[dict[str, Any]] | None = None,
        interruption_check: Callable[[], str | None] | None = None,
        reasoning_visibility: ReasoningVisibility | None = None,
    ) -> None:
        if max_cycles < 1:
            raise ValueError("max_cycles must be >= 1")
        self.run_id = run_id
        self.query = query
        self.session_id = session_id
        self.project_path = project_path
        self.agent_id = agent_id
        self.max_cycles = max_cycles
        self.events = events or RunEventStream(run_id)
        self.telemetry = telemetry or RunTelemetry(run_id=run_id)
        self.spawn_policy = spawn_policy or SpawnPolicy(
            max_parallel_workers=max_parallel_subagents
        )
        self.steering = steering or SteeringChannel()
        self._stream = stream
        self._observe = observe
        self._verify = verify
        self._run_subagent = run_subagent
        self._max_parallel_subagents = max_parallel_subagents
        self._experience_bus = experience_bus
        self._run_timeout = run_timeout
        self._heartbeat_interval = (
            _configured_heartbeat_interval()
            if heartbeat_interval_seconds is None
            else max(0.0, float(heartbeat_interval_seconds))
        )
        self.skill_activations = list(skill_activations or [])
        self._interruption_check = interruption_check
        # ``None`` means "read NEXUS_REASONING_VISIBILITY at emit time"; the
        # route pins it to the user's ``thinking_strength`` when it can.
        self._reasoning_visibility = reasoning_visibility
        self._reasoning_parts: list[str] = []

        self.outcome = PrimaryOutcome(run_id=run_id)
        self._answer_parts: list[str] = []
        self._changed_files: list[str] = []
        self._subagent_results: list[SubagentResult] = []
        self._declined: list[str] = []
        self._phase = PrimaryPhase.OBSERVE
        self._failure_event_emitted = False

    @property
    def reasoning_visibility(self) -> ReasoningVisibility:
        """Effective policy for this run (env-resolved when not pinned)."""
        if self._reasoning_visibility is not None:
            return self._reasoning_visibility
        return reasoning_visibility()

    @property
    def reasoning_text(self) -> str:
        """Every reasoning label this run surfaced, joined for token counting."""
        return join_collected_reasoning(self._reasoning_parts)

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------
    async def run(self) -> AsyncIterator[RuntimeEvent]:
        """Drive the turn, yielding every event in ``(run_id, seq)`` order."""
        emitted: list[RuntimeEvent] = []
        self.events_sink = emitted  # noqa: B010 - inspected by tests

        def emit(event_type: RuntimeEventType, **payload: Any) -> RuntimeEvent:
            event = self.events.emit(
                event_type,
                agent_id=self.agent_id,
                task_id=payload.pop("task_id", ""),
                **payload,
            )
            emitted.append(event)
            return event

        started = time.monotonic()
        yield emit(
            RuntimeEventType.RUN_STARTED,
            query=self.query,
            project_path=self.project_path,
            session_id=self.session_id,
            max_cycles=self.max_cycles,
        )
        if self.skill_activations:
            names = ", ".join(
                f"{item['name']} v{item['version']}" for item in self.skill_activations
            )
            reasons = "; ".join(
                f"{item['name']}: {item['reason']}" for item in self.skill_activations
            )
            yield emit(
                RuntimeEventType.STATUS_UPDATE,
                phase="skills",
                label=f"Skills ativadas: {names}",
                reason="skills_selected_for_task",
                skills=self.skill_activations,
                activation_reason=reasons,
            )

        # --- experience bus: start trace ----------------------------
        bus = self._experience_bus
        if bus is None:
            bus = self._get_experience_bus()
        trace = None
        if bus is not None and not os.environ.get("NEXUS_EXPERIENCE_OFF"):
            try:
                trace = bus.start_trace(
                    prompt=self.query,
                    session_id=self.session_id,
                    version_tags={
                        f"skill:{item['name']}": str(item["version"])
                        for item in self.skill_activations
                    },
                )
            except Exception:
                logger.debug("experience_bus.start_trace failed", exc_info=True)

        observation: Observation | None = None
        feedback = ""
        previous_answer = ""
        cycle = 0
        try:
            # Mid-run guidance earns a bounded follow-up model turn even when
            # triage chose a one-cycle conversational/no-project run.
            while cycle < self.max_cycles or self.steering.has_guidance:
                cycle += 1
                self.outcome.cycles = cycle
                guidance = self.steering.drain_guidance()
                turn = PrimaryTurn(
                    query=self.query,
                    cycle=cycle,
                    observation=observation,
                    feedback=feedback,
                    project_path=self.project_path,
                    session_id=self.session_id,
                    guidance=guidance,
                    previous_answer=previous_answer,
                )
                for hint in guidance:
                    yield emit(RuntimeEventType.USER_STEERING, guidance=hint, cycle=cycle)

                # -- 1. OBSERVE -------------------------------------------
                async for event in self._checkpoint(emit, "observe"):
                    yield event
                if self._must_stop():
                    break
                if self._observe is not None:
                    self._phase = PrimaryPhase.OBSERVE
                    self.telemetry.enter_phase(RunPhase.CONTEXT_BUILD)
                    self.telemetry.blocked_on = BlockedOn.WORKING
                    observation = await self._call_observer(turn)
                    turn.observation = observation
                    if observation.files_inspected:
                        # Real inspection of the project: this is useful work and
                        # is recorded as such, before the provider has replied.
                        self.telemetry.mark_file_read(observation.files_inspected)
                        yield emit(
                            RuntimeEventType.FILE_READ,
                            count=observation.files_inspected,
                            phase=PrimaryPhase.OBSERVE.value,
                        )
                    yield emit(
                        RuntimeEventType.STATUS_UPDATE,
                        phase=PrimaryPhase.OBSERVE.value,
                        cycle=cycle,
                        label=observation.summary or "a observar o projeto",
                        facts=observation.facts,
                        blocked_on=self.telemetry.blocked_on.value,
                    )
                else:
                    # Conversational turns have no project observer by design.
                    # Keep that absence out of both the model prompt and the
                    # execution timeline instead of reporting it as a failed step.
                    observation = None
                    turn.observation = None

                # -- 2/3. ACT + TOOL --------------------------------------
                self._phase = PrimaryPhase.ACT
                self.telemetry.enter_phase(RunPhase.MODEL_REQUEST)
                self.telemetry.blocked_on = BlockedOn.WAITING_MODEL
                yield emit(RuntimeEventType.MESSAGE_STARTED, cycle=cycle)
                async for event in self._drive_model(turn, emit):
                    yield event
                if self._must_stop() or self.outcome.failed:
                    break

                # -- 4. TEST ----------------------------------------------
                self._phase = PrimaryPhase.TEST
                async for event in self._checkpoint(emit, "test"):
                    yield event
                if self._must_stop():
                    break
                result = await self._run_verification(turn, emit)
                if self._verify is not None:
                    yield emit(
                        RuntimeEventType.TEST_RESULT,
                        ok=result.ok,
                        ran=result.ran,
                        summary=result.summary,
                        command=result.command,
                        details=result.details,
                        cycle=cycle,
                    )
                self.outcome.verification = result

                if self.steering.has_guidance:
                    # Treat the user's intervention as a new instruction, not
                    # as another ordinary assistant turn or a verification
                    # retry. It is consumed at the next loop boundary.
                    feedback = ""
                    answer_so_far = "".join(self._answer_parts).strip()
                    previous_answer = _bounded_previous_answer(answer_so_far)
                    yield emit(
                        RuntimeEventType.STATUS_UPDATE,
                        phase="steering",
                        label="orientação recebida; o NEXUS vai incorporá-la",
                        cycle=cycle,
                    )
                    continue

                if result.ran and not result.ok and cycle < self.max_cycles:
                    # The back-edge of the loop: a failed verification is a new
                    # observation, not a terminal state.
                    feedback = (
                        f"A verificação falhou no ciclo {cycle}: {result.summary}\n"
                        f"Comando: {result.command or 'n/d'}\n"
                        "Corrige a causa e volta a verificar."
                    )
                    previous_answer = _bounded_previous_answer(
                        "".join(self._answer_parts).strip()
                    )
                    self.telemetry.mark_retry()
                    yield emit(
                        RuntimeEventType.RECOVERY,
                        reason="verification_failed",
                        cycle=cycle,
                        detail=result.summary,
                    )
                    continue
                if result.ran and not result.ok:
                    # Reaching the cycle limit with a red verification is still
                    # a failed run.  Never turn an exhausted repair loop into a
                    # false RUN_COMPLETED merely because the model produced text.
                    self.outcome.failed = True
                    self.outcome.error = (
                        "A verificação final falhou: "
                        f"{result.summary or 'resultado sem detalhes'}"
                    )
                break

            # Close before reporting: a late POST must not be accepted after
            # the final model/verification checkpoint has already passed.
            self.steering.close()

            # -- 5. REPORT ------------------------------------------------
            self._phase = PrimaryPhase.REPORT
            self.telemetry.enter_phase(RunPhase.FINISHED)
            raw_answer = "".join(self._answer_parts).strip()
            corrections = self._unsupported_claims(raw_answer)
            if corrections:
                # The run already MEASURED that these statements are false.
                # Delivering them unchallenged is how "corri os testes (4
                # passed)" reached the user in a run whose own verification
                # said 0 passed / 1 failed (audit 2026-08-16, P8).
                yield emit(
                    RuntimeEventType.STATUS_UPDATE,
                    phase=PrimaryPhase.REPORT.value,
                    label="afirmações não suportadas por evidência",
                    claims=list(corrections),
                )
                notice = (
                    "\n\n> ⚠️ **Verificação do próprio NEXUS** — as afirmações "
                    "seguintes não são suportadas pela evidência medida "
                    "nesta execução:\n"
                    + "\n".join(f"> - {item}" for item in corrections)
                )
                # Emitted as a delta, not only appended to the stored answer:
                # a correction the user never sees corrects nothing.
                yield emit(RuntimeEventType.MESSAGE_DELTA, text=notice)
                raw_answer = f"{raw_answer}{notice}"
            self.outcome.answer = raw_answer
            self.outcome.changed_files = tuple(dict.fromkeys(self._changed_files))
            self.outcome.subagents = tuple(self._subagent_results)
            self.outcome.declined_subagents = tuple(self._declined)
            self.telemetry.finish()
            self.outcome.telemetry = self.telemetry.snapshot()

            if not self.outcome.stopped and not self.outcome.failed and not self.outcome.answer:
                self.outcome.failed = True
                self.outcome.error = (
                    "O provider terminou a execução sem uma resposta visível."
                )
            if not self.outcome.stopped and not self.outcome.failed:
                try:
                    interruption_reason = (
                        self._interruption_check() if self._interruption_check else None
                    )
                    if interruption_reason:
                        self.outcome.interrupted = True
                        self.outcome.error = interruption_reason
                except Exception:
                    logger.debug("completion status check failed", exc_info=True)

            # --- experience bus: complete trace --------------------
            if trace is not None and bus is not None:
                try:
                    bus.record_trajectory(
                        trace,
                        agent=self.agent_id,
                        action=(
                            "run_completed"
                            if self.outcome.succeeded
                            else "run_interrupted"
                            if self.outcome.interrupted
                            else "run_failed"
                        ),
                        observation=f"Run ended after {cycle} cycle(s).",
                        success=self.outcome.succeeded,
                        error=self.outcome.error or None,
                        input_data={"cycles": cycle},
                    )
                except Exception:
                    logger.debug(
                        "experience_bus.record_trajectory failed",
                        exc_info=True,
                    )
                try:
                    bus.complete(
                    trace,
                    success=(
                        not self.outcome.failed
                        and not self.outcome.stopped
                        and not self.outcome.interrupted
                    ),
                        output=self.outcome.answer or "",
                        files_modified=list(self.outcome.changed_files),
                        error=self.outcome.error or None,
                        latency_ms=int((time.monotonic() - started) * 1000),
                    )
                except Exception:
                    logger.debug("experience_bus.complete failed", exc_info=True)

            if self.outcome.failed:
                if not self._failure_event_emitted:
                    yield emit(
                        RuntimeEventType.RUN_FAILED,
                        error=self.outcome.error or "A execução falhou sem uma mensagem técnica.",
                        telemetry=self.outcome.telemetry,
                    )
            elif self.outcome.stopped:
                yield emit(
                    RuntimeEventType.RUN_CANCELLED,
                    reason="stop_requested",
                    partial_answer=self.outcome.answer,
                    telemetry=self.outcome.telemetry,
                )
            elif self.outcome.interrupted:
                yield emit(
                    RuntimeEventType.RUN_INTERRUPTED,
                    reason=self.outcome.error or "A resposta foi interrompida.",
                    partial_answer=self.outcome.answer,
                    telemetry=self.outcome.telemetry,
                )
            else:
                yield emit(
                    RuntimeEventType.MESSAGE_COMPLETED,
                    content=self.outcome.answer,
                    cycles=self.outcome.cycles,
                )
                yield emit(
                    RuntimeEventType.RUN_COMPLETED,
                    changed_files=list(self.outcome.changed_files),
                    verification={
                        "ran": self.outcome.verification.ran,
                        "ok": self.outcome.verification.ok,
                        "summary": self.outcome.verification.summary,
                        "command": self.outcome.verification.command,
                    },
                    subagents=[
                        {"name": s.name, "status": s.status} for s in self.outcome.subagents
                    ],
                    declined_subagents=list(self.outcome.declined_subagents),
                    duration=time.monotonic() - started,
                    telemetry=self.outcome.telemetry,
                )
        except asyncio.CancelledError:
            self.steering.close()
            self.outcome.stopped = True
            self.outcome.answer = "".join(self._answer_parts).strip()
            self.outcome.changed_files = tuple(dict.fromkeys(self._changed_files))
            self.outcome.subagents = tuple(self._subagent_results)
            self.outcome.declined_subagents = tuple(self._declined)
            self.outcome.error = self.outcome.error or "Execução cancelada."
            self.telemetry.finish()
            self.outcome.telemetry = self.telemetry.snapshot()
            if trace is not None and bus is not None:
                try:
                    bus.record_trajectory(
                        trace,
                        agent=self.agent_id,
                        action="run_cancelled",
                        observation=f"Run cancelled after {cycle} cycle(s).",
                        success=False,
                        error=self.outcome.error,
                        input_data={"cycles": cycle},
                    )
                    bus.complete(
                        trace,
                        success=False,
                        output=self.outcome.answer,
                        files_modified=list(self.outcome.changed_files),
                        error=self.outcome.error,
                        latency_ms=int((time.monotonic() - started) * 1000),
                    )
                except Exception:
                    logger.debug(
                        "experience_bus cancellation capture failed", exc_info=True
                    )
            cancelled_event = self.events.emit(
                RuntimeEventType.RUN_CANCELLED,
                agent_id=self.agent_id,
                reason="client_cancelled",
                partial_answer=self.outcome.answer,
                telemetry=self.outcome.telemetry,
            )
            self.events_sink.append(cancelled_event)
            raise
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            self.steering.close()
            logger.exception("primary loop failed for run %s", self.run_id)
            self.outcome.failed = True
            self.outcome.error = f"{type(exc).__name__}: {exc}"
            self.telemetry.finish()
            self.outcome.telemetry = self.telemetry.snapshot()
            yield emit(
                RuntimeEventType.RUN_FAILED,
                error=self.outcome.error,
                telemetry=self.outcome.telemetry,
            )

    # ------------------------------------------------------------------
    # phases
    # ------------------------------------------------------------------
    async def _drive_model(
        self, turn: PrimaryTurn, emit: Callable[..., RuntimeEvent]
    ) -> AsyncIterator[RuntimeEvent]:
        """Consume one model turn, executing its tool signals as they arrive."""
        proposals: list[SubagentProposal] = []
        buffer_followup = bool(
            turn.previous_answer and turn.guidance and not turn.project_path
        )
        followup_tokens: list[str] = []
        stream = self._stream(turn)
        _timeout = self._run_timeout
        _retried = False
        _has_output = False
        pending_signal: asyncio.Task[AgentSignal] | None = None
        pending_since = 0.0
        try:
            while True:
                try:
                    if pending_signal is None:
                        pending_since = time.monotonic()
                        pending_signal = asyncio.create_task(stream.__anext__())
                    elapsed = time.monotonic() - pending_since
                    remaining = _timeout - elapsed if _timeout and _timeout > 0 else None
                    if remaining is not None and remaining <= 0:
                        raise TimeoutError

                    wait_for = self._heartbeat_interval or remaining
                    if wait_for is not None and remaining is not None:
                        wait_for = min(wait_for, remaining)
                    if wait_for is None:
                        done, _ = await asyncio.wait({pending_signal})
                    else:
                        done, _ = await asyncio.wait({pending_signal}, timeout=wait_for)
                    if not done:
                        elapsed = time.monotonic() - pending_since
                        if remaining is not None and elapsed >= _timeout:
                            raise TimeoutError
                        if self._heartbeat_interval > 0:
                            yield emit(
                                RuntimeEventType.HEARTBEAT,
                                phase=self._phase.value,
                                blocked_on=self.telemetry.blocked_on.value,
                                waiting_seconds=round(elapsed, 2),
                            )
                        continue
                    signal = pending_signal.result()
                    pending_signal = None
                except TimeoutError:
                    if pending_signal is not None:
                        pending_signal.cancel()
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await pending_signal
                        pending_signal = None
                    self.outcome.failed = True
                    self.outcome.error = (
                        f"limite de {_timeout}s excedido no provider."
                    )
                    self.telemetry.finish()
                    self.outcome.telemetry = self.telemetry.snapshot()
                    break
                except StopAsyncIteration:
                    break
                # A STOP that arrived between two signals is honoured before
                # another token is spent — and it is *announced* before the
                # loop blocks. Blocking first would show the user a frozen
                # stream with no explanation, which is the failure mode this
                # whole phase exists to remove.
                if self.steering.stop_requested and not self.steering.aborted:
                    yield emit(
                        RuntimeEventType.STATUS_UPDATE,
                        phase=self._phase.value,
                        label="pausado a pedido do utilizador",
                        blocked_on=BlockedOn.WAITING_USER.value,
                    )
                if not await self.steering.wait_if_paused():
                    self.outcome.stopped = True
                    break

                if buffer_followup and signal.kind is AgentSignalKind.TOKEN and signal.text:
                    # Keep the already-visible answer intact while we check
                    # whether this model turn regenerated sections the user
                    # has already seen. The follow-up text is emitted once,
                    # after the duplicate-section filter runs below.
                    self.telemetry.mark_first_token()
                    followup_tokens.append(signal.text)
                    _has_output = True
                    continue

                # --- transient error retry logic (before failure check) --
                if (
                    signal.kind is AgentSignalKind.ERROR
                    and not signal.ok
                    and not _has_output
                    and not _retried
                ):
                    reason = signal.payload.get("reason", "")
                    if reason in ("rate_limit", "upstream_error", "timeout"):
                        _retried = True
                        self.telemetry.mark_retry()
                        aclose = getattr(stream, "aclose", None)
                        if aclose is not None:
                            with contextlib.suppress(Exception):
                                await aclose()
                        stream = self._stream(turn)
                        continue

                for event in self._handle_signal(signal, turn, emit, proposals):
                    yield event
                if self.outcome.failed:
                    break

                if signal.kind is AgentSignalKind.TOKEN and signal.text:
                    _has_output = True
        finally:
            if pending_signal is not None and not pending_signal.done():
                pending_signal.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await pending_signal
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(Exception):
                    await aclose()

        if followup_tokens and not self.outcome.failed and not self.outcome.stopped:
            prior_answer = "".join(self._answer_parts).strip()
            continuation = _remove_repeated_markdown_sections(
                prior_answer, "".join(followup_tokens)
            )
            if not continuation.strip():
                continuation = (
                    "\n\n> A orientação recebida não acrescentou conteúdo novo; "
                    "a resposta anterior mantém-se."
                )
            elif prior_answer and not continuation.startswith(("\n", " ", "\t")):
                continuation = f"\n\n{continuation}"
            self._answer_parts.append(continuation)
            yield emit(RuntimeEventType.MESSAGE_DELTA, text=continuation)

        if proposals and not self.outcome.stopped and not self.outcome.failed:
            async for event in self._delegate(proposals, emit):
                yield event

    def _handle_signal(
        self,
        signal: AgentSignal,
        turn: PrimaryTurn,
        emit: Callable[..., RuntimeEvent],
        proposals: list[SubagentProposal],
    ) -> list[RuntimeEvent]:
        events: list[RuntimeEvent] = []
        kind = signal.kind

        if kind is AgentSignalKind.TOKEN:
            if signal.text:
                self.telemetry.mark_first_token()
                self._answer_parts.append(signal.text)
                events.append(emit(RuntimeEventType.MESSAGE_DELTA, text=signal.text))
            return events

        if kind is AgentSignalKind.THINKING:
            # Operational transparency only: a short label, never the private
            # reasoning transcript. The STATUS_UPDATE is emitted FIRST and
            # unchanged — phase/telemetry consumers and the existing contract
            # depend on it — and the THINKING event follows it with the SAME
            # bounded text so the on-screen reasoning panel has something to
            # render. Both are bounded by ``reasoning.bound_label``.
            label = reasoning_label_or_default(signal.text or "a raciocinar")
            events.append(
                emit(
                    RuntimeEventType.STATUS_UPDATE,
                    phase=PrimaryPhase.ACT.value,
                    label=label[:160],
                    blocked_on=BlockedOn.WAITING_MODEL.value,
                )
            )
            visible = bound_reasoning_text(
                signal.text or "a raciocinar",
                visibility=self.reasoning_visibility,
            )
            if visible:
                # Only the public approach is recorded; ``signal.payload`` may
                # carry provider internals and never leaves the process.
                self._reasoning_parts.append(visible)
                events.append(
                    emit(
                        RuntimeEventType.THINKING,
                        text=visible,
                        label=label[:160],
                        visibility=self.reasoning_visibility.value,
                    )
                )
            return events

        if kind is AgentSignalKind.TOOL_CALL:
            self._phase = PrimaryPhase.TOOL
            self.telemetry.enter_phase(RunPhase.EXECUTING)
            self.telemetry.blocked_on = BlockedOn.WAITING_TOOL
            useful = signal.tool_name in (
                READ_TOOLS | WRITE_TOOLS | COMMAND_TOOLS | TEST_TOOLS | PLAN_TOOLS
            )
            self.telemetry.mark_tool_call(useful=useful)
            events.append(
                emit(
                    RuntimeEventType.TOOL_STARTED,
                    tool=signal.tool_name,
                    args=signal.payload,
                    cycle=turn.cycle,
                )
            )
            if signal.tool_name in COMMAND_TOOLS:
                events.append(
                    emit(
                        RuntimeEventType.COMMAND_STARTED,
                        tool=signal.tool_name,
                        command=str(
                            signal.payload.get("command")
                            or signal.payload.get("code")
                            or ""
                        ),
                        cycle=turn.cycle,
                    )
                )
            elif signal.tool_name in TEST_TOOLS:
                events.append(
                    emit(
                        RuntimeEventType.TEST_STARTED,
                        tool=signal.tool_name,
                        args=signal.payload,
                        cycle=turn.cycle,
                    )
                )
            return events

        if kind in (AgentSignalKind.TOOL_RESULT, AgentSignalKind.TOOL_ERROR):
            ok = signal.ok and kind is AgentSignalKind.TOOL_RESULT
            name = signal.tool_name
            if ok:
                events.extend(self._record_tool_effect(name, signal.payload, emit))
            else:
                self.telemetry.mark_agent_failure()
            events.append(
                emit(
                    RuntimeEventType.TOOL_COMPLETED if ok else RuntimeEventType.TOOL_FAILED,
                    tool=name,
                    ok=ok,
                    result=signal.payload,
                    error=signal.text,
                    cycle=turn.cycle,
                )
            )
            # Back to observation: the tool result is the new evidence the
            # next model step reasons over.
            self._phase = PrimaryPhase.OBSERVE
            self.telemetry.blocked_on = BlockedOn.WORKING
            return events

        if kind is AgentSignalKind.DELEGATE:
            proposal = _proposal_from_payload(signal.payload)
            if proposal is None:
                return events
            decision = self.spawn_policy.evaluate(proposal)
            if decision.verdict is SpawnVerdict.SPAWN or decision.verdict is SpawnVerdict.QUEUE:
                proposals.append(proposal)
                events.append(
                    emit(
                        RuntimeEventType.STATUS_UPDATE,
                        phase=PrimaryPhase.ACT.value,
                        label=f"delegação aceite: {proposal.name}",
                        verdict=decision.verdict.value,
                        reason=decision.reason,
                    )
                )
            else:
                self.telemetry.mark_subagent_declined()
                self._declined.append(proposal.name)
                events.append(
                    emit(
                        RuntimeEventType.STATUS_UPDATE,
                        phase=PrimaryPhase.ACT.value,
                        label=f"o agente primário trata isto: {proposal.name}",
                        verdict=decision.verdict.value,
                        reason=decision.reason,
                    )
                )
            return events

        if kind is AgentSignalKind.ERROR:
            if signal.payload.get("reason") == "provider_token_limit":
                notice = signal.text.strip() or (
                    "A resposta foi interrompida pelo limite de tokens do provider; "
                    "o estado ficou incompleto e pode ser continuado numa nova mensagem."
                )
                self.outcome.interrupted = True
                self._answer_parts.append(f"\n\n⚠️ {notice}")
                events.append(
                    emit(
                        RuntimeEventType.STATUS_UPDATE,
                        label=notice,
                        reason="provider_token_limit",
                        finish_reason=signal.payload.get("finish_reason"),
                    )
                )
                events.append(
                    emit(
                        RuntimeEventType.PROVIDER_RESULT,
                        summary=notice,
                        usage=signal.payload.get("usage") or {},
                    )
                )
                return events
            self.telemetry.mark_agent_failure()
            self.outcome.failed = True
            self.outcome.error = signal.text.strip() or "O provider devolveu um erro sem detalhes."
            self._failure_event_emitted = True
            events.append(emit(RuntimeEventType.RUN_FAILED, error=self.outcome.error))
        return events

    def _record_tool_effect(
        self, name: str, payload: dict[str, Any], emit: Callable[..., RuntimeEvent]
    ) -> list[RuntimeEvent]:
        """Translate a successful tool result into measured, honest progress."""
        events: list[RuntimeEvent] = []
        if name in READ_TOOLS:
            count = int(payload.get("files_read") or 1)
            self.telemetry.mark_file_read(count)
            events.append(emit(RuntimeEventType.FILE_READ, tool=name, count=count))
        elif name in WRITE_TOOLS:
            changed = _paths_from_payload(payload)
            self._changed_files.extend(changed)
            self.telemetry.mark_file_changed(max(1, len(changed)))
            events.append(
                emit(RuntimeEventType.FILE_CHANGED, tool=name, paths=list(changed))
            )
        elif name in COMMAND_TOOLS:
            self.telemetry.mark_command()
            events.append(
                emit(
                    RuntimeEventType.COMMAND_COMPLETED,
                    tool=name,
                    command=str(payload.get("command") or ""),
                    exit_code=payload.get("exit_code"),
                )
            )
        elif name in TEST_TOOLS:
            self.telemetry.mark_test_run()
            events.append(
                emit(
                    RuntimeEventType.TEST_RESULT,
                    tool=name,
                    ok=bool(payload.get("ok", True)),
                    summary=str(payload.get("summary") or ""),
                )
            )
        elif name in PLAN_TOOLS and name != "sequential_thinking":
            # The todo handlers return the full list under "todos"; surface it
            # as a plan update so the UI (and the session replay) can render
            # the current plan without re-reading the todo file. execute_tool
            # wraps handler output as {ok, result}, while legacy streams may
            # already pass the handler payload at the root.
            result_payload = payload.get("result")
            todo_payload = (
                result_payload
                if isinstance(result_payload, dict)
                and isinstance(result_payload.get("todos"), list)
                else payload
            )
            todos = todo_payload.get("todos")
            if isinstance(todos, list):
                events.append(emit(RuntimeEventType.PLAN_UPDATED, tool=name, todos=todos))
        return events

    async def _delegate(
        self, proposals: Sequence[SubagentProposal], emit: Callable[..., RuntimeEvent]
    ) -> AsyncIterator[RuntimeEvent]:
        """Run approved proposals through the deterministic scheduler.

        Dependencies are honoured (a dependent never starts before its
        dependency has COMPLETED), overlapping write scopes are serialised,
        and independent proposals run in real parallel up to the cap.
        """
        if self._run_subagent is None:
            for proposal in proposals:
                self._declined.append(proposal.name)
            return

        self.telemetry.blocked_on = BlockedOn.WAITING_WORKER
        live = 0
        by_name = {proposal.name: proposal for proposal in proposals}
        name_to_id: dict[str, str] = {}
        tasks: list[RuntimeTask] = []
        for proposal in proposals:
            task = RuntimeTask(
                name=proposal.name,
                run=self._subagent_body(proposal),
                write_scope=proposal.write_scope,
                read_scope=proposal.read_scope,
                agent_id=proposal.name,
            )
            name_to_id[proposal.name] = task.task_id
            tasks.append(task)
        for task in tasks:
            deps = by_name[task.name].depends_on
            task.depends_on = frozenset(
                name_to_id[dep] for dep in deps if dep in name_to_id
            )

        queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue()

        def task_context(task: RuntimeTask) -> dict[str, Any]:
            proposal = by_name.get(task.name)
            return {
                "name": task.name,
                "objective": proposal.objective if proposal is not None else None,
                "depends_on": sorted(task.depends_on),
            }

        def on_status(task: RuntimeTask) -> None:
            nonlocal live
            if task.status is RuntimeTaskStatus.RUNNING:
                live += 1
                self.telemetry.mark_subagent_started(live)
                queue.put_nowait(
                    self.events.emit(
                        RuntimeEventType.SUBAGENT_STARTED,
                        agent_id=task.agent_id,
                        task_id=task.task_id,
                        **task_context(task),
                    )
                )
            elif task.status is RuntimeTaskStatus.WAITING:
                queue.put_nowait(
                    self.events.emit(
                        RuntimeEventType.WAITING_DEPENDENCY,
                        agent_id=task.agent_id,
                        task_id=task.task_id,
                        **task_context(task),
                    )
                )
            elif task.status in {
                RuntimeTaskStatus.COMPLETED,
                RuntimeTaskStatus.FAILED,
                RuntimeTaskStatus.BLOCKED,
                RuntimeTaskStatus.CANCELLED,
            }:
                live = max(0, live - 1)
                queue.put_nowait(
                    self.events.emit(
                        RuntimeEventType.SUBAGENT_COMPLETED,
                        agent_id=task.agent_id,
                        task_id=task.task_id,
                        **task_context(task),
                        status=task.status.value,
                        error=task.error,
                    )
                )

        scheduler = RuntimeScheduler(
            max_parallel=self._max_parallel_subagents, on_status=on_status
        )
        cancel = asyncio.Event()
        runner = asyncio.create_task(scheduler.run(tasks, cancel_event=cancel))
        try:
            while True:
                if runner.done() and queue.empty():
                    break
                if self.steering.aborted or self.steering.stop_requested:
                    cancel.set()
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.05)
                except TimeoutError:
                    continue
                yield event
        finally:
            report = await runner

        for task in report.tasks:
            proposal = by_name.get(task.name)
            if proposal is not None:
                self.spawn_policy.release(
                    proposal.name, completed=task.status is RuntimeTaskStatus.COMPLETED
                )
            self._subagent_results.append(
                SubagentResult(
                    name=task.name,
                    status=task.status.value,
                    output=str(task.result or ""),
                    error=task.error,
                )
            )
        self.telemetry.parallelism_peak = max(
            self.telemetry.parallelism_peak, report.peak_parallelism
        )
        self.telemetry.blocked_on = BlockedOn.WORKING

    def _subagent_body(
        self, proposal: SubagentProposal
    ) -> Callable[[RuntimeTask], Awaitable[Any]]:
        async def body(task: RuntimeTask) -> Any:
            self.spawn_policy.register(proposal)
            task.heartbeat()
            assert self._run_subagent is not None
            result = await self._run_subagent(proposal)
            task.heartbeat()
            return result

        return body

    #: Claim patterns paired with the measurement that would have to be true.
    #: Kept deliberately narrow: a false positive here would contradict a
    #: correct answer, which is worse than missing one exaggeration.
    _CLAIM_PATTERNS: tuple[tuple[str, str, str], ...] = (
        (
            "tests",
            r"(?:corri|executei|rodei|ran|executed)\s+(?:a\s+|os\s+|the\s+|todos\s+os\s+|all\s+)?"
            r"(?:su[ií]te\s+de\s+)?(?:testes|tests)|"
            r"(?:testes|tests)\s+(?:passaram|passed|pass)|"
            r"\b\d+\s+(?:passed|passaram)\b|"
            r"(?:todos\s+os\s+testes|all\s+tests)\s+(?:passam|passaram|pass)",
            "diz que executou testes, mas nenhum teste foi executado nesta execução",
        ),
        (
            "files_read",
            r"(?:analisei|li|revi|inspecionei|examinei|reviewed|analy[sz]ed|inspected)\s+"
            r"(?:todos\s+os\s+|cada\s+|all\s+(?:the\s+)?|every\s+)?"
            r"(?:ficheiros?|arquivos?|files?|c[oó]digo|codebase)",
            "diz que analisou ficheiros, mas nenhum ficheiro foi lido nesta execução",
        ),
        (
            "files_changed",
            r"(?:corrigi|alterei|modifiquei|apliquei|escrevi|criei|fixed|changed|applied|wrote|created)\s+"
            r"(?:o\s+|os\s+|a\s+|as\s+|the\s+)?(?:ficheiros?|arquivos?|files?|bugs?|patch|"
            r"corre[cç][ãa]o|corre[cç][õo]es)",
            "diz que alterou ficheiros, mas nenhuma escrita foi registada nesta execução",
        ),
        (
            "subagent",
            r"(?:sub-?agente|subagent|agente\s+\w+)\s+(?:est[áa]|ficou|continua|is)\s+"
            r"(?:a\s+trabalhar|em\s+background|running|working)",
            "diz que um sub-agente ficou a trabalhar, mas nenhuma delegação foi aceite",
        ),
    )

    def _unsupported_claims(self, answer: str) -> tuple[str, ...]:
        """Return the claims in ``answer`` that this run's telemetry refutes.

        This is not a style check. It compares what the answer *asserts* with
        what the loop actually measured — tests executed, files read, files
        changed, subagents started — and reports only the contradictions.
        """
        if not answer.strip():
            return ()
        text = " ".join(answer.split())
        verification_green = self.outcome.verification.ran and self.outcome.verification.ok
        evidence = {
            "tests": self.telemetry.tests_run > 0 and verification_green,
            "files_read": self.telemetry.files_read > 0,
            "files_changed": self.telemetry.files_changed > 0 or bool(self._changed_files),
            "subagent": bool(self._subagent_results),
        }
        found: list[str] = []
        for key, pattern, message in self._CLAIM_PATTERNS:
            if evidence.get(key):
                continue
            if re.search(pattern, text, re.IGNORECASE):
                found.append(message)
        return tuple(found)

    async def _run_verification(
        self, turn: PrimaryTurn, emit: Callable[..., RuntimeEvent]
    ) -> VerificationResult:
        """Verify before reporting. Never claim success that was not checked."""
        if self._verify is None:
            return VerificationResult(
                ran=False,
                ok=True,
                summary="sem verificador configurado",
            )
        request = VerificationRequest(
            turn=turn,
            changed_files=tuple(dict.fromkeys(self._changed_files)),
            commands_run=self.telemetry.commands_run,
        )
        self.telemetry.enter_phase(RunPhase.VERIFYING)
        self.telemetry.blocked_on = BlockedOn.TESTING
        emit(
            RuntimeEventType.TEST_STARTED,
            cycle=turn.cycle,
            changed_files=list(request.changed_files),
        )
        result = await _maybe_await(self._verify(request))
        if result.ran:
            self.telemetry.mark_test_run()
        self.telemetry.blocked_on = BlockedOn.WORKING
        return result

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    async def _call_observer(self, turn: PrimaryTurn) -> Observation:
        if self._observe is None:
            return Observation(summary="sem observador configurado")
        try:
            return await _maybe_await(self._observe(turn))
        except Exception as exc:  # noqa: BLE001 - observation must never abort a run
            logger.warning("observer failed for run %s: %s", self.run_id, exc)
            return Observation(summary=f"observação indisponível: {exc}")

    async def _checkpoint(
        self, emit: Callable[..., RuntimeEvent], label: str
    ) -> AsyncIterator[RuntimeEvent]:
        """A STOP/CONTINUE boundary between phases."""
        if self.steering.aborted:
            self.outcome.stopped = True
            return
        if self.steering.stop_requested:
            yield emit(
                RuntimeEventType.STATUS_UPDATE,
                phase=label,
                label="pausado a pedido do utilizador",
                blocked_on=BlockedOn.WAITING_USER.value,
            )
            if not await self.steering.wait_if_paused():
                self.outcome.stopped = True
                return
            yield emit(
                RuntimeEventType.USER_STEERING,
                phase=label,
                action="continue",
            )

    def _must_stop(self) -> bool:
        if self.steering.aborted:
            self.outcome.stopped = True
        return self.outcome.stopped

    def _get_experience_bus(self) -> Any:
        """Lazy-resolve the experience bus from the module cache or import."""
        global _experience_bus_cache
        if _experience_bus_cache is not None:
            return _experience_bus_cache
        try:
            from backend.experience.bus import get_experience_bus

            _experience_bus_cache = get_experience_bus()
            return _experience_bus_cache
        except Exception:
            logger.debug("experience bus not available", exc_info=True)
            return None


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        return await value
    return value


def _paths_from_payload(payload: dict[str, Any]) -> tuple[str, ...]:
    for key in ("paths", "files", "changed_files"):
        value = payload.get(key)
        if isinstance(value, (list, tuple)):
            return tuple(str(item) for item in value if item)
    for key in ("path", "file", "target"):
        value = payload.get(key)
        if value:
            return (str(value),)
    return ()


def _proposal_from_payload(payload: dict[str, Any]) -> SubagentProposal | None:
    name = str(payload.get("name") or "").strip()
    if not name:
        return None
    return SubagentProposal(
        name=name,
        objective=str(payload.get("objective") or ""),
        definition_of_done=str(payload.get("definition_of_done") or ""),
        read_scope=frozenset(str(p) for p in payload.get("read_scope") or ()),
        write_scope=frozenset(str(p) for p in payload.get("write_scope") or ()),
        depends_on=frozenset(str(p) for p in payload.get("depends_on") or ()),
        estimated_seconds=float(payload.get("estimated_seconds") or 0.0),
        context_ready=bool(payload.get("context_ready", True)),
        requires_deep_exploration=bool(payload.get("requires_deep_exploration", False)),
    )
