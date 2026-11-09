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

Durability lives in :class:`RunLifecycle` (Fase 1b, at the bottom of this
module): the loop itself stays provider/database/HTTP free, and every other
lane talks to the durable run state through that one failure-tolerant seam.
"""

from __future__ import annotations

import asyncio
import contextlib
import difflib
import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from backend.runtime.activity_redaction import is_sensitive_file_request, redact_activity
from backend.runtime.events import RunEventStream, RuntimeEvent, RuntimeEventType
from backend.runtime.reasoning import (
    ReasoningVisibility,
    join_collected_reasoning,
    reasoning_delta_text,
    reasoning_label_or_default,
    reasoning_visibility,
)
from backend.runtime.run_coordinator import RunState
from backend.runtime.scheduler import RuntimeScheduler, RuntimeTask, RuntimeTaskStatus
from backend.runtime.spawn_policy import SpawnPolicy, SpawnVerdict, SubagentProposal
from backend.runtime.telemetry import BlockedOn, RunPhase, RunTelemetry
from backend.tools.output_stream import shell_output_allowed

try:
    from backend.experience.bus import FakeBus
except (ImportError, AttributeError):
    FakeBus = None  # type: ignore[assignment-misc]

logger = logging.getLogger(__name__)


def _dedupe_paths(paths, project_path=None):
    """p40: one entry per file - absolute paths inside the project become
    project-relative, separators are normalised, order is kept (acc14b listed
    NOTES.md twice, once absolute and once relative)."""
    root = ""
    if project_path:
        try:
            root = os.path.normcase(os.path.abspath(str(project_path)))
        except Exception:
            root = ""
    seen = {}
    for raw in paths or ():
        p = str(raw or "").strip()
        if not p:
            continue
        rel = p
        try:
            if root and os.path.isabs(p):
                ap = os.path.normcase(os.path.abspath(p))
                if ap == root or ap.startswith(root + os.sep):
                    rel = os.path.relpath(os.path.abspath(p), os.path.abspath(str(project_path)))
        except Exception:
            rel = p
        rel = rel.replace("\\", "/")
        if rel.startswith("./"):
            rel = rel[2:]
        key = rel.casefold() if os.name == "nt" else rel
        seen.setdefault(key, rel)
    return tuple(seen.values())


def _completed_child_payload(run, name):
    """p40: a duplicate spawn of a finished subagent returns that subagent's
    result instead of a bare denial, so the model does not redo the work."""
    want = " ".join(str(name or "").casefold().split())
    for res in reversed(getattr(run, "_subagent_results", []) or []):
        have = " ".join(str(res.name or "").casefold().split())
        if have == want or have.endswith(":" + want) or want.endswith(":" + have):
            files = list(_dedupe_paths(getattr(run, "_changed_files", []), getattr(run, "project_path", None)))
            return {
                "status": "already_completed" if res.status == "completed" else res.status,
                "previous_status": res.status,
                "output": (res.output or res.error or "")[:2000],
                "changed_files": files[:20],
                "reason": "este subagente JA correu neste run; usa este resultado e nao refacas o trabalho",
            }
    return {}

_experience_bus_cache: Any = None
_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 30.0
_MAX_PREVIOUS_ANSWER_CHARS = 12_000
#: How long a cancelled parent waits for the subagent scheduler to drain its
#: children before giving up and leaving them to the runtime's own cleanup.
_SUBAGENT_DRAIN_TIMEOUT_SECONDS = 10.0


async def _drain_scheduler(
    runner: asyncio.Task[Any],
    *,
    timeout: float = _SUBAGENT_DRAIN_TIMEOUT_SECONDS,
) -> tuple[Any, bool]:
    """Wait for the subagent scheduler to observe a cancel and drain.

    The parent is being cancelled when this runs, and a plain ``await`` on the
    scheduler is interrupted by that pending cancellation — the children would
    then be abandoned mid-flight and the run would leave work behind.
    ``asyncio.wait`` registers a waiter on the existing task instead of
    wrapping it in a new future, so the drain survives the cancellation; a
    repeated cancellation is absorbed and the wait continues.

    Returns the scheduler report (or ``None``) and whether the parent was
    cancelled while draining.
    """
    deadline = time.monotonic() + timeout
    # ``Task.cancelling()`` stays above zero for the whole life of a cancelled
    # task, even after the CancelledError has been delivered. Reading it on
    # entry is what lets the caller re-raise instead of swallowing the
    # cancellation when the drain itself was not interrupted.
    try:
        current = asyncio.current_task()
    except RuntimeError:  # pragma: no cover - no running loop
        current = None
    cancelled = bool(current is not None and current.cancelling() > 0)
    while not runner.done():
        if time.monotonic() >= deadline:
            logger.warning(
                "subagent scheduler did not drain within %.1fs; abandoning",
                timeout,
            )
            runner.cancel()
            break
        try:
            await asyncio.wait({runner}, timeout=0.05)
        except asyncio.CancelledError:
            # A repeated cancellation must not abandon the children.
            cancelled = True
            continue
    if not runner.done():
        return None, cancelled
    if runner.cancelled():
        return None, True
    try:
        return runner.result(), cancelled
    except asyncio.CancelledError:
        return None, True
    except Exception:  # noqa: BLE001 - the report is best effort
        logger.exception("subagent scheduler failed while draining")
        return None, cancelled


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


_DIFF_SNAPSHOT_MAX_BYTES = 256_000
_DIFF_TEXT_CAP = 60_000


def _resolve_project_file(project_path: str, path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(project_path or ".", path)


def _snapshot_files(project_path: str, paths: Sequence[str]) -> dict[str, str | None]:
    """Text of each target file BEFORE a write (``None`` = did not exist)."""
    snapshot: dict[str, str | None] = {}
    for path in list(paths)[:8]:
        full = _resolve_project_file(project_path, str(path))
        try:
            if not os.path.exists(full):
                snapshot[str(path)] = None
            elif os.path.isfile(full) and os.path.getsize(full) <= _DIFF_SNAPSHOT_MAX_BYTES:
                with open(full, encoding="utf-8", errors="replace") as handle:
                    snapshot[str(path)] = handle.read()
        except OSError:
            continue
    return snapshot


def _diff_from_snapshot(
    project_path: str, snapshot: dict[str, str | None]
) -> dict[str, Any] | None:
    """Real unified diff between the pre-write snapshot and the file on disk."""
    files: list[dict[str, Any]] = []
    total_added = total_removed = 0
    for path, before in snapshot.items():
        full = _resolve_project_file(project_path, path)
        try:
            if os.path.isfile(full):
                if os.path.getsize(full) > _DIFF_SNAPSHOT_MAX_BYTES:
                    continue
                with open(full, encoding="utf-8", errors="replace") as handle:
                    after: str | None = handle.read()
            else:
                after = None
        except OSError:
            continue
        if before == after:
            continue
        lines = list(
            difflib.unified_diff(
                (before or "").splitlines(keepends=True),
                (after or "").splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                n=3,
            )
        )
        added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
        total_added += added
        total_removed += removed
        text = "".join(lines)
        files.append(
            {
                "path": path,
                "diff": text[:_DIFF_TEXT_CAP],
                "truncated": len(text) > _DIFF_TEXT_CAP,
                "added": added,
                "removed": removed,
                "created": before is None,
                "deleted": after is None,
            }
        )
    if not files:
        return None
    return {"files": files, "added": total_added, "removed": total_removed}


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
    "SIDE_EFFECT_TOOLS",
    "AgentSignal",
    "AgentSignalKind",
    "Observation",
    "PrimaryLoop",
    "PrimaryOutcome",
    "PrimaryPhase",
    "PrimaryTurn",
    "RunLifecycle",
    "SteeringChannel",
    "VerificationRequest",
    "VerificationResult",
    "find_run_for_identity",
    "get_run_coordinator",
    "is_side_effecting_tool",
    "reset_run_coordinator",
    "run_integration_enabled",
    "side_effect_idempotency_key",
    "side_effect_result_digest",
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
    COMMAND_OUTPUT = "command_output"
    CHILD_SESSION = "child_session"
    #: The agent asks for a subagent. Subject to the spawn policy.
    DELEGATE = "delegate"
    ERROR = "error"
    #: A tool call is held at a human confirmation gate (interactive runs).
    CONFIRMATION = "confirmation"


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
    #: p28: every requested step already ran; this cycle only writes the answer.
    synthesis_only: bool = False
    #: p45: a subagent already wrote files in this run (delegated write done).
    delegated_writes: bool = False


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
ObservedSubagentRunner = Callable[
    [SubagentProposal, Callable[[AgentSignal], None]], Awaitable[str]
]


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
        run_subagent_observed: ObservedSubagentRunner | None = None,
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
        self._run_subagent_observed = run_subagent_observed
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
        self._p42_synth_mark: int | None = None
        self._p42_child_files: list[str] = []
        self._p42_dup_names: list[str] = []
        self._p42_last_turn_proposed = False
        self._changed_files: list[str] = []
        # Tool-result frames carry the handler result, which does not always
        # repeat the path from the original write request. Retain paths in
        # call order and only commit them after the matching tool succeeds.
        self._pending_write_paths: dict[str, list[tuple[str, ...]]] = {}
        # Primary tool calls are paired by a stable call_id (FIFO per tool
        # name), so the UI never has to guess which row a result closes.
        self._open_tool_calls: dict[str, list[tuple[str, float]]] = {}
        self._sensitive_tool_calls: set[str] = set()
        # Pre-write file snapshots keyed by call_id -> real diffs on result.
        self._write_snapshots: dict[str, dict[str, str | None]] = {}
        self._subagent_results: list[SubagentResult] = []
        self._declined: list[str] = []
        # Proposals already dispatched in this run, keyed by (agent, objective).
        # A follow-up cycle asks the model again after the subagents reported
        # back, and the model may repeat the same delegation. Running it twice
        # would duplicate the work, the cost and the file writes.
        self._dispatched_proposals: set[tuple[str, str]] = set()
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

    def partial_answer(self) -> str:
        """Text this run has actually produced, including the reply still streaming.

        ``outcome.answer`` is filled only when the cycle closes. The session
        panel has to count the same buffer the user is already reading.
        """
        answer = (self.outcome.answer or "").strip()
        if answer:
            return answer
        return "".join(self._answer_parts).strip()

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
        cycle_limit = self.max_cycles
        subagent_followup_added = False
        try:
            # Mid-run guidance earns a bounded follow-up model turn even when
            # triage chose a one-cycle conversational/no-project run.
            while cycle < cycle_limit or self.steering.has_guidance:
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
                    delegated_writes=bool(self._p42_child_files),
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
                subagents_before_turn = len(self._subagent_results)
                declined_before_turn = len(self._declined)
                async for event in self._drive_model(turn, emit):
                    yield event
                new_subagent_results = self._subagent_results[subagents_before_turn:]
                new_declined = self._declined[declined_before_turn:]
                if new_subagent_results:
                    self._p42_synth_mark = len(self._answer_parts)
                    child_context = "\n".join(
                        f"- {result.name} [{result.status}]: "
                        f"{result.output or result.error or 'sem resultado'}"
                        for result in new_subagent_results
                    )
                    turn.feedback = (
                        f"{turn.feedback}\n\nRESULTADOS DOS SUBAGENTES:\n{child_context}"
                    ).strip()
                if new_declined:
                    declined_context = ", ".join(dict.fromkeys(new_declined))
                    turn.feedback = (
                        f"{turn.feedback}\n\nDELEGAÇÃO NÃO CRIADA: {declined_context}. "
                        "O runtime PRIMARY não iniciou esses trabalhos. Faz tu o trabalho "
                        "necessário com as ferramentas disponíveis ou explica claramente "
                        "o bloqueio; não afirmes que os subagentes estão a trabalhar."
                    ).strip()
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
                if new_subagent_results or new_declined:
                    if cycle >= cycle_limit and not subagent_followup_added:
                        cycle_limit += 1
                        subagent_followup_added = True
                    if cycle < cycle_limit:
                        direction = (
                            "Usa os resultados dos subagentes para concluir o pedido e "
                            "verificar o trabalho antes de responder."
                            if new_subagent_results
                            else "A delegação não foi iniciada; conclui tu o pedido ou "
                            "reporta o bloqueio com honestidade."
                        )
                        if new_subagent_results and self._changed_files:
                            direction = (
                                "Ficheiros com alterações registadas: "
                                f"{', '.join(_dedupe_paths(self._changed_files, self.project_path)[:8])}. "
                                "Evita repetir alterações confirmadas e verifica o que falta. "
                                + direction
                            )
                        logger.info("p39 decision | changed=%d commands=%d new_sub=%d new_declined=%d ver_ran=%s ver_ok=%s", len(self._changed_files), self.telemetry.commands_run, len(new_subagent_results), len(new_declined), result.ran, result.ok)
                        _p44_done = [r.name for r in new_subagent_results if r.status == "completed"]
                        if _p44_done:
                            # p44 (acc14f): cycle 2 re-spawned the finished CODER.
                            direction = (
                                f"Subagentes JÁ concluídos: {', '.join(_p44_done)}. NÃO os voltes a "
                                "lançar (spawn_task repetido é ignorado); usa o resultado abaixo. "
                                + direction
                            )
                        feedback = f"{direction}\n{turn.feedback}"
                        previous_answer = _bounded_previous_answer(
                            "".join(self._answer_parts).strip()
                        )
                        continue
                    self.outcome.failed = True
                    self.outcome.error = (
                        "Os resultados da delegação não foram sintetizados pelo agente primário."
                        if new_subagent_results
                        else "A delegação foi recusada e o agente primário não concluiu o pedido."
                    )
                    break

                if result.ran and not result.ok and cycle < cycle_limit:
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
            for _p42_event in self._p42_ensure_synthesis(emit):
                yield _p42_event
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
            self.outcome.changed_files = _dedupe_paths(self._changed_files, self.project_path)
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
            self.outcome.changed_files = _dedupe_paths(self._changed_files, self.project_path)
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
            # The category is what lets the UI say *why* the run failed (a
            # refused key, an exhausted quota, a local server that is not
            # running) instead of repeating a stack-shaped string.
            error_category = str(getattr(exc, "category", "") or "") or "unknown"
            yield emit(
                RuntimeEventType.RUN_FAILED,
                error=self.outcome.error,
                error_category=error_category,
                telemetry=self.outcome.telemetry,
            )

    # ------------------------------------------------------------------
    # phases
    # ------------------------------------------------------------------
    async def _drive_model(
        self, turn: PrimaryTurn, emit: Callable[..., RuntimeEvent]
    ) -> AsyncIterator[RuntimeEvent]:
        """Consume one model turn, executing its tool signals as they arrive."""
        from backend.runtime.run_context import reset_current_task_id, set_current_task_id

        # Each ``stream.__anext__()`` runs in a fresh ``asyncio.Task`` that
        # inherits *this* context, not the previous anext task's mutations.
        # Publish the cycle task id here so tool idempotency keys match the
        # primary lane's durable checkpoints and the registry ledger.
        task_ctx_token = set_current_task_id(f"cycle-{turn.cycle}")
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
            reset_current_task_id(task_ctx_token)

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

        self._p42_last_turn_proposed = bool(proposals)
        if proposals and not self.outcome.stopped and not self.outcome.failed:
            _p42_before = len(self._changed_files)
            async for event in self._delegate(proposals, emit):
                yield event
            self._p42_child_files.extend(self._changed_files[_p42_before:])

    def _p42_ensure_synthesis(self, emit: Callable[..., RuntimeEvent]) -> list[RuntimeEvent]:
        """p42 (acc14e): the synthesis-only cycle can end with an EMPTY model
        answer (free models put everything in reasoning), so the chat showed
        the subagent card and nothing after it. Always close with a visible
        synthesis and attribute subagent file changes to the subagent."""
        if self._p42_synth_mark is None or not self._subagent_results:
            return []
        if self.outcome.stopped or self.outcome.failed:
            return []
        synthesis = "".join(self._answer_parts[self._p42_synth_mark :]).strip()
        child_files = _dedupe_paths(self._p42_child_files, self.project_path)
        names = list(dict.fromkeys(r.name for r in self._subagent_results))
        status_pt = {"completed": "concluído", "failed": "falhou", "cancelled": "cancelado"}
        text = ""
        # p43 (acc14f): the follow-up turn re-spawned the finished subagent and
        # ended on "Vou lançar o subagente..." - prose, but no synthesis.
        ended_on_delegation = self._p42_last_turn_proposed
        if not synthesis or ended_on_delegation:
            logger.warning(
                "p42 synthesis block | empty=%s ended_on_delegation=%s dup=%s subagents=%s",
                not synthesis, ended_on_delegation, self._p42_dup_names, names,
            )
            lines = ["**Resultado dos subagentes**"]
            for r in self._subagent_results:
                # p44: the child's first line is usually its preamble ("Vou
                # começar por..."); its conclusion is at the end.
                detail = [ln.strip() for ln in (r.output or r.error or "").splitlines() if ln.strip()]
                first = detail[-1][:300] if detail else "sem resultado"
                lines.append(f"- **{r.name}** — {status_pt.get(r.status, r.status)}: {first}")
            for dup in dict.fromkeys(self._p42_dup_names):
                lines.append(
                    f"- Pedido repetido de delegação para **{dup}** ignorado: "
                    "o subagente já tinha corrido nesta execução."
                )
            if child_files:
                lines.append(
                    "Ficheiros alterados pelo(s) subagente(s): "
                    + ", ".join(f"`{f}`" for f in child_files[:12])
                )
            text = ("\n\n" if self._answer_parts else "") + "\n".join(lines)
        elif child_files:
            low = synthesis.lower()
            mentioned = any(
                n.lower() in low or n.split(":", 1)[-1].lower() in low for n in names
            )
            if not mentioned:
                text = (
                    "\n\nAlterações feitas pelo(s) subagente(s) "
                    + ", ".join(f"**{n}**" for n in names)
                    + ": "
                    + ", ".join(f"`{f}`" for f in child_files[:12])
                    + "."
                )
        logger.info(
            "p42 synthesis | chars=%d child_files=%d appended=%d",
            len(synthesis), len(child_files), len(text),
        )
        if not text:
            return []
        self._answer_parts.append(text)
        return [emit(RuntimeEventType.MESSAGE_DELTA, text=text)]

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
            label = reasoning_label_or_default(
                signal.text or "a raciocinar",
                visibility=self.reasoning_visibility,
            )
            events.append(
                emit(
                    RuntimeEventType.STATUS_UPDATE,
                    phase=PrimaryPhase.ACT.value,
                    label=label[:160],
                    blocked_on=BlockedOn.WAITING_MODEL.value,
                )
            )
            visible = reasoning_delta_text(
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

        if kind is AgentSignalKind.CONFIRMATION:
            # The ReAct loop is blocked in wait_for_confirmation; surface the
            # gate on the SAME call id so the chat row can show "Confirmar".
            # (Previously this signal was dropped and the row spun on
            # "A executar" until the 300 s confirmation expired.)
            open_calls = self._open_tool_calls.get(signal.tool_name) or []
            call_id = open_calls[-1][0] if open_calls else None
            confirmation = redact_activity(dict(signal.payload or {}))
            if call_id in self._sensitive_tool_calls and isinstance(confirmation, dict):
                confirmation["tool_args"] = {"detail": "[argumentos sensíveis omitidos]"}
            events.append(
                emit(
                    RuntimeEventType.TOOL_PROGRESS,
                    tool=signal.tool_name,
                    call_id=call_id,
                    phase="awaiting_confirmation",
                    label="aguarda aprovação",
                    confirmation=confirmation,
                )
            )
            return events

        if kind is AgentSignalKind.COMMAND_OUTPUT:
            calls = self._open_tool_calls.get(signal.tool_name) or []
            # Only associate output when its call is unambiguous and safe.
            if len(calls) == 1 and calls[0][0] not in self._sensitive_tool_calls:
                stream = signal.payload.get("stream")
                if stream in {"stdout", "stderr"} and signal.text:
                    events.append(emit(
                        RuntimeEventType.COMMAND_OUTPUT, tool=signal.tool_name,
                        call_id=calls[0][0], stream=stream, text=redact_activity(signal.text),
                    ))
            return events

        if kind is AgentSignalKind.TOOL_CALL:
            if signal.tool_name in WRITE_TOOLS:
                self._pending_write_paths.setdefault(signal.tool_name, []).append(
                    _paths_from_payload(signal.payload)
                )
            self._phase = PrimaryPhase.TOOL
            self.telemetry.enter_phase(RunPhase.EXECUTING)
            self.telemetry.blocked_on = BlockedOn.WAITING_TOOL
            useful = signal.tool_name in (
                READ_TOOLS | WRITE_TOOLS | COMMAND_TOOLS | TEST_TOOLS | PLAN_TOOLS
            )
            self.telemetry.mark_tool_call(useful=useful)
            call_id = uuid.uuid4().hex
            sensitive = is_sensitive_file_request(signal.payload) or (
                signal.tool_name == "run_shell"
                and not shell_output_allowed(str(signal.payload.get("command") or ""))
            )
            if sensitive:
                self._sensitive_tool_calls.add(call_id)
            self._open_tool_calls.setdefault(signal.tool_name, []).append(
                (call_id, time.monotonic())
            )
            if signal.tool_name in WRITE_TOOLS and not sensitive:
                with contextlib.suppress(Exception):
                    self._write_snapshots[call_id] = _snapshot_files(
                        self.project_path, _paths_from_payload(signal.payload)
                    )
            args = redact_activity(signal.payload)
            if sensitive and isinstance(args, dict):
                args = {
                    key: value for key, value in args.items()
                    if key in {"path", "file_path", "filename", "file", "paths", "files"}
                }
                args["detail"] = "[argumentos sensíveis omitidos]"
            events.append(
                emit(
                    RuntimeEventType.TOOL_STARTED,
                    tool=signal.tool_name,
                    args=args,
                    cycle=turn.cycle,
                    call_id=call_id,
                )
            )
            if signal.tool_name in COMMAND_TOOLS:
                events.append(
                    emit(
                        RuntimeEventType.COMMAND_STARTED,
                        call_id=call_id,
                        tool=signal.tool_name,
                        command=redact_activity(str(
                            signal.payload.get("command")
                            or signal.payload.get("code")
                            or ""
                        )),
                        cwd=redact_activity(self.project_path),
                        cycle=turn.cycle,
                    )
                )
            elif signal.tool_name in TEST_TOOLS:
                events.append(
                    emit(
                        RuntimeEventType.TEST_STARTED,
                        tool=signal.tool_name,
                        args=args,
                        cycle=turn.cycle,
                    )
                )
            return events

        if kind in (AgentSignalKind.TOOL_RESULT, AgentSignalKind.TOOL_ERROR):
            ok = signal.ok and kind is AgentSignalKind.TOOL_RESULT
            name = signal.tool_name
            open_calls = self._open_tool_calls.get(name) or []
            matched_call = bool(open_calls)
            if open_calls:
                call_id, started_at = open_calls.pop(0)
                duration_ms: int | None = int((time.monotonic() - started_at) * 1000)
            else:
                call_id, duration_ms = uuid.uuid4().hex, None
            # Without a start event there is no trustworthy way to decide if a
            # result came from a sensitive file. Fail closed for that payload.
            sensitive = call_id in self._sensitive_tool_calls or not matched_call
            self._sensitive_tool_calls.discard(call_id)
            visible_result = (
                {"detail": "Conteúdo sensível ou sem chamada associada omitido do histórico."}
                if sensitive else redact_activity(signal.payload)
            )
            visible_error = (
                "Detalhes de erro sensíveis omitidos." if sensitive and signal.text
                else redact_activity(signal.text)
            )
            diff: dict[str, Any] | None = None
            snapshot = self._write_snapshots.pop(call_id, None)
            if ok and snapshot:
                with contextlib.suppress(Exception):
                    diff = _diff_from_snapshot(self.project_path, snapshot)
            pending_write_paths = (
                self._take_pending_write_paths(name) if name in WRITE_TOOLS else ()
            )
            if ok and matched_call:
                events.extend(
                    self._record_tool_effect(
                        name,
                        visible_result,
                        emit,
                        fallback_paths=pending_write_paths,
                    )
                )
            elif not ok:
                self.telemetry.mark_agent_failure()
            events.append(
                emit(
                    RuntimeEventType.TOOL_COMPLETED if ok else RuntimeEventType.TOOL_FAILED,
                    tool=name,
                    ok=ok,
                    result=visible_result,
                    error=visible_error,
                    cycle=turn.cycle,
                    call_id=call_id,
                    duration_ms=duration_ms,
                    diff=redact_activity(diff),
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
                task_name = str(signal.payload.get("name") or "subagente")
                self._mark_declined(task_name)
                events.extend(
                    [
                        emit(
                            RuntimeEventType.TOOL_STARTED,
                            tool="spawn_task",
                            args=redact_activity(signal.payload),
                            cycle=turn.cycle,
                        ),
                        emit(
                            RuntimeEventType.TOOL_COMPLETED,
                            tool="spawn_task",
                            ok=True,
                            result={
                                "status": "denied",
                                "spawned": False,
                                "task_name": task_name,
                                "reason": "a proposta não contém um agente e um objetivo válidos",
                            },
                            cycle=turn.cycle,
                        ),
                    ]
                )
                return events
            decision = self.spawn_policy.evaluate(proposal)
            events.append(
                emit(
                    RuntimeEventType.TOOL_STARTED,
                    tool="spawn_task",
                    args=redact_activity(signal.payload),
                    cycle=turn.cycle,
                )
            )
            if decision.verdict is SpawnVerdict.SPAWN or decision.verdict is SpawnVerdict.QUEUE:
                proposals.append(proposal)
                _p43_dup = any(
                    " ".join(old.casefold().split()) == " ".join(proposal.name.casefold().split())
                    for old, _ in self._dispatched_proposals
                )
                events.append(
                    emit(
                        RuntimeEventType.STATUS_UPDATE,
                        phase=PrimaryPhase.ACT.value,
                        label=(
                            f"delegação repetida ignorada: {proposal.name} já correu nesta execução"
                            if _p43_dup
                            else f"proposta de delegação aceite: {proposal.name}; a aguardar início"
                        ),
                        verdict=decision.verdict.value,
                        reason=decision.reason,
                    )
                )
            else:
                self._mark_declined(proposal.name)
                events.append(
                    emit(
                        RuntimeEventType.TOOL_COMPLETED,
                        tool="spawn_task",
                        ok=True,
                        result={
                            "status": "denied",
                            "spawned": False,
                            "background": False,
                            "task_name": proposal.name,
                            "reason": decision.reason,
                            "failed_conditions": list(decision.failed_conditions),
                        },
                        cycle=turn.cycle,
                    )
                )
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
        self,
        name: str,
        payload: dict[str, Any],
        emit: Callable[..., RuntimeEvent],
        *,
        fallback_paths: tuple[str, ...] = (),
    ) -> list[RuntimeEvent]:
        """Translate a successful tool result into measured, honest progress."""
        events: list[RuntimeEvent] = []
        if name in READ_TOOLS:
            count = int(payload.get("files_read") or 1)
            self.telemetry.mark_file_read(count)
            events.append(emit(RuntimeEventType.FILE_READ, tool=name, count=count))
        elif name in WRITE_TOOLS:
            changed = _paths_from_payload(payload) or fallback_paths
            changed = tuple(dict.fromkeys(changed))
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

    def _take_pending_write_paths(self, tool_name: str) -> tuple[str, ...]:
        """Pair a write result with the corresponding earlier tool call."""
        pending = self._pending_write_paths.get(tool_name)
        if not pending:
            return ()
        paths = pending.pop(0)
        if not pending:
            self._pending_write_paths.pop(tool_name, None)
        return paths

    def _mark_declined(self, name: str) -> None:
        """Count and report each declined worker once, even across model cycles."""
        if name not in self._declined:
            self._declined.append(name)
            self.telemetry.mark_subagent_declined()

    async def _delegate(
        self, proposals: Sequence[SubagentProposal], emit: Callable[..., RuntimeEvent]
    ) -> AsyncIterator[RuntimeEvent]:
        """Run approved proposals through the deterministic scheduler.

        Dependencies are honoured (a dependent never starts before its
        dependency has COMPLETED), overlapping write scopes are serialised,
        and independent proposals run in real parallel up to the cap.
        """
        if self._run_subagent is None and self._run_subagent_observed is None:
            for proposal in proposals:
                self._mark_declined(proposal.name)
                yield emit(
                    RuntimeEventType.TOOL_COMPLETED,
                    tool="spawn_task",
                    ok=True,
                    result={
                        "status": "denied",
                        "spawned": False,
                        "background": False,
                        "task_name": proposal.name,
                        "reason": "no subagent runner is configured for this run",
                    },
                )
            return

        self.telemetry.blocked_on = BlockedOn.WAITING_WORKER
        live = 0
        # Task names are also dependency and scheduler identities. Reusing one
        # name for different objectives makes by_name/name_to_id ambiguous and
        # can attach the wrong objective or dependency to a worker. Require a
        # new name, even when the model rewords a previous objective.
        fresh: list[SubagentProposal] = []
        for proposal in proposals:
            key = (proposal.name, str(proposal.objective or ""))
            name_used = any(
                " ".join(old_name.casefold().split()) == " ".join(proposal.name.casefold().split())
                for old_name, _ in self._dispatched_proposals
            )
            if name_used:
                logger.info(
                    "run %s: skipping repeated delegation of %s (%s)",
                    self.run_id,
                    proposal.name,
                    proposal.objective,
                )
                # p28: a duplicate of an already-dispatched subagent is not a
                # refused delegation. Marking it declined told the follow-up
                # cycle "DELEGAÇÃO NÃO CRIADA ... faz tu o trabalho", and the
                # model restarted the whole task (acc12).
                self._p42_dup_names.append(proposal.name)
                yield emit(
                    RuntimeEventType.TOOL_COMPLETED,
                    tool="spawn_task",
                    ok=True,
                    result={
                        "status": "denied",
                        "spawned": False,
                        "background": False,
                        "task_name": proposal.name,
                        "reason": "this task name was already delegated in this run; use a distinct name for different work",
                        **_completed_child_payload(self, proposal.name),
                    },
                )
                continue
            self._dispatched_proposals.add(key)
            fresh.append(proposal)
        if not fresh:
            return
        proposals = fresh
        by_name = {proposal.name: proposal for proposal in proposals}
        queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue()
        sensitive_tasks: set[str] = set()
        started_at: dict[str, float] = {}
        child_snapshots: dict[str, dict[str, str | None]] = {}

        def on_signal(task: RuntimeTask, signal: AgentSignal) -> None:
            """Enqueue observed child tools in the same total order as lifecycle events."""
            pending = pending_calls.setdefault(task.task_id, {})
            if signal.kind is AgentSignalKind.CHILD_SESSION:
                queue.put_nowait(self.events.emit(
                    RuntimeEventType.SUBAGENT_PROGRESS, agent_id=task.agent_id,
                    task_id=task.task_id, phase="child_session_created",
                    child_session_id=str(signal.payload.get("child_session_id") or ""),
                    child_run_id=str(signal.payload.get("child_run_id") or ""),
                ))
                return
            if signal.kind is AgentSignalKind.TOKEN:
                # The child's own words belong to the child's conversation,
                # attributed by agent_id/task_id. They never enter the parent's
                # answer buffer (``_answer_parts``).
                if signal.text and task.task_id not in sensitive_tasks:
                    task.heartbeat()
                    queue.put_nowait(self.events.emit(
                        RuntimeEventType.MESSAGE_DELTA, agent_id=task.agent_id,
                        task_id=task.task_id, text=signal.text, subagent=True,
                    ))
                return
            if signal.kind is AgentSignalKind.THINKING:
                visible = reasoning_delta_text(
                    signal.text or "", visibility=self.reasoning_visibility,
                )
                if visible and task.task_id not in sensitive_tasks:
                    queue.put_nowait(self.events.emit(
                        RuntimeEventType.THINKING, agent_id=task.agent_id,
                        task_id=task.task_id, text=visible, label=visible[:160],
                        visibility=self.reasoning_visibility.value, subagent=True,
                    ))
                return
            if signal.kind is AgentSignalKind.COMMAND_OUTPUT:
                calls = pending.get(signal.tool_name, [])
                stream = signal.payload.get("stream")
                if len(calls) == 1 and not calls[0][1] and stream in {"stdout", "stderr"}:
                    queue.put_nowait(self.events.emit(
                        RuntimeEventType.COMMAND_OUTPUT, agent_id=task.agent_id,
                        task_id=task.task_id, tool=signal.tool_name, call_id=calls[0][0],
                        stream=stream, text=redact_activity(signal.text),
                    ))
                return
            if signal.kind is AgentSignalKind.TOOL_CALL:
                call_id = uuid.uuid4().hex
                sensitive = is_sensitive_file_request(signal.payload) or (
                    signal.tool_name == "run_shell"
                    and not shell_output_allowed(str(signal.payload.get("command") or ""))
                )
                if sensitive:
                    sensitive_tasks.add(task.task_id)
                pending.setdefault(signal.tool_name, []).append((call_id, sensitive))
                started_at[call_id] = time.monotonic()
                if signal.tool_name in WRITE_TOOLS and not sensitive:
                    with contextlib.suppress(Exception):
                        child_snapshots[call_id] = _snapshot_files(
                            self.project_path, _paths_from_payload(signal.payload)
                        )
                args = redact_activity(signal.payload)
                if sensitive and isinstance(args, dict):
                    args = {
                        key: value for key, value in args.items()
                        if key in {"path", "file_path", "filename", "file", "paths", "files"}
                    }
                    args["detail"] = "[argumentos sensíveis omitidos]"
                task.mark_first_tool_call()
                queue.put_nowait(self.events.emit(
                    RuntimeEventType.TOOL_STARTED, agent_id=task.agent_id, task_id=task.task_id,
                    tool=signal.tool_name, args=args, call_id=call_id,
                ))
            elif signal.kind in (AgentSignalKind.TOOL_RESULT, AgentSignalKind.TOOL_ERROR):
                task.heartbeat()
                calls = pending.get(signal.tool_name, [])
                # A result without a matching start must never close another
                # worker's tool with the same name in the frontend.
                call_id, sensitive = calls.pop(0) if calls else (uuid.uuid4().hex, True)
                ok = signal.kind is AgentSignalKind.TOOL_RESULT and signal.ok
                began = started_at.pop(call_id, None)
                duration_ms = int((time.monotonic() - began) * 1000) if began else None
                diff = None
                snapshot = child_snapshots.pop(call_id, None)
                if ok and snapshot:
                    with contextlib.suppress(Exception):
                        diff = _diff_from_snapshot(self.project_path, snapshot)
                # p32: child evidence counts for the parent's claim verifier
                # and changed-file list (subagent writes/tests/reads).
                if ok and not sensitive:
                    with contextlib.suppress(Exception):
                        if snapshot and diff:
                            child_paths = [str(p) for p in snapshot]
                            self._changed_files.extend(child_paths)
                            self.telemetry.mark_file_changed(max(1, len(child_paths)))
                        elif signal.tool_name in TEST_TOOLS:
                            self.telemetry.mark_test_run()
                            payload = signal.payload if isinstance(signal.payload, dict) else {}
                            failed = payload.get("failed") or payload.get("failures") or 0
                            if payload.get("success", True) is not False and not failed:
                                self._child_tests_green = True
                        elif signal.tool_name in READ_TOOLS:
                            self.telemetry.mark_file_read()
                result = (
                    {"detail": "Conteúdo de ficheiro sensível omitido do histórico."}
                    if sensitive else redact_activity(signal.payload)
                )
                queue.put_nowait(self.events.emit(
                    RuntimeEventType.TOOL_COMPLETED if ok else RuntimeEventType.TOOL_FAILED,
                    agent_id=task.agent_id, task_id=task.task_id, tool=signal.tool_name,
                    call_id=call_id, ok=ok, result=result,
                    duration_ms=duration_ms, diff=redact_activity(diff),
                    error=("Detalhes de erro sensíveis omitidos." if sensitive and signal.text
                           else redact_activity(signal.text)),
                ))

        pending_calls: dict[str, dict[str, list[tuple[str, bool]]]] = {}
        name_to_id: dict[str, str] = {}
        tasks: list[RuntimeTask] = []
        for proposal in proposals:
            task = RuntimeTask(
                name=proposal.name,
                run=self._subagent_body(proposal, on_signal),
                write_scope=proposal.write_scope,
                read_scope=proposal.read_scope,
                # The scheduler task name includes a short task label after
                # the colon; runtime/UI agent ids must remain a valid AgentName.
                agent_id=proposal.name.split(":", 1)[0].upper(),
            )
            name_to_id[proposal.name] = task.task_id
            tasks.append(task)
        for task in tasks:
            deps = by_name[task.name].depends_on
            task.depends_on = frozenset(
                name_to_id[dep] for dep in deps if dep in name_to_id
            )

        def task_context(task: RuntimeTask) -> dict[str, Any]:
            proposal = by_name.get(task.name)
            return {
                "name": task.name,
                "objective": redact_activity(proposal.objective) if proposal is not None else None,
                "depends_on": sorted(task.depends_on),
                "parent_agent_id": self.agent_id,
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
                        error=("Detalhes de erro sensíveis omitidos."
                               if task.task_id in sensitive_tasks and task.error
                               else redact_activity(task.error)),
                        result=(
                            None if task.status is not RuntimeTaskStatus.COMPLETED or task.result is None
                            else "[resultado omitido: o agente acedeu a um ficheiro sensível]"
                            if task.task_id in sensitive_tasks
                            else redact_activity(str(task.result))
                        ),
                    )
                )

        scheduler = RuntimeScheduler(
            max_parallel=self._max_parallel_subagents, on_status=on_status
        )
        cancel = asyncio.Event()
        # The scheduler runs as a background task so the parent can keep
        # yielding subagent events while the children work, and so a cancelled
        # parent can drain it through the cooperative ``cancel`` event.
        # Without this line every delegated task raised NameError and the
        # whole subagent path was dead.
        runner = asyncio.create_task(scheduler.run(tasks, cancel_event=cancel))
        cancelled = False
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
            # A cancelled parent must not leave scheduler tasks running outside
            # the run's lifetime. The scheduler observes this cooperative signal
            # and returns a terminal report after draining its workers.
            cancel.set()
            report, cancelled = await _drain_scheduler(runner)

        for task in report.tasks:
            task_proposal = by_name.get(task.name)
            if task_proposal is not None:
                self.spawn_policy.release(
                    task_proposal.name, completed=task.status is RuntimeTaskStatus.COMPLETED
                )
            self._subagent_results.append(
                SubagentResult(
                    name=task.name,
                    status=task.status.value,
                    output=str(task.result) if task.result is not None else "",
                    error=task.error,
                )
            )
            result = {
                "status": task.status.value,
                "spawned": task.started_at > 0,
                "background": False,
                "task_name": task.name,
                "output": (
                    "[resultado omitido: o agente acedeu a um ficheiro sensível]"
                    if task.task_id in sensitive_tasks
                    else str(task.result) if task.result is not None else ""
                ),
            }
            if task.error:
                result["error"] = (
                    "Detalhes de erro sensíveis omitidos."
                    if task.task_id in sensitive_tasks else task.error
                )
            completed = task.status is RuntimeTaskStatus.COMPLETED
            if not cancelled:
                yield emit(
                    RuntimeEventType.TOOL_COMPLETED
                    if completed
                    else RuntimeEventType.TOOL_FAILED,
                    task_id=task.task_id,
                    tool="spawn_task",
                    ok=completed,
                    result=redact_activity(result),
                    error=redact_activity(result.get("error", "")),
                )
        self.telemetry.parallelism_peak = max(
            self.telemetry.parallelism_peak, report.peak_parallelism
        )
        self.telemetry.blocked_on = BlockedOn.WORKING
        if cancelled:
            raise asyncio.CancelledError

    def _subagent_body(
        self, proposal: SubagentProposal,
        on_signal: Callable[[RuntimeTask, AgentSignal], None],
    ) -> Callable[[RuntimeTask], Awaitable[Any]]:
        async def body(task: RuntimeTask) -> Any:
            from backend.runtime.run_context import reset_current_task_id, set_current_task_id

            self.spawn_policy.register(proposal)
            task.heartbeat()
            task_token = set_current_task_id(task.task_id)
            try:
                if self._run_subagent_observed is not None:
                    result = await self._run_subagent_observed(
                        proposal, lambda signal: on_signal(task, signal)
                    )
                else:
                    assert self._run_subagent is not None
                    result = await self._run_subagent(proposal)
                task.heartbeat()
                return result
            finally:
                reset_current_task_id(task_token)

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
            "tests": (self.telemetry.tests_run > 0 and verification_green)
            or bool(getattr(self, "_child_tests_green", False)),
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
            changed_files=_dedupe_paths(self._changed_files, self.project_path),
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
    task_name = str(payload.get("name") or "").strip()
    if not task_name:
        return None
    from typing import get_args

    from backend.models.api import AgentName

    valid_agents = get_args(AgentName)
    agent = str(payload.get("agent") or "").strip().upper()
    if agent:
        if agent not in valid_agents:
            return None
        # p42: the model often passes name "CODER:Notas" with agent "CODER";
        # prefixing again produced "CODER:CODER:Notas" in the UI.
        if task_name.upper().startswith(f"{agent}:"):
            task_name = task_name[len(agent) + 1 :].strip() or task_name
        name = f"{agent}:{task_name}"
    elif (
        ":" in task_name
        and task_name.split(":", 1)[0].strip().upper() in valid_agents
        and task_name.split(":", 1)[1].strip()
    ):
        head, tail = task_name.split(":", 1)
        name = f"{head.strip().upper()}:{tail.strip()}"
    elif task_name.upper() in valid_agents:
        # Direct runtime callers may already provide the registered agent name.
        name = task_name.upper()
    else:
        # The tool schema leaves ``agent`` optional and spawn_task defaults it
        # to CODER, so PRIMARY must preserve that same default for scheduling.
        name = f"CODER:{task_name}"
    default_estimate = os.environ.get("NEXUS_SPAWN_ESTIMATED_SECONDS", "120") or "120"
    try:
        estimated_seconds = float(
            payload.get("estimated_seconds")
            if payload.get("estimated_seconds") is not None
            else default_estimate
        )
    except (TypeError, ValueError):
        estimated_seconds = 120.0
    return SubagentProposal(
        name=name,
        objective=str(payload.get("objective") or payload.get("description") or ""),
        definition_of_done=str(payload.get("definition_of_done") or ""),
        context=str(payload.get("context") or "")[:8_000],
        read_scope=frozenset(str(p) for p in payload.get("read_scope") or ()),
        write_scope=frozenset(str(p) for p in payload.get("write_scope") or ()),
        depends_on=frozenset(str(p) for p in payload.get("depends_on") or ()),
        estimated_seconds=estimated_seconds,
        context_ready=bool(payload.get("context_ready", True)),
        requires_deep_exploration=bool(payload.get("requires_deep_exploration", False)),
    )


# ---------------------------------------------------------------------------
# run lifecycle integration (Fase 1b — checkpoint / resume / idempotência)
# ---------------------------------------------------------------------------
# A NEXUS run is now a *durable* object owned by
# :class:`backend.runtime.run_coordinator.RunCoordinator`: a goal, the
# requirements it must satisfy, an explicit definition of done, a checkpoint at
# every phase boundary and an idempotency ledger for side effects. This section
# is the seam every execution lane uses to talk to that owner.
#
# Two rules are structural here, and both are load-bearing:
#
# 1. **The loop above stays free of persistence imports.** ``run_coordinator``
#    and ``backend.persistence.db`` are imported lazily, inside the functions
#    that need them, exactly like the experience bus above.
# 2. **A coordinator failure degrades durability, never the run.** Every method
#    of :class:`RunLifecycle` catches its own exceptions and logs them: a locked
#    database, a missing table or an illegal transition is an operational
#    finding, not a reason to lose the user's turn.
#
# Reuse (idempotency) is the third rule: :meth:`RunLifecycle.begin` returns the
# run that is already in flight for the same session/query/idempotency key
# instead of creating a second one, so a client retry cannot fork the durable
# run state into two competing histories.

#: Marker prefix recorded in ``RunRecord.memory_refs`` so an explicit
#: ``Idempotency-Key`` can be resolved back to its run after a restart.
_IDEMPOTENCY_MARKER = "idempotency:"

#: Marker prefix for the mission a run belongs to. Runs created by the engine
#: lane carry it; the primary lane has no mission.
_MISSION_MARKER = "mission:"

#: Tools whose execution changes the world outside the process (files, git,
#: shell commands). Read/plan tools are deliberately absent: they have no
#: side effect to guard or replay.
SIDE_EFFECT_TOOLS = frozenset(
    WRITE_TOOLS | COMMAND_TOOLS | {"git_commit", "git_push", "git_apply", "apply_patch"}
)


def run_integration_enabled() -> bool:
    """Feature flag for the durable run lifecycle. Defaults to on."""
    raw = os.environ.get("NEXUS_RUN_LIFECYCLE", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def is_side_effecting_tool(name: str) -> bool:
    """Whether a tool's completion is a real-world side effect worth guarding."""
    tool = str(name or "").strip()
    return tool in SIDE_EFFECT_TOOLS or tool.startswith("git_")


