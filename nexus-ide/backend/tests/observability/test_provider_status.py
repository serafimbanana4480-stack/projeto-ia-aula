"""Provider status must reflect a directly configured LLM client."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.llm.factory import ResilientLLMProvider
from backend.observability.routes.metrics import get_providers_status


class OpenRouterProvider:
    pass


@pytest.mark.asyncio
async def test_direct_provider_is_reported_as_available() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(llm_client=OpenRouterProvider()))
    )

    result = await get_providers_status(request, _user={"id": "test"})

    assert result["providers"]["openrouter"]["healthy"] is True
    assert "Unsupported LLM client" not in result.get("note", "")


@pytest.mark.asyncio
async def test_resilient_provider_reports_observed_real_fallback() -> None:
    primary = OpenRouterProvider()

    class OllamaProvider:
        provider_name = "ollama"
        simulation = False

    fallback = OllamaProvider()
    client = ResilientLLMProvider(primary, [fallback], free_only=True)
    client.last_provider = fallback
    client.last_provider_at = 1234.0
    client.last_provider_latency_ms = 42.5
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(llm_client=client)))

    result = await get_providers_status(request, _user={"id": "test"})

    assert result["providers"]["ollama"]["healthy"] is True
    assert result["providers"]["ollama"]["runtime_observed"] is True
    assert result["providers"]["ollama"]["latency"] == 42.5
    assert result["providers"]["openrouter"]["last_check"] is None
