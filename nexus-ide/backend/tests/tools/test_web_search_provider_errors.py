from __future__ import annotations

import asyncio

import pytest

from backend.tools import web_search


def test_all_provider_failures_raise_instead_of_becoming_cached_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = "provider-outage-regression-2026-09-28"

    async def brave_fails(*_args: object, **_kwargs: object) -> list[web_search.SearchHit]:
        raise web_search.SearchProviderError("brave")

    async def duckduckgo_fails(
        *_args: object,
        **_kwargs: object,
    ) -> list[web_search.SearchHit]:
        raise web_search.SearchProviderError("duckduckgo")

    monkeypatch.setattr(web_search, "_search_brave", brave_fails)
    monkeypatch.setattr(web_search, "_search_duckduckgo", duckduckgo_fails)

    with pytest.raises(web_search.SearchProvidersUnavailable):
        asyncio.run(web_search.search_web(query, max_results=3))

    async def duckduckgo_recovers(
        *_args: object,
        **_kwargs: object,
    ) -> list[web_search.SearchHit]:
        return [
            web_search.SearchHit(
                title="Recovered result",
                url="https://example.test/recovered",
                snippet="Provider recovered",
                source_engine="duckduckgo",
            )
        ]

    monkeypatch.setattr(web_search, "_search_duckduckgo", duckduckgo_recovers)
    result = asyncio.run(web_search.search_web(query, max_results=3))

    assert result["count"] == 1
    assert result["hits"][0]["title"] == "Recovered result"


def test_empty_results_are_kept_when_a_provider_responds_successfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_brave_key(*_args: object, **_kwargs: object) -> list[web_search.SearchHit]:
        return []

    async def no_matches(*_args: object, **_kwargs: object) -> list[web_search.SearchHit]:
        return []

    monkeypatch.setattr(web_search, "_search_brave", no_brave_key)
    monkeypatch.setattr(web_search, "_search_duckduckgo", no_matches)

    result = asyncio.run(web_search.search_web("genuinely-empty-result-2026-09-28", max_results=3))

    assert result["count"] == 0
    assert result["hits"] == []
