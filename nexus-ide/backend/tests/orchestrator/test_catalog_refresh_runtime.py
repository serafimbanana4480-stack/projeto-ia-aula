"""A model selector refresh must update the running provider's policy view."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from backend.llm.model_catalog import DiscoveryResult, ModelInfo
from backend.llm.openrouter_provider import OpenRouterProvider
from backend.orchestrator.routes import providers


def _model() -> ModelInfo:
    return ModelInfo(
        id="example/coder:free", provider="openrouter", name="Example",
        input_price_per_1m=0.0, output_price_per_1m=0.0,
        quota_available=True, validated_at=time.time(),
    )


@pytest.mark.asyncio
async def test_fresh_model_refresh_reaches_running_provider(monkeypatch) -> None:
    client = OpenRouterProvider(api_key="test", free_only=True, catalog=[])
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(llm_client=client)))

    async def discover(_provider, *, refresh):
        assert refresh
        return DiscoveryResult("openrouter", [_model()])

    monkeypatch.setattr(providers, "discover_models", discover)
    response = await providers.provider_models("openrouter", request, refresh=True, _user={})
    assert response["error"] is None
    assert client.validate_model("example/coder:free") == "example/coder:free"
    await client.aclose()


@pytest.mark.asyncio
async def test_failed_refresh_does_not_replace_provider_catalog(monkeypatch) -> None:
    existing = _model()
    client = OpenRouterProvider(api_key="test", free_only=True, catalog=[existing])
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(llm_client=client)))

    async def discover(_provider, *, refresh):
        return DiscoveryResult("openrouter", [_model()], cached=True, error="catalog expired")

    monkeypatch.setattr(providers, "discover_models", discover)
    response = await providers.provider_models("openrouter", request, refresh=True, _user={})
    assert response["error"] == "catalog expired"
    assert client._catalog == [existing]
    await client.aclose()


@pytest.mark.asyncio
async def test_catalog_update_handles_cyclic_provider_wrappers() -> None:
    from backend.llm.model_catalog import apply_catalog_to_llm_client

    client = OpenRouterProvider(api_key="test", free_only=True, catalog=[])
    wrapper = SimpleNamespace(primary=client)
    wrapper.fallbacks = [wrapper, client]
    assert apply_catalog_to_llm_client(wrapper, "openrouter", [_model()]) == 1
    assert client.validate_model("example/coder:free") == "example/coder:free"
    await client.aclose()