#: Server-injected scope fields must not change the identity of an action.
#: ``execute_tool`` may drop them before the handler runs while the primary
#: lane's tool-call signal still carries them — both paths must hash the same
#: payload or the ledger records one write twice.
_SIDE_EFFECT_IDENTITY_STRIP_KEYS = frozenset(
    {"project_path", "cwd", "root_path", "workspace_path", "session_id"}
)


def _normalize_side_effect_args(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    return {
        key: value
        for key, value in args.items()
        if key not in _SIDE_EFFECT_IDENTITY_STRIP_KEYS
    }


def side_effect_idempotency_key(
    run_id: str, task_id: str, tool: str, args: dict[str, Any] | None = None
) -> str:
    """Stable key for one side effect of one run.

    The key covers the *identity* of the action (run, task, tool, arguments) and
    nothing about its outcome, so a replay of the same action produces the same
    key and the ledger recognises it as already applied. Arguments are hashed
    with ``sort_keys`` so a re-ordered dict cannot look like a different action.
    """
    normalized = _normalize_side_effect_args(args)
    try:
        serialized = json.dumps(normalized, sort_keys=True, default=str)
    except (TypeError, ValueError):
        serialized = repr(args)
    digest = hashlib.sha256(
        "\u0000".join([str(run_id), str(task_id or "-"), str(tool or "-"), serialized]).encode(
            "utf-8"
        )
    ).hexdigest()[:32]
    return f"{tool or 'tool'}:{digest}"


def side_effect_result_digest(result: Any) -> str:
    """Short digest of what a tool actually returned, for the ledger row."""
    try:
        payload = json.dumps(result, sort_keys=True, default=str)
    except (TypeError, ValueError):
        payload = repr(result)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


_run_coordinator_lock = threading.Lock()
_run_coordinator: Any = None
_run_coordinator_path: str = ""


def get_run_coordinator() -> Any:
    """Return the process-wide coordinator, or ``None`` when unavailable.

    The instance is keyed by the resolved database path: the test suite repoints
    ``backend.persistence.db.DB_PATH`` per test, and a coordinator pinned to a
    previous path would silently write into a database nobody reads.
    """
    global _run_coordinator, _run_coordinator_path
    if not run_integration_enabled():
        return None
    from backend.persistence import db

    target = str(db.DB_PATH)
    with _run_coordinator_lock:
        if _run_coordinator is not None and _run_coordinator_path == target:
            return _run_coordinator
        from backend.runtime.run_coordinator import RunCoordinator

        coordinator = RunCoordinator()
        _run_coordinator = coordinator
        _run_coordinator_path = target
        return coordinator


def reset_run_coordinator() -> None:
    """Forget the cached coordinator (test helper; safe when none exists)."""
    global _run_coordinator, _run_coordinator_path
    with _run_coordinator_lock:
        _run_coordinator = None
        _run_coordinator_path = ""


def _run_budget() -> dict[str, Any]:
    """Budget limits for a new run, read from the environment.

    Only limits that are actually configured are sent: an empty budget means
    "no limit" and the coordinator refuses unknown keys, so this never invents
    one. ``NEXUS_RUN_MAX_*`` are the operator-facing run-level ceilings.
    """
    budget: dict[str, Any] = {}
    int_limits = {
        "NEXUS_RUN_MAX_TOKENS": "max_tokens",
        "NEXUS_RUN_MAX_TOOL_CALLS": "max_tool_calls",
        "NEXUS_RUN_MAX_RETRIES": "max_retries",
        "NEXUS_RUN_MAX_SUBAGENTS": "max_subagents",
        "NEXUS_RUN_MAX_PROVIDER_CALLS": "max_provider_calls",
    }
    float_limits = {
        "NEXUS_RUN_MAX_COST_USD": "max_cost_usd",
        "NEXUS_RUN_MAX_RUNTIME_SECONDS": "max_runtime_seconds",
    }
    for env_name, limit in int_limits.items():
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            continue
        try:
            budget[limit] = int(float(raw))
        except ValueError:
            logger.debug("Ignoring invalid run budget %s=%r", env_name, raw)
    for env_name, limit in float_limits.items():
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            continue
        try:
            budget[limit] = float(raw)
        except ValueError:
            logger.debug("Ignoring invalid run budget %s=%r", env_name, raw)
    return budget


def _newest_resumable(coordinator: Any, **filters: Any) -> Any:
    """Return the most recently updated resumable run matching ``filters``."""
    try:
        runs = coordinator.find_resumable_runs(**filters)
    except Exception:
        logger.debug("Could not list resumable runs", exc_info=True)
        return None
    return runs[0] if runs else None


def find_run_for_identity(
    *,
    session_id: str = "",
    user_id: str = "",
    goal: str = "",
    idempotency_key: str = "",
    mission_id: str = "",
    include_terminal: bool = False,
) -> Any:
    """Return the durable run this request is a retry of, or ``None``.

    Resolution order is deliberate: an explicit idempotency key is the strongest
    signal a client gives us, then the mission association, then the weakest
    (and most heuristic) ``session_id + goal`` pair. By default only non-terminal
    runs qualify. HTTP request replays may opt into terminal runs so a late
    network retry can return the original result instead of running the task a
    second time.
    """
    if not (idempotency_key or mission_id or (session_id and goal)):
        return None
    coordinator = get_run_coordinator()
    if coordinator is None:
        return None

    if idempotency_key:
        marker = f"{_IDEMPOTENCY_MARKER}{idempotency_key}"
        records = (
            coordinator.list_runs(
                session_id=session_id or None,
                user_id=user_id or None,
                limit=1_000,
            )
            if include_terminal
            else coordinator.find_resumable_runs(
                session_id=session_id or None,
                user_id=user_id or None,
            )
        )
        for record in records:
            if marker in [str(item) for item in record.memory_refs]:
                return record
        # An explicit request key defines the operation's identity. Falling
        # back to matching prompt text here could merge a deliberate second
        # request into an unrelated run that happens to share the same goal.
        return None
    if mission_id:
        marker = f"{_MISSION_MARKER}{mission_id}"
        for record in coordinator.find_resumable_runs(
            session_id=session_id or None,
            user_id=user_id or None,
        ):
            if marker in [str(item) for item in record.memory_refs]:
                return record
    if session_id and goal:
        try:
            runs = coordinator.find_resumable_runs(
                session_id=session_id,
                user_id=user_id or None,
            )
        except Exception:
            logger.debug("Could not list runs for session %s", session_id, exc_info=True)
            return None
        for record in runs:
            if record.goal == goal:
                return record
    return None


class RunLifecycle:
    """Durable mirror of one unit of work. Every call is failure-tolerant.

    One instance owns one ``run_state`` row for its whole life: it creates the
    run (or adopts the one already in flight), drives it through
    ``CREATED → PLANNING → RUNNING``, writes the phase-boundary checkpoints the
    resume path restores from, records confirmed side effects in the
    idempotency ledger, and closes the run only when the definition of done is
    actually satisfied.

    Constructing one never raises: when the coordinator is unavailable the
    instance is created in a *disabled* state and every method becomes a
    no-op, which is exactly the degradation this runtime promises.
    """

    def __init__(
        self,
        run_id: str,
        *,
        goal: str = "",
        session_id: str = "",
        user_id: str = "",
        project_id: str = "",
        mission_id: str = "",
        idempotency_key: str = "",
        record: Any = None,
    ) -> None:
        self.run_id = run_id
        self.goal = goal
        self.session_id = session_id
        self.user_id = user_id
        self.project_id = project_id
        self.mission_id = mission_id
        self.idempotency_key = idempotency_key
        self._record = record
        self._completed = False
        self._closed = False

    # ───── construction ─────────────────────────────────────────────────

    @classmethod
    def begin(
        cls,
        *,
        goal: str,
        session_id: str = "",
        user_id: str = "",
        project_id: str = "",
        mission_id: str = "",
        requirements: Any = None,
        constraints: Any = None,
        definition_of_done: Any = None,
        budget: dict[str, Any] | None = None,
        idempotency_key: str = "",
        run_id: str = "",
        reuse_existing: bool = True,
    ) -> RunLifecycle | None:
        """Create — or adopt — the durable run for this unit of work.

        Returns ``None`` when the coordinator is unavailable or disabled: the
        caller then simply runs without a durable mirror, which is the
        documented degradation rather than a broken turn.
        """
        coordinator = get_run_coordinator()
        if coordinator is None:
            return None

        existing = None
        if run_id:
            existing = cls._safe_get(coordinator, run_id)
        elif reuse_existing:
            existing = find_run_for_identity(
                session_id=session_id,
                user_id=user_id,
                goal=goal,
                idempotency_key=idempotency_key,
                mission_id=mission_id,
            )

        if existing is not None:
            lifecycle = cls(
                str(existing.run_id),
                goal=goal or str(existing.goal),
                session_id=session_id or str(existing.session_id),
                user_id=user_id or str(existing.user_id),
                project_id=project_id or str(existing.project_id),
                mission_id=mission_id,
                idempotency_key=idempotency_key,
                record=existing,
            )
            lifecycle._mark_identity(coordinator)
            lifecycle._move(RunState.RUNNING, reason="run in flight for this request")
            logger.info(
                "[RUN] reusing durable run %s (session=%s goal=%.80s)",
                lifecycle.run_id,
                lifecycle.session_id,
                lifecycle.goal,
            )
            return lifecycle

        try:
            record = coordinator.create_run(
                goal=goal,
                requirements=list(requirements or []),
                constraints=list(constraints or []),
                definition_of_done=list(definition_of_done or []),
                project_id=project_id,
                user_id=user_id,
                session_id=session_id,
                budget=budget if budget is not None else _run_budget(),
            )
        except Exception:
            logger.exception("Could not create the durable run for %.80s", goal)
            return None
        lifecycle = cls(
            str(record.run_id),
            goal=goal,
            session_id=session_id,
            user_id=user_id,
            project_id=project_id,
            mission_id=mission_id,
            idempotency_key=idempotency_key,
            record=record,
        )
        lifecycle._mark_identity(coordinator)
        lifecycle._move(RunState.PLANNING, reason="run created")
        lifecycle._move(RunState.RUNNING, reason="execution started")
        logger.info(
            "[RUN] created durable run %s (session=%s goal=%.80s)",
            lifecycle.run_id,
            lifecycle.session_id,
            lifecycle.goal,
        )
        return lifecycle

    @staticmethod
    def _safe_get(coordinator: Any, run_id: str) -> Any:
        try:
            return coordinator.get_run(run_id)
        except Exception:
            logger.debug("Could not read run %s", run_id, exc_info=True)
            return None

    @property
    def record(self) -> Any:
        """The last known :class:`RunRecord`; ``None`` when never read."""
        return self._record

    @property
    def enabled(self) -> bool:
        """Always ``True``: an instance exists only when the coordinator does."""
        return True

    @property
    def closed(self) -> bool:
        """Whether this run already reached a terminal durable state."""
        return self._closed

    # ───── state machine ────────────────────────────────────────────────

    def _move(self, state: Any, *, reason: str = "") -> None:
        if self._closed:
            return
        coordinator = get_run_coordinator()
        if coordinator is None:
            return
        try:
            self._record = coordinator.transition(self.run_id, state, reason=reason)
        except Exception as exc:
            # An illegal move (for example RUNNING → RUNNING while adopting a
            # run that is already executing) is a no-op, not a broken run.
            logger.debug("Run %s did not transition to %s: %s", self.run_id, state, exc)

    def _mark_identity(self, coordinator: Any) -> None:
        """Persist the markers that make this run findable after a restart."""
        markers: list[str] = []
        if self.idempotency_key:
            markers.append(f"{_IDEMPOTENCY_MARKER}{self.idempotency_key}")
        if self.mission_id:
            markers.append(f"{_MISSION_MARKER}{self.mission_id}")
        if not markers:
            return
        try:
            existing = [str(item) for item in (self._record.memory_refs if self._record else [])]
            merged = list(dict.fromkeys([*existing, *markers]))
            self._record = coordinator.update_progress(self.run_id, memory_refs=merged)
        except Exception:
            logger.debug("Could not record identity markers for run %s", self.run_id, exc_info=True)

    # ───── progress / checkpoints ───────────────────────────────────────

    def update_progress(
        self,
        *,
        plan: dict[str, Any] | None = None,
        current_task_id: str | None = None,
        artifacts: Any = None,
        changed_files: Any = None,
        provider: dict[str, Any] | None = None,
    ) -> None:
        """Refresh the executable state of the run (heartbeat included)."""
        coordinator = get_run_coordinator()
        if coordinator is None:
            return
        try:
            self._record = coordinator.update_progress(
                self.run_id,
                plan=plan,
                current_task_id=current_task_id,
                artifacts=artifacts,
                changed_files=changed_files,
                provider=provider,
                # Every real step is also a liveness signal: the watchdog reads
                # ``heartbeat_at`` from this, and a run that works must not look
                # stalled while it works.
                heartbeat=True,
            )
        except Exception:
            logger.debug("Could not update progress for run %s", self.run_id, exc_info=True)

    def heartbeat(self, **payload: Any) -> None:
        """Liveness signal; recorded as a checkpoint so a resume sees it.

        The caller's keys are nested under ``signal`` so they can never collide
        with the mandatory ``phase`` argument of :meth:`checkpoint`.
        """
        self.checkpoint("heartbeat", signal=dict(payload))

    def checkpoint(self, phase: str, **payload: Any) -> None:
        """Record one phase boundary. The payload is what a resume restores."""
        coordinator = get_run_coordinator()
        if coordinator is None:
            return
        try:
            coordinator.checkpoint(self.run_id, phase=phase, payload=dict(payload))
        except Exception:
            logger.debug("Could not checkpoint run %s (%s)", self.run_id, phase, exc_info=True)

    def record_task_completed(
        self,
        task_id: str,
        *,
        name: str = "",
        ok: bool = True,
        changed_files: Any = None,
        detail: Any = None,
    ) -> None:
        """One task/cycle finished: persist it as a resumable boundary."""
        self.checkpoint(
            "after_task",
            task_id=str(task_id),
            task_name=name,
            ok=bool(ok),
            changed_files=[str(item) for item in (changed_files or [])],
            detail=detail,
        )
        self.update_progress(
            current_task_id=str(task_id),
            changed_files=changed_files if changed_files is not None else None,
        )

    # ───── side effects (idempotency ledger) ────────────────────────────

    def _side_effect_task_id(self, explicit: str) -> str:
        from backend.runtime.run_context import get_current_task_id

        return get_current_task_id() or str(explicit or "").strip()

    def side_effect_confirmed(self, *, tool: str, args: Any = None, task_id: str = "") -> bool:
        """Whether this exact side effect was already applied by this run."""
        coordinator = get_run_coordinator()
        if coordinator is None:
            return False
        key = side_effect_idempotency_key(
            self.run_id, self._side_effect_task_id(task_id), tool, args
        )
        try:
            return bool(coordinator.is_side_effect_confirmed(self.run_id, key))
        except Exception:
            logger.debug("Could not read the side-effect ledger for run %s", self.run_id, exc_info=True)
            return False

    def before_side_effect(
        self, *, tool: str, args: Any = None, task_id: str = "", cycle: int = 0
    ) -> bool:
        """Checkpoint *before* a real-world action; ``True`` means replay.

        The return value tells the caller whether this action was already
        confirmed for this run, so a resumed run can report "already applied"
        instead of silently doing it twice.
        """
        resolved_task = self._side_effect_task_id(task_id)
        key = side_effect_idempotency_key(self.run_id, resolved_task, tool, args)
        already = self.side_effect_confirmed(tool=tool, args=args, task_id=task_id)
        self.checkpoint(
            "before_side_effect",
            tool=str(tool),
            args=_jsonable(args),
            idempotency_key=key,
            replay=already,
            task_id=str(task_id),
            cycle=cycle,
        )
        if already:
            logger.info(
                "[RUN] side effect already confirmed for run %s (%s); treating as a replay",
                self.run_id,
                key,
            )
        return already

    def after_side_effect(
        self,
        *,
        tool: str,
        args: Any = None,
        task_id: str = "",
        result: Any = None,
        ok: bool = True,
    ) -> None:
        """Checkpoint *after* the action and record it in the ledger."""
        resolved_task = self._side_effect_task_id(task_id)
        key = side_effect_idempotency_key(self.run_id, resolved_task, tool, args)
        self.checkpoint(
            "after_side_effect",
            tool=str(tool),
            args=_jsonable(args),
            idempotency_key=key,
            ok=bool(ok),
            result_digest=side_effect_result_digest(result),
            task_id=str(resolved_task or task_id),
        )
        if not ok:
            return
        if self.side_effect_confirmed(tool=tool, args=args, task_id=task_id):
            # Already recorded (typically by ``execute_tool``): checkpoints still
            # bracket the action, but the ledger has a single writer.
            return
        coordinator = get_run_coordinator()
        if coordinator is None:
            return
        try:
            coordinator.record_side_effect(
                self.run_id,
                key,
                kind=str(tool),
                result_digest=side_effect_result_digest(result),
            )
        except Exception:
            logger.warning(
                "Could not record the side effect %s for run %s", key, self.run_id, exc_info=True
            )

    # ───── closing ──────────────────────────────────────────────────────

    def finish(self, dod_results: Any = None, *, reason: str = "") -> bool:
        """Close the run as ``COMPLETED`` — only with a satisfied definition.

        Returns ``True`` when the run reached ``COMPLETED``. An unsatisfied
        definition of done leaves the run exactly where it was (non-terminal,
        therefore still listed as resumable) and returns ``False``: absence of
        evidence is never allowed to look like success.
        """
        if self._closed or self._completed:
            return self._completed
        coordinator = get_run_coordinator()
        if coordinator is None:
            return False
        from backend.runtime.run_coordinator import DoDNotSatisfied

        try:
            self._record = coordinator.complete(self.run_id, list(dod_results or []))
            self._completed = True
            self._closed = True
            logger.info(
                "[RUN] run %s completed with a satisfied definition of done", self.run_id
            )
            return True
        except DoDNotSatisfied as exc:
            logger.warning(
                "[RUN] run %s NOT completed — definition of done unmet: %s",
                self.run_id,
                "; ".join(str(item.get("requirement", "?")) for item in exc.details) or "n/a",
            )
            return False
        except Exception:
            logger.exception("Could not complete run %s", self.run_id)
            return False

    def fail(self, reason: str = "") -> None:
        """Mark the run ``FAILED`` with a human-readable reason."""
        # The transition happens before the flag: ``_move`` refuses to act on a
        # closed run, so closing first would make every failure a no-op.
        self._move(RunState.FAILED, reason=reason[:400] or "run failed")
        self._closed = True
        logger.info("[RUN] run %s failed: %s", self.run_id, reason[:200])

    def cancel(self, reason: str = "") -> None:
        """Mark the run ``CANCELLED`` (user stop / client disconnect)."""
        self._move(RunState.CANCELLED, reason=reason[:400] or "run cancelled")
        self._closed = True
        logger.info("[RUN] run %s cancelled: %s", self.run_id, reason[:200])

    def pause(self, reason: str = "") -> None:
        """Park the run so it can be resumed by an explicit request."""
        self._move(RunState.PAUSED, reason=reason[:400] or "paused")


def _jsonable(value: Any) -> Any:
    """Best-effort JSON-safe copy, so a checkpoint payload can always be stored."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(item) for item in value]
    return str(value)

