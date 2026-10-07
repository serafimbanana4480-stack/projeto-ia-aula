"""Tests for backend.tools.web_search_v2.

Integration tests mock all outbound HTTP calls so the suite remains fast and
does not depend on network connectivity or third-party API keys.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.tools import web_search_v2
from backend.tools.web_search_v2 import (
    FetchedContent,
    SearchHit,
    SearchResult,
    _apply_recency_filter,
    _cross_reference_facts,
    _domain_score,
    _extract_site_filter,
    _parse_age_hint,
    _rank_hits,
    _relevance_score,
    fetch_and_summarize,
    search_and_answer,
    search_docs,
    search_github,
    search_web,
)

# ---------------------------------------------------------------------------
# Mock fixtures — keep tests deterministic and fast
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_search_brave(monkeypatch: pytest.MonkeyPatch):
    """Mock Brave search with a small set of hits."""

    async def _mock(query: str, max_results: int = 10, **kwargs):
        return [
            SearchHit(
                url="https://example.com/python-tutorial",
                title="Python Programming Tutorial",
                snippet=f"Learn python programming — query was {query}",
                source_engine="brave",
                age_hint="2 days ago",
            ),
            SearchHit(
                url="https://github.com/python/cpython",
                title="python/cpython",
                snippet="The Python programming language",
                source_engine="brave",
                age_hint="1 week ago",
            ),
        ][:max_results]

    monkeypatch.setattr("backend.tools.web_search_v2._search_brave", _mock)


@pytest.fixture
def mock_search_duckduckgo(monkeypatch: pytest.MonkeyPatch):
    """Mock DuckDuckGo fallback search."""

    async def _mock(query: str, max_results: int = 10, **kwargs):
        return [
            SearchHit(
                url="https://duckduckgo-result.example.com",
                title="DuckDuckGo Result",
                snippet=f"DuckDuckGo fallback for {query}",
                source_engine="duckduckgo",
            ),
        ][:max_results]

    monkeypatch.setattr("backend.tools.web_search_v2._search_duckduckgo", _mock)


@pytest.fixture
def mock_fetch_jina(monkeypatch: pytest.MonkeyPatch):
    """Mock Jina AI fetch so no real URL is retrieved."""

    async def _mock(url: str, max_length: int = 500):
        return FetchedContent(
            url=url,
            title="Mocked Page Title",
            content=f"Mocked content for {url}",
            summary=f"Mocked summary for {url}"[:max_length],
            published_date="2024-01-01",
            content_length=100,
            extraction_method="jina_ai",
            links=["https://example.com/related"],
        )

    monkeypatch.setattr("backend.tools.web_search_v2._fetch_via_jina", _mock)


@pytest.fixture
def mock_fetch_httpx(monkeypatch: pytest.MonkeyPatch):
    """Mock httpx fallback fetch (should not be needed when Jina is mocked)."""

    async def _mock(url: str, max_length: int = 500):
        return FetchedContent(
            url=url,
            title="Mocked HTTPX Title",
            content=f"Mocked httpx content for {url}",
            summary=f"Mocked httpx summary for {url}"[:max_length],
            extraction_method="httpx_bs4",
            links=[],
        )

    monkeypatch.setattr("backend.tools.web_search_v2._fetch_via_httpx", _mock)


@pytest.fixture
def mock_github_search(monkeypatch: pytest.MonkeyPatch):
    """Mock GitHub repository search."""

    async def _mock(query: str, language: str | None = None, stars_min: int = 100):
        return {
            "query": query,
            "repositories": [
                {
                    "name": "tiangolo/fastapi",
                    "url": "https://github.com/tiangolo/fastapi",
                    "description": "FastAPI framework",
                    "stars": 80000,
                    "language": language or "python",
                    "updated_at": "2024-01-01T00:00:00Z",
                }
            ],
            "count": 1,
            "total_count": 1,
        }

    monkeypatch.setattr("backend.tools.web_search_v2.search_github", _mock)


@pytest.fixture
def search_mocks(
    mock_search_brave,
    mock_search_duckduckgo,
    mock_fetch_jina,
    mock_fetch_httpx,
    mock_github_search,
):
    """Combined fixture for all web search mocks."""
    return None


# ---------------------------------------------------------------------------
# Pure unit tests (no mocks needed)
# ---------------------------------------------------------------------------


class TestSearchHit:
    def test_defaults(self) -> None:
        hit = SearchHit(url="https://example.com", title="Example", snippet="A site")
        assert hit.score == 0.0
        assert hit.source_engine == ""
        assert hit.published_date == ""

    def test_with_score(self) -> None:
        hit = SearchHit(
            url="https://example.com",
            title="Example",
            snippet="A site",
            score=0.95,
            source_engine="brave",
            age_hint="2 days ago",
        )
        assert hit.score == 0.95
        assert hit.source_engine == "brave"


class TestSearchResult:
    def test_structure(self) -> None:
        hits = [SearchHit(url="https://a.com", title="A", snippet="aa")]
        result = SearchResult(
            query="python async",
            sources=hits,
            confidence=0.88,
            search_iterations=3,
        )
        assert result.query == "python async"
        assert len(result.sources) == 1
        assert result.confidence == 0.88


@pytest.mark.asyncio
async def test_v2_brave_search_uses_the_runtime_key_saved_in_search_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.tools import web_search

    captured: dict[str, object] = {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    async def fake_request(_client, method: str, url: str, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return SimpleNamespace(
            json=lambda: {
                "web": {
                    "results": [
                        {
                            "title": "Resultado",
                            "url": "https://example.com/result",
                            "description": "Resultado de teste",
                        }
                    ]
                }
            }
        )

    monkeypatch.setattr(web_search, "get_brave_api_key", lambda: "ui-saved-key")
    monkeypatch.setattr(web_search_v2.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    monkeypatch.setattr(web_search_v2, "_request_with_retry", fake_request)

    hits = await web_search_v2._search_brave("NEXUS")

    assert captured["method"] == "GET"
    headers = captured.get("headers")
    assert isinstance(headers, dict)
    assert headers.get("X-Subscription-Token") == "ui-saved-key"
    assert hits[0].title == "Resultado"
    assert hits[0].source_engine == "brave"


class TestFetchedContent:
    def test_defaults(self) -> None:
        fc = FetchedContent(url="https://example.com")
        assert fc.title == ""
        assert fc.links == []
        assert fc.extraction_method == ""


class TestDomainScore:
    def test_authority_domain(self) -> None:
        assert _domain_score("https://github.com/foo/bar") == 0.25
        assert _domain_score("https://stackoverflow.com/questions/1") == 0.25

    def test_non_authority_domain(self) -> None:
        assert _domain_score("https://random-blog.example.com") == 0.0

    def test_www_stripping(self) -> None:
        assert _domain_score("https://www.github.com/foo") == 0.25


class TestParseAgeHint:
    def test_recent(self) -> None:
        assert _parse_age_hint("2 hours ago") == 1.0
        assert _parse_age_hint("today") == 1.0
        assert _parse_age_hint("1 day ago") == 0.85
        assert _parse_age_hint("3 days ago") == 0.85

    def test_moderate(self) -> None:
        assert _parse_age_hint("2 weeks ago") == 0.7
        assert _parse_age_hint("1 month ago") == 0.5

    def test_old(self) -> None:
        assert _parse_age_hint("1 year ago") == 0.2
        assert _parse_age_hint("5 years ago") == 0.2

    def test_empty(self) -> None:
        assert _parse_age_hint("") == 0.5


class TestRelevanceScore:
    def test_exact_match_boost(self) -> None:
        hit = SearchHit(
            url="https://example.com",
            title="Python async tutorial",
            snippet="Learn async python",
        )
        score = _relevance_score("python async tutorial", hit)
        assert score > 0.5

    def test_no_match(self) -> None:
        hit = SearchHit(
            url="https://example.com",
            title="Unrelated",
            snippet="Nothing here",
        )
        score = _relevance_score("python async", hit)
        assert score < 0.3


class TestRankHits:
    def test_ranking_order(self) -> None:
        hits = [
            SearchHit(url="https://a.com", title="A", snippet="unrelated", score=0.1),
            SearchHit(url="https://github.com/b", title="B", snippet="python async", score=0.1),
            SearchHit(url="https://c.com", title="C", snippet="python async tutorial", score=0.1),
        ]
        ranked = _rank_hits("python async", hits)
        assert ranked[0].url == "https://github.com/b" or ranked[0].url == "https://c.com"
        assert ranked[-1].url == "https://a.com"


class TestExtractSiteFilter:
    def test_with_site(self) -> None:
        q, site = _extract_site_filter("python async site:github.com")
        assert q == "python async"
        assert site == "github.com"

    def test_without_site(self) -> None:
        q, site = _extract_site_filter("python async")
        assert q == "python async"
        assert site is None


class TestApplyRecencyFilter:
    def test_filters(self) -> None:
        assert "today" in _apply_recency_filter("python", 1)
        assert "this week" in _apply_recency_filter("python", 7)
        assert "this month" in _apply_recency_filter("python", 30)
        assert "this year" in _apply_recency_filter("python", 365)
        assert _apply_recency_filter("python", None) == "python"


class TestCrossReferenceFacts:
    def test_empty(self) -> None:
        result = _cross_reference_facts([])
        assert result["phrase_overlap_score"] == 0.0
        assert result["common_phrases"] == []

    def test_single_source_cannot_corroborate_itself(self) -> None:
        # One page has nothing to overlap with: a mid value here would invent
        # corroboration that never happened.
        result = _cross_reference_facts([{"title": "A", "summary": "foo bar baz qux"}])
        assert result["phrase_overlap_score"] == 0.0
        assert result["common_phrases"] == []

    def test_common_phrases(self) -> None:
        summaries = [
            {"title": "A", "summary": "the quick brown fox jumps"},
            {"title": "B", "summary": "the quick brown fox runs"},
        ]
        result = _cross_reference_facts(summaries)
        assert result["phrase_overlap_score"] > 0.0
        assert len(result["common_phrases"]) > 0

    def test_score_is_named_as_lexical_overlap_not_consensus(self) -> None:
        summaries = [
            {"title": "A", "summary": "the quick brown fox jumps"},
            {"title": "B", "summary": "the quick brown fox runs"},
        ]
        result = _cross_reference_facts(summaries)
        assert "consensus_score" not in result
        assert result["basis"] == "phrase_overlap_4gram"

    def test_conflicts_key_is_absent_instead_of_always_empty(self) -> None:
        # An always-empty ``conflicts`` list implies "checked, found none".
        # No claim is extracted here, so the key is not returned at all.
        assert "conflicts" not in _cross_reference_facts([])
        assert "conflicts" not in _cross_reference_facts([{"title": "A", "summary": "a b c d"}])
        summaries = [
            {"title": "A", "summary": "the quick brown fox jumps"},
            {"title": "B", "summary": "the quick brown fox runs"},
        ]
        assert "conflicts" not in _cross_reference_facts(summaries)


# ---------------------------------------------------------------------------
# Integration-style tests — use mocks for all outbound HTTP
# ---------------------------------------------------------------------------


class TestSearchWeb:
    @pytest.mark.asyncio
    async def test_search_web_basic(self, search_mocks) -> None:
        result = await search_web("python programming", max_results=3)
        assert "query" in result
        assert "hits" in result
        assert "count" in result
        assert result["query"] == "python programming"
        assert isinstance(result["hits"], list)
        assert result["count"] >= 1

    @pytest.mark.asyncio
    async def test_search_web_with_site(self, search_mocks) -> None:
        result = await search_web("fastapi site:github.com", max_results=3)
        assert result["query"] == "fastapi site:github.com"
        assert isinstance(result["hits"], list)

    @pytest.mark.asyncio
    async def test_search_web_cache(self, search_mocks) -> None:
        q = "unique_test_query_12345"
        r1 = await search_web(q, max_results=2)
        r2 = await search_web(q, max_results=2)
        assert r1["count"] == r2["count"]

    @pytest.mark.asyncio
    async def test_provider_outage_raises_and_is_not_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        query = "provider-outage-v2-regression-2026-09-28"
        monkeypatch.setattr(
            web_search_v2,
            "_search_brave",
            AsyncMock(side_effect=web_search_v2.SearchProviderError("brave")),
        )
        monkeypatch.setattr(
            web_search_v2,
            "_search_duckduckgo",
            AsyncMock(side_effect=web_search_v2.SearchProviderError("duckduckgo")),
        )

        with pytest.raises(web_search_v2.SearchProvidersUnavailable):
            await search_web(query, max_results=3)

        monkeypatch.setattr(
            web_search_v2,
            "_search_duckduckgo",
            AsyncMock(return_value=[
                SearchHit(
                    url="https://example.test/recovered-v2",
                    title="Recovered v2 result",
                    snippet="Provider recovered",
                    source_engine="duckduckgo",
                )
            ]),
        )
        recovered = await search_web(query, max_results=3)

        assert recovered["count"] == 1
        assert recovered["hits"][0]["title"] == "Recovered v2 result"


class TestFetchAndSummarize:
    @pytest.mark.asyncio
    async def test_fetch_and_summarize_success(self, mock_fetch_jina) -> None:
        result = await fetch_and_summarize("https://example.com", max_length=200)
        assert "url" in result
        assert "title" in result
        assert "summary" in result
        assert result["url"] == "https://example.com"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_fetch_and_summarize_invalid_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Force both fetch strategies to fail
        async def _fail(*args, **kwargs):
            return None

        monkeypatch.setattr("backend.tools.web_search_v2._fetch_via_jina", _fail)
        monkeypatch.setattr("backend.tools.web_search_v2._fetch_via_httpx", _fail)

        result = await fetch_and_summarize(
            "https://this-domain-does-not-exist-12345.invalid", max_length=200
        )
        assert result["status"] == "error"


class TestSearchAndAnswer:
    @pytest.mark.asyncio
    async def test_search_and_answer_structure(self, search_mocks) -> None:
        result = await search_and_answer("what is python", max_results=3)
        assert "query" in result
        assert "sources" in result
        assert "answer" in result
        assert "confidence" in result
        assert "consensus" in result


# ---------------------------------------------------------------------------
# Answer honesty: an answer must never outrun the evidence behind it
# ---------------------------------------------------------------------------


def _fixed_hits() -> list[SearchHit]:
    """Two hits whose relevance score does not depend on the query wording.

    Titles/snippets deliberately contain no query terms, so ``_rank_hits``
    assigns the same low score no matter which query is used. Any change in the
    reported confidence therefore has to come from the fetched pages.
    """
    return [
        SearchHit(
            url="https://example.test/page-a",
            title="zzz",
            snippet="",
            source_engine="brave",
        ),
        SearchHit(
            url="https://example.test/page-b",
            title="yyy",
            snippet="",
            source_engine="brave",
        ),
    ]


def _patch_search(monkeypatch: pytest.MonkeyPatch, hits: list[SearchHit]) -> None:
    async def _mock(*_args: object, **_kwargs: object) -> list[SearchHit]:
        return [SearchHit(**vars(h)) for h in hits]

    monkeypatch.setattr(web_search_v2, "_search_with_fallback", _mock)


def _patch_fetch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    summary_for: dict[str, str] | None = None,
    error_urls: set[str] | None = None,
    raise_urls: set[str] | None = None,
) -> None:
    """Replace the fetch helper with a local stub; no network, no SSRF path."""
    summary_for = summary_for or {}
    error_urls = error_urls or set()
    raise_urls = raise_urls or set()

    async def _mock(url: str, max_length: int = 500) -> dict[str, object]:
        if url in raise_urls:
            raise RuntimeError(f"network unreachable for {url}")
        if url in error_urls:
            return {
                "url": url,
                "title": "",
                "summary": "Error fetching URL: unable to retrieve content",
                "content": "",
                "content_length": 0,
                "extraction_method": "failed",
                "status": "error",
            }
        return {
            "url": url,
            "title": f"Title of {url}",
            "summary": summary_for.get(url, f"page body of {url}"),
            "content": summary_for.get(url, f"page body of {url}"),
            "content_length": 42,
            "extraction_method": "httpx_bs4",
            "published_date": "",
            "status": "success",
        }

    monkeypatch.setattr(web_search_v2, "fetch_and_summarize", _mock)


class TestSearchAndAnswerHonesty:
    @pytest.mark.asyncio
    async def test_all_fetches_failing_emits_no_empty_source_section(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hits = _fixed_hits()
        _patch_search(monkeypatch, hits)
        _patch_fetch(monkeypatch, error_urls={h.url for h in hits})

        result = await search_and_answer("python asyncio tutorial", max_results=2)

        answer = result["answer"]
        assert "## Sources" not in answer
        assert "## Key Findings" not in answer
        assert "Confidence:" not in answer
        assert "confidence" not in answer.lower()
        assert answer == ""
        assert result["error_category"] == "no_evidence"
        assert result["error"]
        assert result["confidence"] == 0.0
        assert result["fetch_failure_count"] == 2
        assert sorted(result["attempted_urls"]) == sorted(h.url for h in hits)

    @pytest.mark.asyncio
    async def test_fetches_raising_also_report_no_evidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hits = _fixed_hits()
        _patch_search(monkeypatch, hits)
        _patch_fetch(monkeypatch, raise_urls={h.url for h in hits})

        result = await search_and_answer("python asyncio tutorial", max_results=2)

        assert result["answer"] == ""
        assert result["error_category"] == "no_evidence"
        assert result["confidence"] == 0.0
        assert result["fetch_failure_count"] == 2

    @pytest.mark.asyncio
    async def test_confidence_comes_from_fetched_evidence_not_hit_scores(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Identical hits, different retrieved pages => different confidence."""
        hits = _fixed_hits()
        urls = [h.url for h in hits]

        _patch_search(monkeypatch, hits)
        _patch_fetch(
            monkeypatch,
            summary_for={urls[0]: "python asyncio tutorial in depth", urls[1]: "python asyncio tutorial"},
        )
        on_topic = await search_and_answer("python asyncio tutorial", max_results=2)

        _patch_fetch(
            monkeypatch,
            summary_for={urls[0]: "kitchen recipes for winter", urls[1]: "beach holidays"},
        )
        off_topic = await search_and_answer("python asyncio guide", max_results=2)

        assert on_topic["sources"] == off_topic["sources"]  # identical hits
        assert on_topic["confidence"] != off_topic["confidence"]
        assert on_topic["confidence"] > off_topic["confidence"]
        # Coverage of the retrieved text, damped by the retrieval ratio.
        assert on_topic["confidence"] == pytest.approx(1.0)
        assert off_topic["confidence"] == pytest.approx(0.3)
        hit_score = on_topic["sources"][0]["score"]
        assert on_topic["confidence"] != hit_score
        assert off_topic["confidence"] != hit_score

    @pytest.mark.asyncio
    async def test_partial_fetch_failure_lowers_confidence_but_keeps_sources(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hits = _fixed_hits()
        _patch_search(monkeypatch, hits)
        _patch_fetch(
            monkeypatch,
            summary_for={hits[0].url: "python asyncio tutorial explained"},
            error_urls={hits[1].url},
        )

        result = await search_and_answer("python asyncio tutorial", max_results=2)

        assert result["answer"] != ""
        assert "## Sources" in result["answer"]
        assert "error_category" not in result
        # 1 of 2 pages retrieved, and it does cover the query terms:
        # 0.7 * 1.0 coverage + 0.3 * (1/2 retrieved).
        assert result["confidence"] == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_zero_hits_is_not_shaped_like_an_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_search(monkeypatch, [])
        _patch_fetch(monkeypatch)

        result = await search_and_answer("nothing matches this query", max_results=3)

        assert result["answer"] == ""
        assert result["error_category"] == "no_results"
        assert result["error"]
        assert result["sources"] == []
        assert result["confidence"] == 0.0
        # Every pre-existing key is still present.
        assert {"query", "sources", "answer", "confidence", "consensus"} <= set(result)

    @pytest.mark.asyncio
    async def test_answer_never_claims_consensus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits = _fixed_hits()
        _patch_search(monkeypatch, hits)
        _patch_fetch(
            monkeypatch,
            summary_for={
                hits[0].url: "the quick brown fox jumps over the lazy dog",
                hits[1].url: "the quick brown fox jumps over the lazy cat",
            },
        )

        result = await search_and_answer("python asyncio tutorial", max_results=2)

        answer = result["answer"].lower()
        assert result["consensus"]["common_phrases"]  # the phrases are still reported
        assert result["consensus"]["phrase_overlap_score"] > 0.0
        assert "consensus" not in answer
        assert "overlap" in answer
        assert "not corroboration" in answer
        assert "consensus_score" not in result["consensus"]

    @pytest.mark.asyncio
    async def test_provider_outage_still_raises_instead_of_returning_no_evidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            web_search_v2,
            "_search_brave",
            AsyncMock(side_effect=web_search_v2.SearchProviderError("brave")),
        )
        monkeypatch.setattr(
            web_search_v2,
            "_search_duckduckgo",
            AsyncMock(side_effect=web_search_v2.SearchProviderError("duckduckgo")),
        )

        with pytest.raises(web_search_v2.SearchProvidersUnavailable):
            await search_and_answer("provider outage honesty v2", max_results=2)


class TestSearchGithub:
    @pytest.mark.asyncio
    async def test_search_github_basic(self, mock_github_search) -> None:
        result = await search_github("fastapi", language="python", stars_min=1000)
        assert "query" in result
        assert "repositories" in result
        assert isinstance(result["repositories"], list)
        assert result["count"] >= 1

    @pytest.mark.asyncio
    async def test_search_github_no_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _empty(*args, **kwargs):
            return {
                "query": args[0] if args else "",
                "repositories": [],
                "count": 0,
                "total_count": 0,
            }

        monkeypatch.setattr("backend.tools.web_search_v2.search_github", _empty)
        result = await search_github("xyznonexistent123456", stars_min=50000)
        assert result["count"] == 0
        assert result["total_count"] == 0


class TestSearchDocs:
    @pytest.mark.asyncio
    async def test_search_docs_known_framework(self, search_mocks) -> None:
        result = await search_docs("asyncio", "python")
        assert result["framework"] == "python"
        assert "hits" in result
        assert isinstance(result["hits"], list)

    @pytest.mark.asyncio
    async def test_search_docs_unknown_framework(self, search_mocks) -> None:
        result = await search_docs("query", "unknown-framework-12345")
        assert "note" in result
