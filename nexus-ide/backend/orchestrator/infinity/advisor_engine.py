"""Advisor Engine — a second model watching every turn (port of omp's advisor).

The advisor runs OUTSIDE the primary loop, on its own context and its own
model (role ``advisor``). It consumes the run's ``RunEventStream`` deltas,
and after meaningful boundaries (tool result, test result, message
completed…) it reviews what the doer did and may emit ONE note:

- ``nit``     — non-interrupting card in the chat timeline.
- ``concern`` — card + injected into the model context at the next cycle via
  ``SteeringChannel.steer`` (unless within the immune window).
- ``blocker`` — same as concern and recorded for the route-level automatic
  corrective follow-up when the run finishes anyway.

Emission guards (ported from omp): normalized exact-dedupe against a FIFO
window, max one note per review cycle, immune turns degrade interrupting
notes to cards, malformed LLM output quarantines twice then drops the batch.

The advisor may also switch the run's model for the next cycle by writing
``agent_context["_model_override"]`` — the primary lane re-reads that dict
per cycle, so the switch is temporary and context-scoped.

Everything here degrades silently: an advisor failure must NEVER break the
run it watches.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.orchestrator.infinity.comm import CommLog, EnvelopeType, normalize_text
from backend.orchestrator.infinity.model_roles import apply_temporary_override, resolve_role
from backend.runtime.events import RunEventStream, RuntimeEventType

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
NOTES_DIR = REPO_ROOT / ".nexus" / "infinity" / "advisor"

SEVERITIES: tuple[str, ...] = ("nit", "concern", "blocker")
_SEVERITY_RANK = {name: rank for rank, name in enumerate(SEVERITIES)}

#: Boundaries worth paying a review call for. Token deltas are never
#: reviewed on their own; batching keeps the advisor cheap.
TRIGGER_TYPES = frozenset({
    RuntimeEventType.TOOL_COMPLETED,
    RuntimeEventType.TOOL_FAILED,
    RuntimeEventType.TEST_RESULT,
    RuntimeEventType.MESSAGE_COMPLETED,
    RuntimeEventType.RUN_COMPLETED,
    RuntimeEventType.RUN_FAILED,
    RuntimeEventType.RUN_CANCELLED,
})

_TERMINAL_TYPES = frozenset({
    RuntimeEventType.RUN_COMPLETED,
    RuntimeEventType.RUN_FAILED,
    RuntimeEventType.RUN_CANCELLED,
})

_IMMUNE_TURNS_DEFAULT = 2
_MAX_DELTA_CHARS = 6_000
_REVIEW_TIMEOUT_S = float(os.environ.get("NEXUS_ADVISOR_REVIEW_TIMEOUT", "45"))
_CONTENT_FREE = {"stop", "lgtm", "done", "ok", "looks good"}

ADVISOR_SYSTEM_PROMPT = """\
You are the ADVISOR: a senior peer engineer reviewing another model's work \
in real time. You see only a compact delta of what it did since your last \
review, plus your own accumulated observations.

Reply with ONLY a JSON object:
{"notes": [{"severity": "nit|concern|blocker", "note": "..."}], "desired_model": null}

Rules:
- At most ONE note per review. Prefer silence; most reviews deserve none.
- severity "blocker": continuing clearly wastes or breaks work (wrong file, \
failing build, destructive command, contradicting the user's literal ask).
- severity "concern": material risk of wrong direction the doer rushed past.
- severity "nit": cleanup/simplification worth saying once.
- Cite only what the delta shows. Never restate advice you already gave.
- desired_model: only when the delta proves the current model cannot do the \
task (e.g. repeated provider truncation). Otherwise null.
No prose outside the JSON."""


def _render_delta(events: list[Any]) -> str:
    lines: list[str] = []
    for event in events:
        kind = getattr(getattr(event, "type", None), "value", "?")
        payload = getattr(event, "payload", {}) or {}
        if kind == "message_delta":
            continue
        if kind in {"tool_started", "tool_completed", "tool_failed"}:
            lines.append(f"{kind}: {payload.get('tool')}")
        elif kind == "test_result":
            lines.append(f"test_result ok={payload.get('ok')} {str(payload.get('summary'))[:200]}")
        elif kind == "message_completed":
            text = str(payload.get("content") or "")[-1_500:]
            lines.append(f"answer_tail:\n{text}")
        elif kind.startswith("run_"):
            lines.append(f"{kind}: {json.dumps(payload, default=str)[:400]}")
        else:
            lines.append(f"{kind}: {json.dumps(payload, default=str)[:200]}")
    rendered = "\n".join(lines)
    return rendered[-_MAX_DELTA_CHARS:]


def _parse_review(raw: str) -> dict[str, Any]:
    """Parse the advisor JSON verdict. Raises ValueError on garbage."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in advisor output")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("advisor output is not an object")
    notes_raw = parsed.get("notes") or []
    if not isinstance(notes_raw, list):
        raise ValueError("notes must be a list")
    notes: list[dict[str, str]] = []
    for item in notes_raw[:5]:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "nit").lower()
        note = str(item.get("note") or "").strip()
        if note and severity in _SEVERITY_RANK:
            notes.append({"severity": severity, "note": note})
    model = parsed.get("desired_model")
    return {"notes": notes, "desired_model": str(model) if model else None}


