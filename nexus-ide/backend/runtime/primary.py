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
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from backend.runtime.events import RunEventStream, RuntimeEvent, RuntimeEventType
from backend.runtime.scheduler import RuntimeScheduler, RuntimeTask, RuntimeTaskStatus
from backend.runtime.spawn_policy import SpawnPolicy, SpawnVerdict, SubagentProposal
from backend.runtime.telemetry import BlockedOn, RunPhase, RunTelemetry

logger = logging.getLogger(__name__)

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
    failed: bool = False
    error: str = ""
    telemetry: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return not self.failed and not self.stopped


class SteeringChannel:
    """Cooperative STOP / CONTINUE, checked at every loop boundary.

    STOP is a pause, not a kill: the run stops at the next checkpoint and
    waits. CONTINUE resumes it with everything it had already learned, which
    is the whole point of a persistent primary agent — a restart would throw
    the observation away. ``abort`` is the hard variant for a client that
    disconnected.
    """

    def __init__(self, *, pause_timeout: float = 300.0) -> None:
        self._paused = asyncio.Event()
        self._resumed = asyncio.Event()
        self._resumed.set()
        self._aborted = asyncio.Event()
        self._guidance: list[str] = []
        self.pause_timeout = pause_timeout

    # -- user actions --------------------------------------------------
    def stop(self) -> None:
        self._paused.set()
        self._resumed.clear()

    def cont(self, guidance: str = "") -> None:
        if guidance.strip():
            self._guidance.append(guidance.strip())
        self._paused.clear()
        self._resumed.set()

    def abort(self) -> None:
        self._aborted.set()
        self._resumed.set()

    def steer(self, guidance: str) -> None:
        if guidance.strip():
            self._guidance.append(guidance.strip())

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

        self.outcome = PrimaryOutcome(run_id=run_id)
        self._answer_parts: list[str] = []
        self._changed_files: list[str] = []
        self._subagent_results: list[SubagentResult] = []
        self._declined: list[str] = []
        self._phase = PrimaryPhase.OBSERVE

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

        observation: Observation | None = None
        feedback = ""
        cycle = 0
        try:
            while cycle < self.max_cycles:
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
                )
                for hint in guidance:
                    yield emit(RuntimeEventType.USER_STEERING, guidance=hint, cycle=cycle)

                # -- 1. OBSERVE -------------------------------------------
                async for event in self._checkpoint(emit, "observe"):
                    yield event
                if self._must_stop():
                    break
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

                # -- 2/3. ACT + TOOL --------------------------------------
                self._phase = PrimaryPhase.ACT
                self.telemetry.enter_phase(RunPhase.MODEL_REQUEST)
                self.telemetry.blocked_on = BlockedOn.WAITING_MODEL
                yield emit(RuntimeEventType.MESSAGE_STARTED, cycle=cycle)
                async for event in self._drive_model(turn, emit):
                    yield event
                if self._must_stop():
                    break

                # -- 4. TEST ----------------------------------------------
                self._phase = PrimaryPhase.TEST
                async for event in self._checkpoint(emit, "test"):
                    yield event
                if self._must_stop():
                    break
                result = await self._run_verification(turn, emit)
                if result.ran:
                    yield emit(
                        RuntimeEventType.TEST_RESULT,
                        ok=result.ok,
                        summary=result.summary,
                        command=result.command,
                        details=result.details,
                        cycle=cycle,
                    )
                self.outcome.verification = result

                if result.ran and not result.ok and cycle < self.max_cycles:
                    # The back-edge of the loop: a failed verification is a new
                    # observation, not a terminal state.
                    feedback = (
                        f"A verificação falhou no ciclo {cycle}: {result.summary}\n"
                        f"Comando: {result.command or 'n/d'}\n"
                        "Corrige a causa e volta a verificar."
                    )
                    self.telemetry.mark_retry()
                    yield emit(
                        RuntimeEventType.RECOVERY,
                        reason="verification_failed",
                        cycle=cycle,
                        detail=result.summary,
                    )
                    continue
                break

            # -- 5. REPORT ------------------------------------------------
            self._phase = PrimaryPhase.REPORT
            self.telemetry.enter_phase(RunPhase.FINISHED)
            self.outcome.answer = "".join(self._answer_parts).strip()
            self.outcome.changed_files = tuple(dict.fromkeys(self._changed_files))
            self.outcome.subagents = tuple(self._subagent_results)
            self.outcome.declined_subagents = tuple(self._declined)
            self.telemetry.finish()
            self.outcome.telemetry = self.telemetry.snapshot()

            if self.outcome.stopped:
                yield emit(
                    RuntimeEventType.RUN_CANCELLED,
                    reason="stop_requested",
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
            self.outcome.stopped = True
            raise
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
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
        stream = self._stream(turn)
        try:
            async for signal in stream:
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

                for event in self._handle_signal(signal, turn, emit, proposals):
                    yield event
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(Exception):
                    await aclose()

        if proposals and not self.outcome.stopped:
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
            # reasoning transcript.
            events.append(
                emit(
                    RuntimeEventType.STATUS_UPDATE,
                    phase=PrimaryPhase.ACT.value,
                    label=(signal.text or "a raciocinar").strip()[:160],
                    blocked_on=BlockedOn.WAITING_MODEL.value,
                )
            )
            return events

        if kind is AgentSignalKind.TOOL_CALL:
            self._phase = PrimaryPhase.TOOL
            self.telemetry.enter_phase(RunPhase.EXECUTING)
            self.telemetry.blocked_on = BlockedOn.WAITING_TOOL
            useful = signal.tool_name in (
                READ_TOOLS | WRITE_TOOLS | COMMAND_TOOLS | TEST_TOOLS
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
            self.telemetry.mark_agent_failure()
            events.append(emit(RuntimeEventType.RUN_FAILED, error=signal.text))
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
                        name=task.name,
                    )
                )
            elif task.status is RuntimeTaskStatus.WAITING:
                queue.put_nowait(
                    self.events.emit(
                        RuntimeEventType.WAITING_DEPENDENCY,
                        agent_id=task.agent_id,
                        task_id=task.task_id,
                        name=task.name,
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
                        name=task.name,
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
