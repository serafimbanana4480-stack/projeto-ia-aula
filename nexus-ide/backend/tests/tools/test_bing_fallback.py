"""Offline tests for the keyless Bing fallback used by web research.

Brave requires an API key and DuckDuckGo's HTML endpoint can answer with an
empty bot-check page. Bing's organic results keep research working without
credentials, but its redirect URLs must be decoded before they reach the
model. No network is used here.
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock

import pytest

from backend.tools import web_search, web_search_v2


def _bing_href(url: str) -> str:
    encoded = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")
    return f"https://www.bing.com/ck/a?!&&p=abc&u=a1{encoded}&ntb=1"


def _markup(*entries: tuple[str, str, str]) -> str:
    blocks = []
    for href, title, snippet in entries:
        blocks.append(
            '<li class="b_algo">'
            f'<h2><a href="{href}">{title}</a></h2>'
            f'<div class="b_caption"><p>{snippet}</p></div>'
            "</li>"
        )
    return f'<html><body><ol id="b_results">{"".join(blocks)}</ol></body></html>'


@pytest.mark.parametrize("module", [web_search, web_search_v2])
def test_bing_redirect_is_decoded_to_the_real_page(module) -> None:
    href = _bing_href("https://docs.python.org/3/library/asyncio-task.html")
    assert module._decode_bing_redirect(href) == (
        "https://docs.python.org/3/library/asyncio-task.html"
    )


@pytest.mark.parametrize("module", [web_search, web_search_v2])
def test_bing_parser_extracts_title_snippet_and_safe_urls(module) -> None:
    markup = _markup(
        (
            _bing_href("https://docs.python.org/3/library/asyncio-task.html"),
            "Coroutines and Tasks",
            "asyncio.wait_for waits for a coroutine with a timeout.",
        ),
        ("javascript:alert(1)", "Unsafe", "must be dropped"),
        ("/relative/result", "Relative", "must be dropped"),
    )

    hits = module._parse_bing_hits(markup, max_results=5)

    assert [hit.url for hit in hits] == [
        "https://docs.python.org/3/library/asyncio-task.html"
    ]
    assert hits[0].title == "Coroutines and Tasks"
    assert "wait_for" in hits[0].snippet
    assert hits[0].source_engine == "bing"


@pytest.mark.asyncio
@pytest.mark.parametrize("module", [web_search, web_search_v2])
async def test_empty_brave_and_duckduckgo_still_use_bing(module, monkeypatch) -> None:
    async def empty(*_args, **_kwargs):
        return []

    async def bing(*_args, **_kwargs):
        return [
            module.SearchHit(
                title="Bing result",
                url="https://example.test/bing-result",
                snippet="keyless fallback",
                source_engine="bing",
            )
        ]

    monkeypatch.setattr(module, "_search_brave", empty)
    monkeypatch.setattr(module, "_search_duckduckgo", empty)
    monkeypatch.setattr(module, "_search_bing", bing)

    kwargs = {"query": "keyless fallback", "max_results": 3, "site_filter": None}
    if module is web_search_v2:
        kwargs["recency_days"] = None

    hits = await module._search_with_fallback(**kwargs)

    assert [hit.title for hit in hits] == ["Bing result"]


@pytest.mark.asyncio
@pytest.mark.parametrize("module", [web_search, web_search_v2])
async def test_bing_outage_is_reported_not_silently_empty(module, monkeypatch) -> None:
    async def empty(*_args, **_kwargs):
        return []

    async def duckduckgo_fails(*_args, **_kwargs):
        raise module.SearchProviderError("duckduckgo")

    monkeypatch.setattr(module, "_search_brave", empty)
    monkeypatch.setattr(module, "_search_duckduckgo", duckduckgo_fails)
    monkeypatch.setattr(
        module,
        "_search_bing",
        AsyncMock(side_effect=module.SearchProviderError("bing")),
    )
    monkeypatch.setattr(web_search, "get_brave_api_key", lambda: "")
    monkeypatch.setattr(module, "_search_bing_news", empty)
    monkeypatch.setattr(module, "_search_stackexchange", empty)

    kwargs = {"query": "outage", "max_results": 3, "site_filter": None}
    if module is web_search_v2:
        kwargs["recency_days"] = None

    with pytest.raises(module.SearchProvidersUnavailable):
        await module._search_with_fallback(**kwargs)