class AdvisorRuntime:
    """Watches one run and injects notes. Attach with :func:`attach`."""

    def __init__(
        self,
        *,
        run_id: str,
        session_id: str,
        events: RunEventStream,
        llm_client: Any,
        steering: Any = None,
        agent_context: dict[str, Any] | None = None,
        project_path: str = "",
        immune_turns: int | None = None,
    ) -> None:
        self.run_id = run_id
        self.session_id = session_id or "default"
        self._events = events
        self._llm_client = llm_client
        self._steering = steering
        self._agent_context = agent_context if agent_context is not None else {}
        self._project_path = project_path
        if immune_turns is None:
            try:
                immune_turns = int(
                    os.environ.get("NEXUS_ADVISOR_IMMUNE_TURNS", str(_IMMUNE_TURNS_DEFAULT))
                )
            except ValueError:
                immune_turns = _IMMUNE_TURNS_DEFAULT
        self._immune_turns_left = max(0, immune_turns)
        self._log = CommLog(maxlen=256)
        self._cursor = 0
        self._delta: list[Any] = []
        self._quarantine_streak = 0
        self.notes: list[dict[str, Any]] = []
        self.pending_blockers: list[dict[str, str]] = []
        self.desired_model: str | None = None
        self.reviews_done = 0
        self._model_id = resolve_role("advisor").model_id
        override = os.environ.get("NEXUS_ADVISOR_MODEL", "").strip()
        if override:
            resolution = resolve_role("advisor", override=override)
            self._model_id = resolution.model_id
        self._task: asyncio.Task[None] | None = None
        self._stopped = False
        self._terminal_reviewed = asyncio.Event()

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._consume(), name=f"advisor-{self.run_id}")

    async def stop(self) -> None:
        self._stopped = True
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task

    # ── consumption ──────────────────────────────────────────────────────
    async def _consume(self) -> None:
        try:
            async for event in self._events.subscribe(after_seq=self._cursor):
                if self._stopped:
                    return
                self._cursor = event.seq
                terminal = event.type in _TERMINAL_TYPES
                if event.type in TRIGGER_TYPES and not terminal:
                    self._delta.append(event)
                if event.type is RuntimeEventType.MESSAGE_COMPLETED:
                    self._on_turn_completed()
                if terminal:
                    self._delta.append(event)
                    try:
                        await self._review(final=True)
                    finally:
                        self._terminal_reviewed.set()
                    return
                if len(self._delta) >= 8:
                    await self._review(final=False)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — observer failures never break runs
            logger.exception("advisor consumer failed for run %s", self.run_id)

    async def wait_for_terminal_review(self, timeout: float) -> bool:
        """Wait a bounded time for the final review after the primary run ends."""
        if self._terminal_reviewed.is_set():
            return True
        try:
            await asyncio.wait_for(self._terminal_reviewed.wait(), timeout=max(0.0, timeout))
        except TimeoutError:
            return False
        return True

    def _on_turn_completed(self) -> None:
        if self._immune_turns_left > 0:
            self._immune_turns_left -= 1

    # ── review ───────────────────────────────────────────────────────────
    async def _review(self, *, final: bool) -> None:
        if not self._delta:
            return
        delta_events, self._delta = self._delta, []
        rendered = _render_delta(delta_events)
        raw = await self._call_model(rendered)
        if raw is None:
            return
        try:
            verdict = _parse_review(raw)
            self._quarantine_streak = 0
        except (ValueError, json.JSONDecodeError):
            self._quarantine_streak += 1
            if self._quarantine_streak >= 2:
                logger.warning(
                    "advisor output quarantined twice for run %s; batch dropped",
                    self.run_id,
                )
                self._quarantine_streak = 0
            return

        self.reviews_done += 1
        self._maybe_switch_model(verdict.get("desired_model"))
        notes = sorted(
            verdict.get("notes", []),
            key=lambda n: -_SEVERITY_RANK[n["severity"]],
        )
        if notes:
            self._deliver_note(notes[0])

    async def _call_model(self, rendered_delta: str) -> str | None:
        prompt = (
            f"Run delta (events since last review):\n{rendered_delta}\n\n"
            "Review now. JSON only."
        )
        messages = [
            {"role": "system", "content": ADVISOR_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        chunks: list[str] = []
        try:
            stream = self._llm_client.chat_stream(
                self._model_id, messages, options={"max_tokens": 400, "temperature": 0.1},
            )

            async def drain() -> None:
                async for chunk in stream:
                    chunks.append(str(chunk))

            await asyncio.wait_for(drain(), timeout=_REVIEW_TIMEOUT_S)
        except TimeoutError:
            logger.debug("advisor review timed out after %ss", _REVIEW_TIMEOUT_S)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.debug("advisor model call failed (%s); skipping review", exc)
            return None
        return "".join(chunks)

    # ── delivery ─────────────────────────────────────────────────────────
    def _maybe_switch_model(self, desired: str | None) -> bool:
        if not desired or desired == self.desired_model:
            return False
        current = str(self._agent_context.get("_model_override") or "")
        if desired == current:
            return False
        self.desired_model = desired
        apply_temporary_override(self._agent_context, desired)
        self._record(
            EnvelopeType.NOTE,
            body=f"modelo do run alterado para {desired} pelo advisor",
            meta={"kind": "model_switch"},
        )
        with suppress(RuntimeError):
            self._events.emit(
                RuntimeEventType.STATUS_UPDATE,
                agent_id="ADVISOR",
                phase="act",
                label=f"[ADVISOR] modelo alterado temporariamente para {desired}",
            )
        return True

    def _deliver_note(self, note: dict[str, str]) -> None:
        severity = note["severity"]
        body = note["note"].strip()
        if normalize_text(body) in _CONTENT_FREE or len(body) < 8:
            return
        envelope = self._log.append(
            EnvelopeType.NOTE,
            sender="ADVISOR",
            recipient="PRIMARY",
            body=body,
            severity=severity,
            meta={"run_id": self.run_id, "session_id": self.session_id},
        )
        if envelope is None:
            return

        delivered = "card"
        if severity in ("concern", "blocker"):
            if self._immune_turns_left > 0:
                delivered = "card(immune)"
            elif self._steering is not None:
                try:
                    self._steering.steer(f"[ADVISOR|{severity}] {body}")
                    delivered = "steer"
                    self._immune_turns_left = _IMMUNE_TURNS_DEFAULT
                except Exception:  # noqa: BLE001
                    logger.debug("steer channel unavailable; note stays a card")
        if severity == "blocker":
            self.pending_blockers.append({"severity": severity, "note": body})

        record = {
            "ts": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "session_id": self.session_id,
            "severity": severity,
            "note": body,
            "delivered": delivered,
            "model": self._model_id,
        }
        self.notes.append(record)
        self._persist(record)
        with suppress(RuntimeError):
            self._events.emit(
                RuntimeEventType.ADVISOR_NOTE,
                agent_id="ADVISOR",
                severity=severity,
                note=body,
                delivered=delivered,
                advisor="ADVISOR",
                model=self._model_id,
            )

    # ── persistence ──────────────────────────────────────────────────────
    def _record(self, envelope_type: EnvelopeType, *, body: str,
                meta: dict[str, Any]) -> None:
        self._log.append(envelope_type, sender="ADVISOR", recipient="PRIMARY",
                         body=body, meta=meta)

    def _persist(self, record: dict[str, Any]) -> None:
        try:
            folder = NOTES_DIR / self.session_id
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{self.run_id}.jsonl"
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError:
            logger.debug("could not persist advisor note for %s", self.run_id)


# Env-dependent defaults are resolved inside AdvisorRuntime so tests can
# patch os.environ freely.


def attach(
    *,
    run_id: str,
    session_id: str,
    events: RunEventStream,
    llm_client: Any,
    steering: Any,
    agent_context: dict[str, Any],
    project_path: str = "",
) -> AdvisorRuntime:
    """Create and start an AdvisorRuntime for one run."""
    runtime = AdvisorRuntime(
        run_id=run_id,
        session_id=session_id,
        events=events,
        llm_client=llm_client,
        steering=steering,
        agent_context=agent_context,
        project_path=project_path,
    )
    runtime.start()
    return runtime


__all__ = [
    "ADVISOR_SYSTEM_PROMPT",
    "AdvisorRuntime",
    "SEVERITIES",
    "TRIGGER_TYPES",
    "_parse_review",
    "_render_delta",
    "attach",
]
