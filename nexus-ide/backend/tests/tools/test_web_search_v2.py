"""Tests for backend.tools.web_search_v2.

Integration tests mock all outbound HTTP calls so the suite remains fast and
does not depend on network connectivity or third-party API keys.
"""

from __future__ import annotations

import pytest

from backend.tools.web_search_v2 import (
    SearchHit,
    SearchResult,
    FetchedContent,
    _domain_score,
    _relevance_score,
    _rank_hits,
    _parse_age_hint,
    _extract_site_filter,
    _apply_recency_filter,
    _cross_reference_facts,
    search_web,
    fetch_and_summarize,
    search_and_answer,
    search_github,
    search_docs,
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
        assert result["consensus_score"] == 0.0

    def test_single_source(self) -> None:
        result = _cross_reference_facts([{"title": "A", "summary": "foo bar baz qux"}])
        assert result["consensus_score"] == 0.5

    def test_common_phrases(self) -> None:
        summaries = [
            {"title": "A", "summary": "the quick brown fox jumps"},
            {"title": "B", "summary": "the quick brown fox runs"},
        ]
        result = _cross_reference_facts(summaries)
        assert result["consensus_score"] > 0.0
        assert len(result["common_phrases"]) > 0


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
    async def test_fetch_and_summarize_invalid_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force both fetch strategies to fail
        async def _fail(*args, **kwargs):
            return None

        monkeypatch.setattr("backend.tools.web_search_v2._fetch_via_jina", _fail)
        monkeypatch.setattr("backend.tools.web_search_v2._fetch_via_httpx", _fail)

        result = await fetch_and_summarize("https://this-domain-does-not-exist-12345.invalid", max_length=200)
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
            return {"query": args[0] if args else "", "repositories": [], "count": 0, "total_count": 0}

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
