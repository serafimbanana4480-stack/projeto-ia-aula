"""Regression tests for runtime LLM configuration and provider selection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.llm import factory
from backend.llm.multi_llm_manager import MultiLLMManager


def _settings() -> SimpleNamespace:
    """Minimal settings object used to prove persisted values take effect."""
    return SimpleNamespace(
        llm_provider="openrouter",
        default_provider="openrouter",
        multi_llm_enabled=True,
        opencode_go_api_key="",
        opencode_go_base_url="https://opencode.ai/zen/go/v1",
        ollama_host="http://localhost:11434",
        airllm_experimental_enabled=False,
        local_llm_device="cpu",
        local_llm_compression="",
        openai_api_key="",
        kimi_api_key="",
        deepseek_api_key="",
        groq_api_key="",
        anthropic_api_key="",
        gemini_api_key="",
        openrouter_api_key="",
    )


@pytest.mark.asyncio
async def test_runtime_key_registers_selected_multi_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key saved through Settings must work without a process restart."""
    monkeypatch.setattr(factory, "get_settings", _settings)
    monkeypatch.setattr(
        factory,
        "_load_runtime_overrides",
        lambda: {"llm_provider": "openai", "openai_api_key": "runtime-key"},
    )

    client = factory.create_llm_client()
    assert isinstance(client, MultiLLMManager)
    assert set(client.providers) == {"openai"}
    assert client.get_best_provider() == "openai"
    await client.aclose()


@pytest.mark.asyncio
async def test_runtime_false_disables_multi_manager_and_explicit_value_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """String booleans from JSON must not be interpreted as truthy by Python."""
    monkeypatch.setattr(factory, "get_settings", _settings)
    monkeypatch.setattr(
        factory,
        "_load_runtime_overrides",
        lambda: {
            "multi_llm_enabled": "false",
            "llm_provider": "openai",
            "openai_api_key": "runtime-key",
        },
    )

    client = factory.create_llm_client(openai_api_key="explicit-key")
    assert client.__class__.__name__ == "OpenAIProvider"
    assert client._client.headers["authorization"] == "Bearer explicit-key"
    await client.aclose()


@pytest.mark.asyncio
async def test_explicit_ollama_selection_enables_the_local_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting Ollama in the UI is itself an explicit opt-in."""
    monkeypatch.setattr(factory, "get_settings", _settings)
    monkeypatch.setattr(factory, "_load_runtime_overrides", lambda: {})
    monkeypatch.delenv("NEXUS_ENABLE_OLLAMA", raising=False)

    manager = factory.create_multi_llm_manager(overrides={"llm_provider": "ollama"})
    assert {"ollama", "local"}.issubset(manager.providers)
    assert manager.get_best_provider() == "ollama"
    await manager.aclose()
