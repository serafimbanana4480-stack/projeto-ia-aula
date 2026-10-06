"""Wiring tests for the LM Studio provider (local OpenAI-compatible server).

Covers the orphan-provider fixes: factory branch, free-only eligibility,
model-catalog spec, chat route allowlist, tier resolution, and the
``stream_options`` retry behaviour. No test touches the network.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from types import SimpleNamespace

import httpx
import pytest

from backend.llm import factory
from backend.llm.factory import ResilientLLMProvider, create_llm_client
from backend.llm.lmstudio_provider import DEFAULT_READ_TIMEOUT, LMStudioProvider
from backend.llm.model_catalog import PROVIDER_SPECS
from backend.llm.openai_provider import OpenAIProvider


def _settings(**extra: object) -> SimpleNamespace:
    """Minimal settings namespace; mirrors test_factory_runtime_settings."""
    base: dict[str, object] = {
        "llm_provider": "lmstudio",
        "default_provider": "lmstudio",
        "multi_llm_enabled": False,
        "free_only": True,
        "opencode_go_api_key": "",
        "opencode_go_base_url": "https://opencode.ai/zen/go/v1",
        "ollama_host": "http://localhost:11434",
        "nexus_enable_ollama": False,
        "airllm_experimental_enabled": False,
        "local_llm_device": "cpu",
        "local_llm_compression": "",
        "openai_api_key": "",
        "kimi_api_key": "",
        "deepseek_api_key": "",
        "groq_api_key": "",
        "anthropic_api_key": "",
        "gemini_api_key": "",
        "openrouter_api_key": "",
        "lmstudio_host": "http://localhost:1234/v1",
        "lmstudio_api_key": "",
        "lmstudio_default_model": "lfm2.5-2.6b-heretic-abliterated",
        "lmstudio_fast_model": "lfm2.5-2.6b-heretic-abliterated",
        "lmstudio_coder_model": "lfm2.5-2.6b-heretic-abliterated",
    }
    base.update(extra)
    return SimpleNamespace(**base)


def _no_network(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    """Stub settings/runtime overrides so no live discovery or HTTP happens."""
    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    monkeypatch.setattr(factory, "_load_runtime_overrides", lambda: {})
    monkeypatch.setattr(
        factory, "_free_only_enabled", lambda _s, _o: bool(getattr(settings, "free_only", True))
    )
    import backend.llm.model_catalog as catalog

    monkeypatch.setattr(catalog, "load_validated_models", lambda _provider: [])


@pytest.mark.asyncio
async def test_create_llm_client_lmstudio_builds_resilient_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM_PROVIDER=lmstudio must build the real provider, not the Ollama fallback."""
    settings = _settings(free_only=False)
    _no_network(monkeypatch, settings)

    client = create_llm_client(policy_candidates=[])
    assert isinstance(client, ResilientLLMProvider)
    assert client.primary.__class__.__name__ == "LMStudioProvider"
    assert client.provider_name == "lmstudio"
    assert client.primary._base_url == "http://localhost:1234"
    await client.aclose()


@pytest.mark.asyncio
async def test_free_only_policy_does_not_block_lmstudio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LM Studio is a zero-cost local server: fail-closed policy must allow it."""
    settings = _settings(free_only=True)
    _no_network(monkeypatch, settings)

    client = create_llm_client(policy_candidates=[])
    assert isinstance(client, ResilientLLMProvider)
    assert client.primary.__class__.__name__ == "LMStudioProvider"
    assert client.primary._free_validated is True
    await client.aclose()


@pytest.mark.asyncio
async def test_lmstudio_primary_reads_env_backed_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host/api-key/tier models must come from the LMSTUDIO_* settings fields."""
    settings = _settings(
        free_only=False,
        lmstudio_host="http://127.0.0.1:9999/v1",
        lmstudio_api_key="sk-local",
        lmstudio_default_model="model-a",
        lmstudio_fast_model="model-b",
        lmstudio_coder_model="model-c",
    )
    _no_network(monkeypatch, settings)

    client = create_llm_client(policy_candidates=[])
    primary = client.primary
    assert primary._base_url == "http://127.0.0.1:9999"
    assert primary._client.headers["authorization"] == "Bearer sk-local"
    assert primary._default_model == "model-a"
    assert primary._fast_model == "model-b"
    assert primary._coder_model == "model-c"
    await client.aclose()


