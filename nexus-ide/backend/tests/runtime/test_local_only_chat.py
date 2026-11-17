"""Local voice turns must never fall back to a cloud LLM."""

from types import SimpleNamespace

import pytest

from backend.llm.factory import ResilientLLMProvider
from backend.llm.lmstudio_provider import LMStudioProvider
from backend.models.api import ChatRequest
from backend.orchestrator.routes import chat as chat_route
from backend.orchestrator.routes import chat_primary
from backend.runtime.run_context import local_only_run


def request(**overrides):
    return ChatRequest(**({
        "message": "Olá", "session_id": "voice-test", "mode": "chat",
        "local_only": True, "provider": "lmstudio", "model": "local-model",
        "model_is_concrete": True,
    } | overrides))


@pytest.mark.asyncio
async def test_local_selection_rejects_remote_url_and_fallback():
    local = LMStudioProvider(base_url="http://127.0.0.1:1234/v1")
    remote = LMStudioProvider(base_url="https://example.com/v1")
    try:
        assert chat_primary._local_provider_error(request(), ResilientLLMProvider(local, [])) is None
        assert chat_primary._local_provider_error(request(), ResilientLLMProvider(remote, []))
        assert chat_primary._local_provider_error(request(), ResilientLLMProvider(local, [remote]))
        assert chat_primary._local_provider_error(request(provider="openai"), local)
        assert chat_primary._local_provider_error(request(model=""), local)
    finally:
        await local.aclose()
        await remote.aclose()


@pytest.mark.asyncio
async def test_local_turn_never_falls_back_if_primary_produces_no_frames(monkeypatch):
    local = LMStudioProvider(base_url="http://127.0.0.1:1234/v1")
    used = []

    async def primary(*args, **kwargs):
        from backend.llm.factory import create_llm_client

        used.append("primary")
        assert local_only_run.get()
        with pytest.raises(RuntimeError, match="local-only"):
            create_llm_client()
        if False:
            yield ""

    async def legacy(*args, **kwargs):
        used.append("legacy")
        yield "legacy"

    monkeypatch.setattr(chat_primary, "run_primary_chat", primary)
    monkeypatch.setattr(chat_primary, "is_primary_enabled", lambda: True)
    monkeypatch.setattr(chat_route, "_run_pipeline", legacy)
    try:
        frames = [frame async for frame in chat_route._select_pipeline(
            request(), ResilientLLMProvider(local, []), None, None,
            request=SimpleNamespace(state=SimpleNamespace(), headers={}), user_id="user",
        )]
        assert any("runtime local terminou sem resposta" in frame for frame in frames)
        assert used == ["primary"]
        assert not local_only_run.get()
    finally:
        await local.aclose()


@pytest.mark.asyncio
async def test_local_turn_rejects_cloud_before_any_pipeline(monkeypatch):
    local = LMStudioProvider(base_url="http://127.0.0.1:1234/v1")
    monkeypatch.setattr(chat_primary, "is_primary_enabled", lambda: True)
    try:
        frames = [frame async for frame in chat_route._select_pipeline(
            request(provider="openai"), ResilientLLMProvider(local, []), None, None,
            request=SimpleNamespace(state=SimpleNamespace(), headers={}), user_id="user",
        )]
        assert any('"type":"error"' in frame or '"type": "error"' in frame for frame in frames)
        assert not any("token" in frame for frame in frames)
    finally:
        await local.aclose()


@pytest.mark.asyncio
async def test_local_advisor_uses_selected_model_even_with_global_override(monkeypatch):
    from backend.orchestrator.infinity.advisor_engine import AdvisorRuntime
    from backend.runtime.events import RunEventStream

    monkeypatch.setenv("NEXUS_ADVISOR_MODEL", "cloud-role-model")
    models = []

    class Client:
        async def chat_stream(self, model, messages, **kwargs):
            models.append(model)
            yield '{"notes": [], "desired_model": null}'

    events = RunEventStream("local-advisor")
    try:
        advisor = AdvisorRuntime(
            run_id="local-advisor", session_id="session", events=events, llm_client=Client(),
            agent_context={"_local_only": True, "_model_override": "local-model"},
        )
        await advisor._call_model("review this")
        assert models == ["local-model"]
    finally:
        await events.aclose()
