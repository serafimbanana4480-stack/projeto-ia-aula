"""Stable voice integration contract.

Voice is transport for one existing conversation turn, not a second runtime.
A final utterance enters ``POST /api/chat`` (or the group composer) exactly like
a typed message.  The identity rules are implemented in
``backend.runtime.voice_integration`` and kept import-light so the chat routes
can depend on them without importing STT/TTS engines.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.middleware.auth import require_auth
from backend.orchestrator.routes import chat as chat_route
from backend.runtime.voice_integration import (
    VoiceAudioChunk,
    VoiceContractError,
    prepare_turn,
)

router = APIRouter(prefix="/voice", tags=["voice"])


class VoiceChunkIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    chunk_id: str = Field(min_length=1, max_length=160)
    index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=12_000)


class VoiceTurnIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=12_000)
    turn_id: str = Field(min_length=1, max_length=160)
    audio_chunks: list[VoiceChunkIn] = Field(default_factory=list, max_length=100)
    project_path: str = Field(default="", max_length=1000)
    bot_id: str = Field(default="", max_length=160)
    group_id: str = Field(default="", max_length=160)
    local_only: bool = True


def _owner(user: dict[str, Any]) -> str:
    owner = str(user.get("user_id") or "").strip()
    if not owner:
        raise HTTPException(status_code=401, detail="Autenticação obrigatória")
    return owner


def _voice_error(exc: VoiceContractError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


def _chat_request(turn: Any, *, provider: str = "", model: str = "", model_is_concrete: bool = False):
    from backend.models.api import ChatRequest

    return ChatRequest(
        message=turn.message,
        session_id=turn.session_id,
        mode="chat",
        model=model,
        model_is_concrete=model_is_concrete,
        provider=provider,
        local_only=turn.local_only,
        project_path=turn.project_path,
    )


def _session_bot(owner: str, session_id: str, bot_id: str) -> bool:
    """Whether this authenticated owner's session belongs to the named bot."""
    from backend.persistence.bots import bot_for_session

    profile = bot_for_session(owner, session_id)
    return bool(profile and str(profile.get("id") or "") == str(bot_id or "").strip())


@router.post("/turn")
async def submit_voice_turn(
    payload: VoiceTurnIn,
    request: Request,
    user: dict = Depends(require_auth),
) -> StreamingResponse:
    """Submit a final local transcript through the normal chat route.

    The endpoint does not synthesize a response and never invokes STT/TTS.  It
    returns the existing chat SSE stream, so the frontend can use the same
    ``useAgentStream`` contract (including ``run_id``/``seq`` replay and stop).
    """
    owner = _owner(user)
    chunks = tuple(
        VoiceAudioChunk(chunk_id=chunk.chunk_id, index=chunk.index, text=chunk.text)
        for chunk in payload.audio_chunks
    )
    try:
        turn = prepare_turn(
            {"user_id": owner},
            session_id=payload.session_id,
            message=payload.message,
            turn_id=payload.turn_id,
            audio_chunks=chunks,
            project_path=payload.project_path,
            bot_id=payload.bot_id,
            group_id=payload.group_id,
            local_only=payload.local_only,
        )
    except VoiceContractError as exc:
        raise _voice_error(exc) from exc

    # A bot's provider and model belong to the persisted session profile, not
    # to this transport.  ``chat`` loads that profile below and rejects a hidden
    # or unconfigured bot; there is deliberately no model/provider field here.
    if turn.bot_id and not _session_bot(owner, turn.session_id, turn.bot_id):
        raise HTTPException(
            status_code=409,
            detail="A sessão de voz não está associada ao bot escolhido.",
        )

    if turn.group_id:
        from backend.orchestrator.routes import bot_groups
        from backend.persistence import bot_groups as group_store

        group = group_store.get_group(owner, turn.group_id)
        if group is None:
            raise HTTPException(status_code=404, detail="Grupo não encontrado")
        # Group turns stay on the composer endpoint: one selected bot, one run,
        # ordered replay. The voice contract cannot declare a spoken team.
        response = await bot_groups.send_group_message(
            turn.group_id,
            bot_groups.GroupTurn(message=turn.message, project_path=turn.project_path),
            request,
            user,
        )
        response.headers["X-Nexus-Voice-Turn-Id"] = turn.turn_id
        response.headers["X-Nexus-Message-Id"] = turn.message_id
        response.headers["X-Nexus-Idempotency-Key"] = turn.idempotency_key
        return response

    # ``POST /api/chat`` is already the canonical text entry point. A voice turn
    # is the same authenticated chat request with a stable idempotency header;
    # do not reimplement its ownership/project checks here.
    from copy import copy

    request.state.nexus_voice_turn_id = turn.turn_id
    request.state.nexus_voice_message_id = turn.message_id
    request.state.nexus_idempotency_key = turn.idempotency_key
    chat_request = request
    try:
        chat_request = copy(request)
        chat_request.headers = {**dict(request.headers), "Idempotency-Key": turn.idempotency_key}
    except Exception:
        # Direct in-process callers/tests may use a lightweight fake Request;
        # the canonical route's state-based fallback is still user/session scoped.
        pass
    chat_req = _chat_request(turn)
    response = await chat_route.chat(chat_req, chat_request, user)
    # ``chat`` returns the existing chat SSE stream. Expose the stable voice ids
    # without inventing a second transcript; they correlate retries and audio
    # playback only.
    response.headers["X-Nexus-Voice-Turn-Id"] = turn.turn_id
    response.headers["X-Nexus-Message-Id"] = turn.message_id
    response.headers["X-Nexus-Idempotency-Key"] = turn.idempotency_key
    return response


@router.get("/contract")
async def voice_contract(user: dict = Depends(require_auth)) -> dict[str, Any]:
    """Describe the stable ids and ownership rules to a reconnecting client."""
    _owner(user)
    return {
        "session_field": "session_id",
        "ids": {
            "voice_session_id": "client-side capture identity; not authority",
            "turn_id": "stable id for one user utterance",
            "message_id": "derived durable chat message identity",
            "run_id": "canonical runtime run id",
            "seq": "runtime event order; replay with after_seq",
            "audio_chunk_id": "ordered capture chunk; not a chat message",
        },
        "audio": "local_only",
        "reconnect": "resume/replay the existing session; never reopen the microphone",
        "cancel": "cancel speech is local only; cancel turn uses the chat stop route",
    }


# The voice route is an integration seam: it is not a second chat runtime.  It
# submits the final transcript through the canonical chat/group route.  Keep the
# contract read-only; speech endpoints remain owned by the voice module.


__all__ = ["router"]