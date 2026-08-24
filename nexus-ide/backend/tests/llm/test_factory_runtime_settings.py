"""Regression tests for runtime LLM configuration and provider selection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.llm import factory
from backend.llm.free_policy import ProviderUnavailableError
from backend.llm.multi_llm_manager import MultiLLMManager


@pytest.fixture(autouse=True)
def _legacy_factory_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests cover paid provider construction, not the free-only policy."""
    monkeypatch.setenv("NEXUS_FREE_ONLY", "false")


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


@pytest.mark.asyncio
async def test_single_provider_ollama_selection_is_an_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Settings provider dropdown must be sufficient for local chat."""
    settings = _settings()
    settings.multi_llm_enabled = False
    settings.llm_provider = "ollama"
    settings.nexus_enable_ollama = False
    settings.free_only = False
    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    monkeypatch.setattr(factory, "_load_runtime_overrides", lambda: {})

    client = factory.create_llm_client()
    assert client.__class__.__name__ == "ResilientLLMProvider"
    assert client.primary.__class__.__name__ == "OllamaProvider"
    assert client.provider_name == "ollama"
    await client.aclose()


@pytest.mark.asyncio
async def test_kilo_selection_blocked_under_free_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit 2026-08-24 (B3): kilo é um gateway PAGO.

    Com NEXUS_FREE_ONLY=true a seleção direta de kilo tem de falhar — antes,
    o provider era construído e podia gastar dinheiro real com a política
    fail-closed aparentemente ativa.
    """
    settings = _settings()
    settings.multi_llm_enabled = False
    settings.llm_provider = "kilo"
    settings.free_only = True
    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    monkeypatch.setattr(factory, "_load_runtime_overrides", lambda: {})

    with pytest.raises(ProviderUnavailableError) as excinfo:
        factory.create_llm_client(kilo_api_key="test-kilo-key")
    assert excinfo.value.category == "eligibility"


@pytest.mark.asyncio
async def test_kilo_selection_builds_provider_when_paid_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Com free_only desativado, kilo continua selecionável (chave presente)."""
    settings = _settings()
    settings.multi_llm_enabled = False
    settings.llm_provider = "kilo"
    settings.free_only = False
    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    monkeypatch.setattr(factory, "_load_runtime_overrides", lambda: {})

    client = factory.create_llm_client(kilo_api_key="test-kilo-key")
    assert client.provider_name == "kilo"
    assert client.primary.__class__.__name__ == "KiloProvider"
    await client.aclose()
