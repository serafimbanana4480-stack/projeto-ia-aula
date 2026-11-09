from __future__ import annotations

import asyncio
import time

import pytest

from backend.llm import model_catalog as catalog


@pytest.mark.asyncio
async def test_parallel_discoveries_preserve_both_provider_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "CACHE_PATH", tmp_path / "catalog.json")
    monkeypatch.setattr(catalog, "resolve_credentials", lambda provider: ("key", "https://example.test"))
    barrier = asyncio.Event()
    calls = 0

    async def fetch(provider, _key, _base):
        nonlocal calls
        calls += 1
        if calls == 2:
            barrier.set()
        await barrier.wait()
        return [catalog.ModelInfo(id=provider, provider=provider, name=provider, validated_at=time.time())]

    monkeypatch.setattr(catalog, "_fetch_models", fetch)
    await asyncio.gather(catalog.discover_models("openrouter", refresh=True),
                         catalog.discover_models("kilo", refresh=True))
    assert set(catalog._load_cache()) == {"openrouter", "kilo"}


@pytest.mark.asyncio
async def test_expired_cache_attempts_live_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "CACHE_PATH", tmp_path / "catalog.json")
    monkeypatch.setattr(catalog, "resolve_credentials", lambda provider: ("key", "https://example.test"))
    old = catalog.ModelInfo(id="old", provider="openrouter", name="old", validated_at=1)
    catalog._write_cache({"openrouter": {"fetched_at": 1, "models": [old.to_dict()]}})

    async def fetch(provider, _key, _base):
        return [catalog.ModelInfo(id="new", provider=provider, name="new", validated_at=time.time())]

    monkeypatch.setattr(catalog, "_fetch_models", fetch)
    result = await catalog.discover_models("openrouter")
    assert [model.id for model in result.models] == ["new"]
    assert result.error is None
