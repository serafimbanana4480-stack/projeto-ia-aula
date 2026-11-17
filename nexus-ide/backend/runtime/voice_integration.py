"""Stable voice-to-runtime integration for an existing NEXUS conversation.

This module deliberately does not create a second agent runtime.  It is the
translation seam between ``/api/voice/transcribe`` and the same chat runtime
used by typed messages (``/api/chat`` or the group composer).  The HTTP route
lives in :mod:`backend.orchestrator.routes.chat`; this module keeps the rules
small enough to test without loading speech models.

The client owns audio capture and sends the final transcript with:

``voice_session_id``
    stable identity for the browser session (never trusted as authority);
``turn_id``
    one user utterance; repeated retries of the same turn are deduplicated;
``voice_message_id``
    idempotency key for the durable chat message/run.  The backend derives and
    returns the same stable id on success/replay;
``audio_chunk_id``
    monotonically increasing chunk identifier from the capture stream; used for
    ordering/diagnostics, never sent to the agent;
``message_id`` / ``run_id`` / ``seq``
    the canonical chat ids and runtime order.  They belong to the selected
    existing session; there is no parallel voice transcript.

If a browser reconnects or refreshes, it resumes the existing session and
replays ``(run_id, seq)`` from the normal chat journal.  It must not reopen a
microphone merely to recover a run.  Cancelling speech only stops local TTS;
cancelling a turn uses the ordinary chat stop endpoint and blocks stale audio.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any

_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")


class VoiceContractError(ValueError):
    """A request does not match the stable voice contract."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class VoiceTurn:
    """One final utterance ready to enter the existing chat runtime."""

    owner_id: str
    session_id: str
    message: str
    message_id: str
    turn_id: str
    audio_chunk_ids: tuple[str, ...]
    project_path: str = ""
    bot_id: str = ""
    group_id: str = ""
    local_only: bool = True

    @property
    def idempotency_key(self) -> str:
        """Deterministic key shared by duplicate submissions of this turn."""
        identity = "\n".join((self.owner_id, self.session_id, self.turn_id, self.message))
        return "voice-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:40]


@dataclass(frozen=True, slots=True)
class VoiceAudioChunk:
    """The ordered identity of one locally transcribed utterance."""

    chunk_id: str
    index: int
    text: str

    def __post_init__(self) -> None:
        if not _ID_RE.fullmatch(self.chunk_id):
            raise VoiceContractError("audio_chunk_id inválido")
        if self.index < 0:
            raise VoiceContractError("audio_chunk_id deve indicar uma ordem não negativa")
        if not self.text.strip():
            raise VoiceContractError("A transcrição está vazia")
        if len(self.text) > 12_000:
            raise VoiceContractError("A transcrição excede o limite da mensagem")


def _owner(user: dict[str, Any]) -> str:
    owner = str(user.get("user_id") or "").strip()
    if not owner:
        raise VoiceContractError("Autenticação obrigatória", status=401)
    return owner


def _required_id(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text or not _ID_RE.fullmatch(text):
        raise VoiceContractError(f"{name} inválido")
    return text


def new_voice_ids() -> tuple[str, str]:
    """Return ``(turn_id, audio_chunk_id)`` for one new utterance."""
    token = uuid.uuid4().hex
    return f"turn-{token}", f"audio-{token}"


def stable_message_id(owner_id: str, session_id: str, turn_id: str) -> str:
    """Return the stable durable message identity for a voice utterance.

    It is intentionally derived from the owner, session, and turn rather than
    from the transcript text: a retry after a network failure keeps the same
    identity even if the client cannot resend the exact transcript unchanged.
    """
    _required_id(owner_id, "owner")
    session_id = _required_id(session_id, "session_id")
    turn_id = _required_id(turn_id, "turn_id")
    digest = hashlib.sha256(f"{owner_id}\n{session_id}\n{turn_id}".encode()).hexdigest()
    return f"voice-msg-{digest[:40]}"


def prepare_turn(
    user: dict[str, Any],
    *,
    session_id: str,
    message: str,
    turn_id: str,
    audio_chunks: list[VoiceAudioChunk] | tuple[VoiceAudioChunk, ...] | None = None,
    project_path: str = "",
    bot_id: str = "",
    group_id: str = "",
    local_only: bool = True,
) -> VoiceTurn:
    """Validate and canonicalize one final transcript.

    Audio chunks must be ordered and unique.  Their text is never used to create
    a second history: the final ``message`` is the sole user input.  Duplicate
    ``turn_id`` values intentionally map to the same idempotency key; the normal
    chat route reuses its already-created run.
    """
    owner = _owner(user)
    session_id = _required_id(session_id, "session_id")
    turn_id = _required_id(turn_id, "turn_id")
    message = str(message or "").strip()
    if not message:
        raise VoiceContractError("A transcrição final está vazia")
    if len(message) > 12_000:
        raise VoiceContractError("A transcrição excede o limite da mensagem")
    chunks = tuple(audio_chunks or ())
    if any(not isinstance(chunk, VoiceAudioChunk) for chunk in chunks):
        raise VoiceContractError("audio_chunk_id inválido")
    indexes = [chunk.index for chunk in chunks]
    ids = [chunk.chunk_id for chunk in chunks]
    if indexes != sorted(indexes) or len(set(indexes)) != len(indexes):
        raise VoiceContractError("Os chunks de áudio não estão por ordem única")
    if len(set(ids)) != len(ids):
        raise VoiceContractError("Os chunks de áudio estão duplicados")
    return VoiceTurn(
        owner_id=owner,
        session_id=session_id,
        message=message,
        message_id=stable_message_id(owner, session_id, turn_id),
        turn_id=turn_id,
        audio_chunk_ids=tuple(ids),
        project_path=str(project_path or "").strip(),
        bot_id=str(bot_id or "").strip(),
        group_id=str(group_id or "").strip(),
        local_only=bool(local_only),
    )


def is_stale_audio_chunk(
    *,
    turn_id: str,
    accepted_turn_id: str,
    generation: int,
    accepted_generation: int,
) -> bool:
    """Whether an audio chunk belongs to a superseded capture session.

    Reconnecting, releasing the microphone, or cancelling speech increments the
    capture generation.  Delayed transcription completion from the old
    generation is ignored instead of entering the current turn.
    """
    if generation != accepted_generation:
        return True
    return str(turn_id or "") != str(accepted_turn_id or "")


def replay_gate(
    *,
    run_id: str,
    seq: int,
    audio_message_id: str,
    delivered_audio_message_ids: set[str],
) -> bool:
    """Whether playback may start for an ordered runtime message.

    Audio delivery is a pure function of ``(message_id, runtime order)``.  The
    caller passes the same set used to suppress duplicate terminal/replay
    frames, so a reconnect, a double click, or a repeated event cannot replay
    audio outside the visible run order.  Cancelling a turn clears its pending
    set in the frontend; an old delayed chunk then fails the identity gate.
    """
    if str(run_id or "").strip() == "" or int(seq) < 0:
        return False
    return str(audio_message_id or "") not in set(delivered_audio_message_ids)


__all__ = [
    "VoiceAudioChunk",
    "VoiceContractError",
    "VoiceTurn",
    "is_stale_audio_chunk",
    "new_voice_ids",
    "prepare_turn",
    "replay_gate",
    "stable_message_id",
]