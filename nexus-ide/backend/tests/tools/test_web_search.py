"""Tests for backend.tools.web_search — dataclasses, fetch_url, answer honesty."""

from __future__ import annotations

import pytest

from backend.tools import web_search
from backend.tools.web_search import SearchHit, SearchResult, fetch_url, search_and_answer


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

    monkeypatch.setattr(web_search, "_search_with_fallback", _mock)


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

    async def _mock(url: str) -> dict[str, object]:
        if url in raise_urls:
            raise RuntimeError(f"network unreachable for {url}")
        if url in error_urls:
            return {
                "url": url,
                "title": "",
                "summary": "Error fetching URL: unable to retrieve content",
                "links": [],
                "status": "error",
            }
        body = summary_for.get(url, f"page body of {url}")
        return {
            "url": url,
            "title": f"Title of {url}",
            "summary": body,
            "links": [],
            "status": "success",
        }

    monkeypatch.setattr(web_search, "fetch_and_summarize", _mock)


class TestSearchAndAnswerHonesty:
    @pytest.mark.asyncio
    async def test_all_fetches_failing_emits_no_empty_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hits = _fixed_hits()
        _patch_search(monkeypatch, hits)
        _patch_fetch(monkeypatch, error_urls={h.url for h in hits})

        result = await search_and_answer("python asyncio tutorial", max_results=2)

        answer = result["answer"]
        assert answer == ""
        assert "### Source" not in answer
        assert "Confidence" not in answer
        assert "confidence" not in answer.lower()
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
            summary_for={
                urls[0]: "python asyncio tutorial in depth",
                urls[1]: "python asyncio tutorial",
            },
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
    async def test_partial_fetch_failure_lowers_confidence_but_keeps_answer(
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
        assert "### Source 1:" in result["answer"]
        assert "### Source 2:" not in result["answer"]
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
        assert {"query", "sources", "answer", "confidence"} <= set(result)

    @pytest.mark.asyncio
    async def test_answer_never_claims_consensus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hits = _fixed_hits()
        _patch_search(monkeypatch, hits)
        _patch_fetch(monkeypatch)

        result = await search_and_answer("python asyncio tutorial", max_results=2)

        answer = result["answer"].lower()
        assert "consensus" not in answer
        assert "evidence confidence" in answer
        assert "retrieved pages" in answer

    @pytest.mark.asyncio
    async def test_provider_outage_still_raises_instead_of_returning_no_evidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def brave_fails(*_args: object, **_kwargs: object) -> list[SearchHit]:
            raise web_search.SearchProviderError("brave")

        async def duckduckgo_fails(*_args: object, **_kwargs: object) -> list[SearchHit]:
            raise web_search.SearchProviderError("duckduckgo")

        monkeypatch.setattr(web_search, "_search_brave", brave_fails)
        monkeypatch.setattr(web_search, "_search_duckduckgo", duckduckgo_fails)

        with pytest.raises(web_search.SearchProvidersUnavailable):
            await search_and_answer("provider outage honesty v1", max_results=2)
