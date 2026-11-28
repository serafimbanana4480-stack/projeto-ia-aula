"""Offline tests for search quality: relevance filtering and keyless fallbacks.

Live observation (2026-11-21): Bing's keyless HTML endpoint answered a
"James Webb Space Telescope" query with results about the band *James*, and a
"python asyncio timeout" query with generic Python pages. Those hits are
worse than no answer because the model would answer about the wrong subject.
These tests pin the filter and the two structured fallbacks that replace the
degraded results. No network is used.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.tools import web_search, web_search_v2


def _hit(module: Any, title: str, url: str, snippet: str = "", engine: str = "bing"):
    return module.SearchHit(
        title=title,
        url=url,
        snippet=snippet,
        source_engine=engine,
    )


@pytest.mark.parametrize("module", [web_search, web_search_v2])
def test_query_terms_ignore_stopwords_and_accents(module) -> None:
    assert module._query_terms("Receita de bacalhau à brás") == [
        "receita",
        "bacalhau",
        "bras",
    ]
    assert module._query_terms("the python asyncio timeout") == [
        "python",
        "asyncio",
        "timeout",
    ]


@pytest.mark.parametrize("module", [web_search, web_search_v2])
def test_first_word_only_bing_hit_is_not_relevant(module) -> None:
    terms = module._query_terms("James Webb Space Telescope recent discoveries")
    band = _hit(
        module,
        "James playlist - BEST songs - YouTube",
        "https://www.youtube.com/playlist?list=abc",
        "The BEST songs of the band James.",
    )
    space = _hit(
        module,
        "James Webb telescope spots giant star swallowing its companion",
        "https://www.space.com/jwst-star",
        "James Webb Space Telescope observed a merger.",
    )

    assert module._hit_matches_query(band, terms) is False
    assert module._hit_matches_query(space, terms) is True


@pytest.mark.parametrize("module", [web_search, web_search_v2])
def test_single_term_queries_are_not_over_filtered(module) -> None:
    terms = module._query_terms("python")
    assert module._hit_matches_query(
        _hit(module, "Welcome to Python.org", "https://www.python.org/"), terms
    )


@pytest.mark.parametrize("module", [web_search, web_search_v2])
def test_news_rss_unwraps_direct_urls_and_drops_unsafe_links(module) -> None:
    markup = """
    <rss><channel>
      <item>
        <title><![CDATA[JWST spots a new exoplanet]]></title>
        <link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;url=https%3a%2f%2fwww.space.com%2fjwst-exoplanet</link>
        <description>&lt;p&gt;The telescope found water.&lt;/p&gt;</description>
        <pubDate>Tue, 10 Nov 2026 05:05:00 GMT</pubDate>
      </item>
      <item>
        <title>Unsafe</title>
        <link>javascript:alert(1)</link>
      </item>
      <item>
        <title>Relative</title>
        <link>/news/local</link>
      </item>
    </channel></rss>
    """

    hits = module._parse_bing_news_rss(markup, max_results=5)

    assert len(hits) == 1
    assert hits[0].url == "https://www.space.com/jwst-exoplanet"
    assert hits[0].title == "JWST spots a new exoplanet"
    assert "water" in hits[0].snippet
    assert hits[0].source_engine == "bing_news"
    assert "2026" in hits[0].age_hint


@pytest.mark.asyncio
@pytest.mark.parametrize("module", [web_search, web_search_v2])
async def test_irrelevant_bing_hits_fall_back_to_news(module, monkeypatch) -> None:
    async def empty(*_args: Any, **_kwargs: Any):
        return []

    async def irrelevant(*_args: Any, **_kwargs: Any):
        return [
            _hit(
                module,
                "the official JAMES website",
                "https://wearejames.com/",
                "The band James.",
            )
        ]

    async def news(*_args: Any, **_kwargs: Any):
        return [
            _hit(
                module,
                "James Webb Space Telescope discovers water on exoplanet",
                "https://www.space.com/jwst-water",
                "JWST found water.",
                engine="bing_news",
            )
        ]

    monkeypatch.setattr(module, "_search_brave", empty)
    monkeypatch.setattr(module, "_search_duckduckgo", empty)
    monkeypatch.setattr(module, "_search_bing", irrelevant)
    monkeypatch.setattr(module, "_search_bing_news", news)
    monkeypatch.setattr(module, "_search_stackexchange", empty)

    kwargs: dict[str, Any] = {
        "query": "James Webb Space Telescope discoveries",
        "max_results": 3,
        "site_filter": None,
    }
    if module is web_search_v2:
        kwargs["recency_days"] = None

    hits = await module._search_with_fallback(**kwargs)

    assert [hit.source_engine for hit in hits] == ["bing_news"]
    assert "Webb" in hits[0].title


@pytest.mark.asyncio
@pytest.mark.parametrize("module", [web_search, web_search_v2])
async def test_irrelevant_hits_plus_a_down_provider_is_not_an_outage(module, monkeypatch) -> None:
    """Live regression (2026-11-21): Bing answered that query with band hits
    while DuckDuckGo bot-checked, and the tool reported every provider as
    unavailable. A provider did answer -- there is simply nothing relevant."""

    async def empty(*_args: Any, **_kwargs: Any):
        return []

    async def irrelevant(*_args: Any, **_kwargs: Any):
        return [
            _hit(
                module,
                "the official JAMES website",
                "https://wearejames.com/",
                "The band James.",
            )
        ]

    async def duckduckgo_fails(*_args: Any, **_kwargs: Any):
        raise module.SearchProviderError("duckduckgo")

    monkeypatch.setattr(module, "_search_brave", empty)
    monkeypatch.setattr(module, "_search_duckduckgo", duckduckgo_fails)
    monkeypatch.setattr(module, "_search_bing", irrelevant)
    monkeypatch.setattr(module, "_search_bing_news", empty)
    monkeypatch.setattr(module, "_search_stackexchange", empty)

    kwargs: dict[str, Any] = {
        "query": "python asyncio timeout best practice",
        "max_results": 3,
        "site_filter": None,
    }
    if module is web_search_v2:
        kwargs["recency_days"] = None

    assert await module._search_with_fallback(**kwargs) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("module", [web_search, web_search_v2])
async def test_programming_query_falls_back_to_stackexchange(module, monkeypatch) -> None:
    async def empty(*_args: Any, **_kwargs: Any):
        return []

    async def generic_python(*_args: Any, **_kwargs: Any):
        return [
            _hit(
                module,
                "Welcome to Python.org",
                "https://www.python.org/",
                "The official home of Python.",
            )
        ]

    async def stackoverflow(*_args: Any, **_kwargs: Any):
        return [
            _hit(
                module,
                "Python asyncio force timeout",
                "https://stackoverflow.com/questions/28609534/python-asyncio-force-timeout",
                "[python, python-asyncio] · respondida · score 12",
                engine="stackexchange",
            )
        ]

    monkeypatch.setattr(module, "_search_brave", empty)
    monkeypatch.setattr(module, "_search_duckduckgo", empty)
    monkeypatch.setattr(module, "_search_bing", generic_python)
    monkeypatch.setattr(module, "_search_bing_news", empty)
    monkeypatch.setattr(module, "_search_stackexchange", stackoverflow)

    kwargs: dict[str, Any] = {
        "query": "python asyncio timeout",
        "max_results": 3,
        "site_filter": None,
    }
    if module is web_search_v2:
        kwargs["recency_days"] = None

    hits = await module._search_with_fallback(**kwargs)

    assert [hit.source_engine for hit in hits] == ["stackexchange"]


@pytest.mark.asyncio
@pytest.mark.parametrize("module", [web_search, web_search_v2])
async def test_fallback_outage_yields_no_results_not_an_invented_hit(module, monkeypatch) -> None:
    async def empty(*_args: Any, **_kwargs: Any):
        return []

    monkeypatch.setattr(module, "_search_brave", empty)
    monkeypatch.setattr(module, "_search_duckduckgo", empty)
    monkeypatch.setattr(module, "_search_bing", empty)
    monkeypatch.setattr(
        module,
        "_search_bing_news",
        _raise_provider(module, "bing_news"),
    )
    monkeypatch.setattr(
        module,
        "_search_stackexchange",
        _raise_provider(module, "stackexchange"),
    )

    kwargs: dict[str, Any] = {"query": "anything at all", "max_results": 3, "site_filter": None}
    if module is web_search_v2:
        kwargs["recency_days"] = None

    # The general providers answered (empty). The fallbacks are down, but that
    # makes the answer unknown, not invented: an empty list is the honest
    # result, never a fabricated hit and never "all providers unavailable".
    assert await module._search_with_fallback(**kwargs) == []


@pytest.mark.parametrize("module", [web_search, web_search_v2])
def test_site_name_page_title_is_replaced_by_the_article_title(module) -> None:
    """``<title>MSN</title>`` is not a citation label; the hit title is."""
    hit_title = "Scientists just made James Webb 15 times more sensitive to faint planets"
    assert module._prefer_descriptive_title("MSN", hit_title) == hit_title
    assert module._prefer_descriptive_title("", hit_title) == hit_title
    long_title = "Northwestern astrophysicists develop method for detecting distant planets"
    assert module._prefer_descriptive_title(long_title, hit_title) == long_title


@pytest.mark.asyncio
@pytest.mark.parametrize("module", [web_search, web_search_v2])
async def test_empty_answer_from_one_provider_plus_a_down_one_is_no_results(
    module, monkeypatch
) -> None:
    """Live regression: Bing answered an unusual query with no hits while
    DuckDuckGo bot-checked; that is "nothing found", not "providers down"."""

    async def empty(*_args: Any, **_kwargs: Any):
        return []

    async def duckduckgo_fails(*_args: Any, **_kwargs: Any):
        raise module.SearchProviderError("duckduckgo")

    monkeypatch.setattr(module, "_search_brave", empty)
    monkeypatch.setattr(module, "_search_duckduckgo", duckduckgo_fails)
    monkeypatch.setattr(module, "_search_bing", empty)
    monkeypatch.setattr(module, "_search_bing_news", empty)
    monkeypatch.setattr(module, "_search_stackexchange", empty)

    kwargs: dict[str, Any] = {
        "query": "Andromeda galaxy new image 2026",
        "max_results": 3,
        "site_filter": None,
    }
    if module is web_search_v2:
        kwargs["recency_days"] = None

    assert await module._search_with_fallback(**kwargs) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("module", [web_search, web_search_v2])
async def test_all_configured_providers_down_still_raises(module, monkeypatch) -> None:
    async def fails(*_args: Any, **_kwargs: Any):
        raise module.SearchProviderError("down")

    monkeypatch.setattr(module, "_search_brave", fails)
    monkeypatch.setattr(module, "_search_duckduckgo", fails)
    monkeypatch.setattr(module, "_search_bing", fails)

    kwargs: dict[str, Any] = {"query": "outage", "max_results": 3, "site_filter": None}
    if module is web_search_v2:
        kwargs["recency_days"] = None

    with pytest.raises(module.SearchProvidersUnavailable):
        await module._search_with_fallback(**kwargs)


def _raise_provider(module: Any, name: str):
    async def _raise(*_args: Any, **_kwargs: Any):
        raise module.SearchProviderError(name)

    return _raise


@pytest.mark.asyncio
@pytest.mark.parametrize("module", [web_search, web_search_v2])
async def test_stackexchange_parses_api_items(module, monkeypatch) -> None:
    class FakeResponse:
        def json(self) -> dict[str, Any]:
            return {
                "items": [
                    {
                        "title": "Python asyncio force timeout",
                        "link": "https://stackoverflow.com/questions/28609534/python-asyncio-force-timeout",
                        "tags": ["python", "python-asyncio"],
                        "is_answered": True,
                        "score": 12,
                        "creation_date": 1424357903,
                    },
                    {
                        "title": "Unsafe link",
                        "link": "javascript:alert(1)",
                        "tags": [],
                        "is_answered": False,
                        "score": 0,
                        "creation_date": 0,
                    },
                ]
            }

    async def fake_request(*_args: Any, **_kwargs: Any):
        return FakeResponse()

    monkeypatch.setattr(module, "_request_with_retry", fake_request)

    hits = await module._search_stackexchange("python asyncio timeout", max_results=5)

    assert len(hits) == 1
    assert hits[0].url.startswith("https://stackoverflow.com/questions/")
    assert hits[0].source_engine == "stackexchange"
    assert "python-asyncio" in hits[0].snippet


@pytest.mark.asyncio
@pytest.mark.parametrize("module", [web_search, web_search_v2])
async def test_stackexchange_is_skipped_for_other_sites(module) -> None:
    assert await module._search_stackexchange(
        "python asyncio timeout", max_results=5, site_filter="docs.python.org"
    ) == []


@pytest.mark.parametrize("module", [web_search, web_search_v2])
def test_news_query_drops_year_and_month_tokens(module) -> None:
    """Live check: dated news queries returned no RSS items, undated ones did."""
    assert (
        module._simplify_news_query("Portugal wildfires November 2026")
        == "Portugal wildfires"
    )
    assert (
        module._simplify_news_query("incêndios em Portugal novembro 2026")
        == "incêndios em Portugal"
    )
    assert module._simplify_news_query("James Webb discoveries") == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("module", [web_search, web_search_v2])
async def test_dated_news_query_retries_once_without_time_tokens(module, monkeypatch) -> None:
    queries: list[str] = []

    class FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text

    filled_rss = (
        "<rss><channel><item>"
        "<title>Incêndios em Portugal obrigam a evacuações</title>"
        "<link>https://www.reuters.com/world/europe/portugal-wildfires</link>"
        "<description>Cerca de 900 bombeiros combatem as chamas.</description>"
        "<pubDate>Thu, 20 Nov 2026 10:00:00 GMT</pubDate>"
        "</item></channel></rss>"
    )

    async def fake_request(*_args: Any, **kwargs: Any):
        queries.append(kwargs["params"]["q"])
        return FakeResponse(
            "<rss><channel></channel></rss>" if len(queries) == 1 else filled_rss
        )

    monkeypatch.setattr(module, "_request_with_retry", fake_request)

    hits = await module._search_bing_news("Portugal wildfires November 2026", max_results=3)

    assert queries == ["Portugal wildfires November 2026", "Portugal wildfires"]
    assert [hit.source_engine for hit in hits] == ["bing_news"]
    assert "Portugal" in hits[0].title


@pytest.mark.asyncio
@pytest.mark.parametrize("module", [web_search, web_search_v2])
async def test_undated_news_query_is_requested_once(module, monkeypatch) -> None:
    queries: list[str] = []

    class FakeResponse:
        text = "<rss><channel></channel></rss>"

    async def fake_request(*_args: Any, **kwargs: Any):
        queries.append(kwargs["params"]["q"])
        return FakeResponse()

    monkeypatch.setattr(module, "_request_with_retry", fake_request)

    assert await module._search_bing_news("inflation report", max_results=3) == []
    assert queries == ["inflation report"]
