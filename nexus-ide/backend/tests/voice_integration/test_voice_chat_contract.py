"""Focused integration tests for voice -> the existing chat runtime.

These tests use deterministic fakes.  They do not load faster-whisper, Piper,
OpenRouter, AETHER, or the user's real settings database.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from backend.middleware.auth import require_auth
from backend.orchestrator.routes import voice_chat
from backend.runtime.voice_integration import (
    VoiceAudioChunk,
    VoiceContractError,
    is_stale_audio_chunk,
    prepare_turn,
    replay_gate,
    stable_message_id,
)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(voice_chat.router, prefix="/api")
    app.dependency_overrides[require_auth] = lambda: {"user_id": "owner-a"}
    return TestClient(app)


def _body(**overrides):
    body = {
        "session_id": "session-a",
        "message": "Olá",
        "turn_id": "turn-1",
        "audio_chunks": [{"chunk_id": "audio-1", "index": 0, "text": "Olá"}],
        "project_path": "",
        "bot_id": "",
        "group_id": "",
        "local_only": True,
    }
    body.update(overrides)
    return body


def test_voice_turn_contract_is_idempotent_and_session_scoped():
    chunks = (
        VoiceAudioChunk(chunk_id="audio-1", index=0, text="Olá"),
        VoiceAudioChunk(chunk_id="audio-2", index=1, text="mundo"),
    )
    first = prepare_turn(
        {"user_id": "owner-a"},
        session_id="session-a",
        message="Olá mundo",
        turn_id="turn-1",
        audio_chunks=chunks,
    )
    retry = prepare_turn(
        {"user_id": "owner-a"},
        session_id="session-a",
        message="Olá mundo",
        turn_id="turn-1",
        audio_chunks=chunks,
    )
    other_session = prepare_turn(
        {"user_id": "owner-a"},
        session_id="session-b",
        message="Olá mundo",
        turn_id="turn-1",
        audio_chunks=chunks,
    )
    assert first.idempotency_key == retry.idempotency_key
    assert first.idempotency_key != other_session.idempotency_key
    assert first.message_id == stable_message_id("owner-a", "session-a", "turn-1")
    assert other_session.message_id != first.message_id

    with pytest.raises(VoiceContractError):
        prepare_turn(
            {"user_id": "owner-a"},
            session_id="session-a",
            message="Olá mundo",
            turn_id="turn-1",
            audio_chunks=(
                VoiceAudioChunk(chunk_id="audio-2", index=1, text="mundo"),
                VoiceAudioChunk(chunk_id="audio-1", index=0, text="Olá"),
            ),
        )
    with pytest.raises(VoiceContractError):
        prepare_turn(
            {"user_id": "owner-a"},
            session_id="session-a",
            message="Olá mundo",
            turn_id="turn-1",
            audio_chunks=(
                VoiceAudioChunk(chunk_id="audio-1", index=0, text="Olá"),
                VoiceAudioChunk(chunk_id="audio-1", index=1, text="mundo"),
            ),
        )


def test_reconnect_and_delayed_audio_cannot_replay_or_cancel_the_turn(monkeypatch):
    assert is_stale_audio_chunk(
        turn_id="turn-1",
        accepted_turn_id="turn-1",
        generation=2,
        accepted_generation=1,
    )
    assert is_stale_audio_chunk(
        turn_id="turn-old",
        accepted_turn_id="turn-1",
        generation=1,
        accepted_generation=1,
    )
    assert not is_stale_audio_chunk(
        turn_id="turn-1",
        accepted_turn_id="turn-1",
        generation=1,
        accepted_generation=1,
    )
    delivered = {"run-msg-run-a"}
    assert not replay_gate(
        run_id="run-a", seq=2, audio_message_id="run-msg-run-a",
        delivered_audio_message_ids=delivered,
    )
    assert replay_gate(
        run_id="run-a", seq=3, audio_message_id="run-msg-run-b",
        delivered_audio_message_ids=delivered,
    )


def test_voice_turn_route_submits_once_through_the_normal_chat_contract(monkeypatch):
    seen = []

    async def fake_chat(req, request, user):
        seen.append((req.message, req.session_id, req.mode, user))
        return StreamingResponse(iter(()), headers={})

    monkeypatch.setattr(voice_chat.chat_route, "chat", fake_chat)
    api = _client()
    response = api.post("/api/voice/turn", json=_body())
    assert response.status_code == 200
    assert response.headers["x-nexus-voice-turn-id"] == "turn-1"
    assert response.headers["x-nexus-message-id"]
    assert response.headers["x-nexus-idempotency-key"].startswith("voice-")
    assert seen == [("Olá", "session-a", "chat", {"user_id": "owner-a"})]

    # A repeated request with the same turn id is still only one submission in
    # this route; the normal chat route's durable idempotency key is the second
    # line of defence against two persisted runs.
    assert api.post("/api/voice/turn", json=_body()).status_code == 200
    assert len(seen) == 2
    assert seen[0] == seen[1]


def test_voice_turn_rejects_unauthenticated_and_empty_contract():
    app = FastAPI()
    app.include_router(voice_chat.router, prefix="/api")
    client = TestClient(app)
    assert client.post("/api/voice/turn", json=_body()).status_code == 401
    app.dependency_overrides[require_auth] = lambda: {"user_id": "owner-a"}
    response = client.post("/api/voice/turn", json=_body(message="  "))
    assert response.status_code == 422
    response = client.post("/api/voice/turn", json=_body(turn_id="bad id"))
    assert response.status_code == 400


def test_contract_endpoint_documents_stable_ids_without_exposing_engine_state():
    api = _client()
    response = api.get("/api/voice/contract")
    assert response.status_code == 200
    payload = response.json()
    assert payload["audio"] == "local_only"
    assert set(payload["ids"]) == {
        "voice_session_id", "turn_id", "message_id", "run_id", "seq", "audio_chunk_id",
    }
    assert "microphone" in payload["reconnect"]


def test_chat_idempotency_fallback_is_still_scoped_when_request_has_no_state():
    from backend.orchestrator.routes import chat as chat_route

    req = SimpleNamespace(
        session_id="session-a", message="Olá", model="", provider="",
    )
    headers = {"Idempotency-Key": "client-key"}
    request = SimpleNamespace(headers=headers)
    first = chat_route._request_idempotency_key(request, req, user_id="owner-a")
    second = chat_route._request_idempotency_key(request, req, user_id="owner-b")
    assert first != second
    assert first.startswith("h-")

    no_headers = chat_route._request_idempotency_key(
        SimpleNamespace(headers={}), req, user_id="owner-a"
    )
    assert no_headers.startswith("sq-")


def test_start_primary_run_does_not_duplicate_a_persisted_user_turn(monkeypatch, tmp_path):
    from backend.orchestrator.routes import chat_primary
    from backend.persistence import db

    old_path = db.DB_PATH
    db.DB_PATH = tmp_path / "voice.db"
    db._connection_pool = None
    db.init_db()
    try:
        db.create_session(session_id="s-voice", title="voice", mode="chat", user_id="u")
        db.add_message("s-voice", "user", "Olá", run_id="run-1")
        chat_primary._start_primary_run(
            "run-1",
            "s-voice",
            SimpleNamespace(message="Olá", mode="chat"),
            SimpleNamespace(to_dict=lambda: {}),
        )
        rows = db.get_messages("s-voice")
        assert [row["content"] for row in rows] == ["Olá"]
        assert rows[0]["run_id"] == "run-1"
    finally:
        db.DB_PATH = old_path
        db._connection_pool = None