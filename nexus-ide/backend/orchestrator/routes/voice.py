"""Authenticated local-only speech endpoints for NEXUS VOICE."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from starlette.requests import ClientDisconnect

from backend.middleware.auth import require_auth
from backend.voice import local

router = APIRouter(prefix="/voice", tags=["voice"])
logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = local.MAX_AUDIO_BYTES
SUPPORTED_CONTENT_TYPES = local.SUPPORTED_CONTENT_TYPES


class SynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=local.MAX_TEXT_CHARS)
    voice: str | None = Field(default=None, max_length=100)
    speed: float = Field(default=1.0, ge=local.MIN_SPEED, le=local.MAX_SPEED)


def _voice_http_error(exc: local.VoiceError) -> HTTPException:
    """Expose a stable code header without leaking native error text."""
    return HTTPException(exc.status, exc.message, headers={"X-Voice-Error-Code": exc.code})


@router.get("/status")
async def voice_status(_user: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
    return await asyncio.to_thread(local.status)


@router.post("/transcribe")
async def voice_transcribe(
    request: Request,
    model: str | None = Query(None),
    device: str = Query("cpu"),
    _user: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in SUPPORTED_CONTENT_TYPES:
        raise HTTPException(415, "Formato de áudio não suportado.")
    data = bytearray()
    try:
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_AUDIO_BYTES:
                raise HTTPException(413, f"A gravação excede {MAX_AUDIO_BYTES // (1024 * 1024)} MB.")
            if await request.is_disconnected():
                # The client is gone: stop buffering immediately. Native inference
                # cannot be cancelled, but we never start it on an abandoned turn.
                logger.info("Voice transcription cancelled by client")
                raise HTTPException(499, "Pedido cancelado pelo cliente.")
    except ClientDisconnect:
        logger.info("Voice transcription cancelled by client")
        raise HTTPException(499, "Pedido cancelado pelo cliente.") from None
    if not data:
        raise HTTPException(400, "Gravação vazia.")
    try:
        return await asyncio.to_thread(
            local.transcribe,
            bytes(data),
            model or local.default_stt_model(),
            device,
            timeout=local.DEFAULT_TRANSCRIBE_TIMEOUT,
        )
    except local.VoiceError as exc:
        raise _voice_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        logger.exception("Local transcription failed")
        raise HTTPException(503, "Falha no reconhecimento local. Confirma o modelo e dispositivo.") from exc


@router.post("/synthesize")
async def voice_synthesize(
    payload: SynthesisRequest, _user: dict[str, Any] = Depends(require_auth)
) -> Response:
    if not payload.text.strip():
        raise HTTPException(400, "Texto vazio.")
    try:
        audio = await asyncio.to_thread(
            local.synthesize,
            payload.text.strip(),
            payload.voice,
            payload.speed,
            timeout=local.DEFAULT_TRANSCRIBE_TIMEOUT,
        )
    except local.VoiceError as exc:
        raise _voice_http_error(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        logger.exception("Local speech synthesis failed")
        raise HTTPException(503, "Falha na síntese de voz local.") from exc
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})