def test_validate_model_fails_open() -> None:
    """Unknown model ids are accepted; the server answers 404 at call time."""
    provider = LMStudioProvider(read_timeout=30.0)
    try:
        assert provider.validate_model("whatever-model") == "whatever-model"
        assert provider.validate_model("lfm2.5-2.6b-heretic-abliterated") == (
            "lfm2.5-2.6b-heretic-abliterated"
        )
    finally:
        asyncio.run(provider.aclose())


def test_resolve_model_maps_tiers_to_configured_ids() -> None:
    """Router tiers resolve through the LMSTUDIO_*_MODEL settings fields."""
    provider = LMStudioProvider(
        read_timeout=30.0,
        default_model="default-id",
        fast_model="fast-id",
        coder_model="coder-id",
    )
    try:
        assert provider.resolve_model("micro") == "default-id"
        assert provider.resolve_model("fast") == "fast-id"
        assert provider.resolve_model("coder") == "coder-id"
        # Concrete ids are used verbatim.
        assert provider.resolve_model("lfm2.5-2.6b-heretic-abliterated") == (
            "lfm2.5-2.6b-heretic-abliterated"
        )
    finally:
        asyncio.run(provider.aclose())


def test_read_timeout_defaults_do_not_change_cloud() -> None:
    """Cloud OpenAI-compatible providers keep the 120s read timeout."""
    cloud = OpenAIProvider("https://api.example.test/v1", api_key="k")
    try:
        assert cloud._read_timeout == 120.0
    finally:
        asyncio.run(cloud.aclose())


def test_lmstudio_read_timeout_is_configurable_and_long_by_default() -> None:
    provider = LMStudioProvider(read_timeout=900.0)
    try:
        assert provider._read_timeout == 900.0
        assert provider._client.timeout.read == 900.0
    finally:
        asyncio.run(provider.aclose())
    assert DEFAULT_READ_TIMEOUT == 600.0


@pytest.mark.asyncio
async def test_stream_options_rejected_is_retried_without_it() -> None:
    """A strict server that 400s on stream_options gets one clean retry."""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        if payload.get("stream_options"):
            return httpx.Response(
                400, json={"error": {"message": "stream_options is not supported"}}
            )
        return httpx.Response(
            200,
            content=b'data: {"choices":[{"delta":{"content":"oi"}}]}\n\ndata: [DONE]\n\n',
        )

    provider = LMStudioProvider("http://localhost:1234/v1", read_timeout=30.0)
    provider._client = httpx.AsyncClient(
        base_url="http://localhost:1234",
        transport=httpx.MockTransport(handler),
    )
    try:
        tokens = [
            token
            async for token in provider.chat_stream(
                "lfm2.5-2.6b-heretic-abliterated",
                [{"role": "user", "content": "hello"}],
            )
        ]
        assert tokens == ["oi"]
        assert provider._send_stream_options is False
        assert len(calls) == 2
        assert calls[0].get("stream_options") == {"include_usage": True}
        assert "stream_options" not in calls[1]
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_stream_options_send_can_be_disabled_upfront() -> None:
    """send_stream_options=False never adds the parameter to the payload."""
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            content=b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n',
        )

    provider = LMStudioProvider("http://localhost:1234/v1", read_timeout=30.0)
    provider._client = httpx.AsyncClient(
        base_url="http://localhost:1234",
        transport=httpx.MockTransport(handler),
    )
    provider._send_stream_options = False
    try:
        tokens = [
            token
            async for token in provider.chat_stream("model", [{"role": "user", "content": "hi"}])
        ]
        assert tokens == ["ok"]
        assert len(payloads) == 1
        assert "stream_options" not in payloads[0]
    finally:
        await provider.aclose()


def test_allowed_providers_includes_lmstudio() -> None:
    """The chat route must accept provider='lmstudio' from the frontend."""
    from backend.orchestrator.routes import chat

    source = inspect.getsource(chat)
    match = re.search(
        r"ALLOWED_PROVIDERS[^=]*=\s*frozenset\(\s*\{(.*?)\}", source, re.DOTALL
    )
    assert match, "ALLOWED_PROVIDERS not found in chat routes"
    assert '"lmstudio"' in match.group(1)


def test_provider_specs_include_lmstudio() -> None:
    """Model discovery must know the local server (no key required)."""
    spec = PROVIDER_SPECS.get("lmstudio")
    assert spec is not None
    assert spec["requires_key"] is False
    assert spec["key_setting"] == "lmstudio_api_key"
    assert spec["base_setting"] == "lmstudio_host"
    assert spec["default_base"] == "http://localhost:1234/v1"
