"""Tests for backend.tools.web_search — dataclasses and fetch_url."""

from __future__ import annotations

from backend.tools.web_search import SearchHit, SearchResult, fetch_url


class TestSearchHit:
    def test_defaults(self) -> None:
        hit = SearchHit(url="https://example.com", title="Example", snippet="A site")
        assert hit.score == 0.0

    def test_with_score(self) -> None:
        hit = SearchHit(
            url="https://example.com",
            title="Example",
            snippet="A site",
            score=0.95,
        )
        assert hit.score == 0.95


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
        assert result.search_iterations == 3


class TestFetchUrl:
    def test_function_exists(self) -> None:
        assert callable(fetch_url)
