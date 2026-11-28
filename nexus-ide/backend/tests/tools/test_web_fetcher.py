"""Tests for backend.tools.web_fetcher."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tools.web_fetcher import (
    _cache_get,
    _cache_set,
    _extract_text_bs4,
    _fetch_stackexchange_question,
    _init_cache_db,
    _stackexchange_target,
    fetch_and_summarize,
)


class TestInitCacheDb:
    def test_creates_schema(self, tmp_path: pytest.TempPathFactory) -> None:
        with patch(
            "backend.tools.web_fetcher.CACHE_DB_PATH",
            tmp_path / "test_web_cache.db",
        ):
            _init_cache_db()
            db = tmp_path / "test_web_cache.db"
            assert db.exists()


class TestCacheRoundTrip:
    def test_set_and_get(self, tmp_path: pytest.TempPathFactory) -> None:
        with patch(
            "backend.tools.web_fetcher.CACHE_DB_PATH",
            tmp_path / "test_web_cache.db",
        ):
            result = {
                "url": "https://example.com",
                "title": "Example",
                "summary": "Hello world",
                "links": ["https://a.com"],
                "status": "ok",
            }
            _cache_set("https://example.com", result)
            cached = _cache_get("https://example.com")
            assert cached is not None
            assert cached["url"] == "https://example.com"
            assert cached["title"] == "Example"
            assert cached["links"] == ["https://a.com"]

    def test_expired_entry_returns_none(self, tmp_path: pytest.TempPathFactory) -> None:
        with patch(
            "backend.tools.web_fetcher.CACHE_DB_PATH",
            tmp_path / "test_web_cache.db",
        ):
            result = {
                "url": "https://old.com",
                "title": "Old",
                "summary": "",
                "links": [],
                "status": "ok",
            }
            _cache_set("https://old.com", result)
            # Manually expire
            import sqlite3
            import time

            conn = sqlite3.connect(str(tmp_path / "test_web_cache.db"))
            conn.execute(
                "UPDATE web_cache SET expires_at = ? WHERE url = ?",
                (time.time() - 1, "https://old.com"),
            )
            conn.commit()
            conn.close()

            cached = _cache_get("https://old.com")
            assert cached is None


class TestExtractTextBs4:
    def test_basic_extraction(self) -> None:
        html = """
        <html><head><title>My Title</title></head>
        <body>
            <nav>Nav content</nav>
            <main>
                <p>First paragraph.</p>
                <p>Second paragraph.</p>
                <a href="/page">Link</a>
            </main>
        </body></html>
        """
        title, text, links = _extract_text_bs4(html, "https://example.com")
        assert title == "My Title"
        assert "First paragraph." in text
        assert "Nav content" not in text
        assert "https://example.com/page" in links

    def test_no_main_uses_body(self) -> None:
        html = "<html><body><p>Body text</p></body></html>"
        title, text, links = _extract_text_bs4(html, "https://x.com")
        assert "Body text" in text
        assert links == []


class TestFetchAndSummarize:
    @pytest.mark.asyncio
    async def test_cache_hit(self, tmp_path: pytest.TempPathFactory) -> None:
        with patch(
            "backend.tools.web_fetcher.CACHE_DB_PATH",
            tmp_path / "test_web_cache.db",
        ):
            _cache_set(
                "https://cached.com",
                {
                    "url": "https://cached.com",
                    "title": "Cached",
                    "summary": "cached content",
                    "links": [],
                    "status": "ok",
                },
            )
            result = await fetch_and_summarize("https://cached.com")
            assert result["status"] == "cache_hit"
            assert result["title"] == "Cached"

    @pytest.mark.asyncio
    async def test_jina_success(
        self,
        tmp_path: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("NEXUS_ENABLE_REMOTE_WEB_READER", "true")
        with patch(
            "backend.tools.web_fetcher.CACHE_DB_PATH",
            tmp_path / "test_web_cache.db",
        ):
            mock_response = MagicMock()
            mock_response.text = "Title: Jina Title\nURL: https://jina.com\n\nHello world"

            with patch(
                "backend.tools.web_fetcher._request_with_retry",
                new_callable=AsyncMock,
                return_value=mock_response,
            ):
                result = await fetch_and_summarize("https://jina.com")
                assert result["status"] == "fetched_via_jina"
                assert result["title"] == "Jina Title"
                assert "Hello world" in result["summary"]

    @pytest.mark.asyncio
    async def test_invalid_url_is_rejected_before_cache_lookup(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cache_get = MagicMock(side_effect=AssertionError("cache must not be consulted"))
        monkeypatch.setattr("backend.tools.web_fetcher._cache_get", cache_get)

        result = await fetch_and_summarize("http://127.0.0.1/private")

        assert result["status"] == "error"
        assert result["links"] == []
        cache_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_remote_reader_is_disabled_by_default(
        self,
        tmp_path: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("NEXUS_ENABLE_REMOTE_WEB_READER", raising=False)
        with (
            patch(
                "backend.tools.web_fetcher.CACHE_DB_PATH",
                tmp_path / "test_web_cache.db",
            ),
            patch("backend.tools.web_fetcher._request_with_retry", new_callable=AsyncMock) as request,
        ):
            request.return_value.text = (
                "<html><head><title>Direct</title></head>"
                "<body><main><p>Direct content</p></main></body></html>"
            )

            result = await fetch_and_summarize("https://example.com/path")

        assert result["status"] == "fetched_direct"
        request.assert_awaited_once()
        assert "r.jina.ai" not in request.await_args.args[2]

    @pytest.mark.asyncio
    async def test_direct_fetch_fallback(self, tmp_path: pytest.TempPathFactory) -> None:
        with (
            patch(
                "backend.tools.web_fetcher.CACHE_DB_PATH",
                tmp_path / "test_web_cache.db",
            ),
            # First call (Jina) fails
            patch(
                "backend.tools.web_fetcher._request_with_retry",
                new_callable=AsyncMock,
                side_effect=Exception("jina down"),
            ),
        ):
            result = await fetch_and_summarize("https://fail.com")
            # Since both Jina and direct fail, we get error
            assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_direct_fetch_success(self, tmp_path: pytest.TempPathFactory) -> None:
        with patch(
            "backend.tools.web_fetcher.CACHE_DB_PATH",
            tmp_path / "test_web_cache.db",
        ):
            jina_response = MagicMock()
            jina_response.text = "Title: Jina\nURL: x\n\ncontent"

            direct_response = MagicMock()
            direct_response.text = (
                "<html><head><title>Direct</title></head>"
                "<body><main><p>Direct content</p></main></body></html>"
            )

            async def _mock_retry(client, method, url, **kwargs):
                if "r.jina.ai" in url:
                    raise Exception("jina blocked")
                return direct_response

            with patch(
                "backend.tools.web_fetcher._request_with_retry",
                new=_mock_retry,
            ):
                result = await fetch_and_summarize("https://direct.com")
                assert result["status"] == "fetched_direct"
                assert result["title"] == "Direct"
                assert "Direct content" in result["summary"]


class TestStackExchangeQuestionFetch:
    """Stack Overflow answers non-browser clients with 403; its API does not."""

    def test_target_parsing(self) -> None:
        assert _stackexchange_target(
            "https://stackoverflow.com/questions/64534844/python-asyncio-aiohttp-timeout"
        ) == ("stackoverflow", "64534844")
        assert _stackexchange_target(
            "https://math.stackexchange.com/questions/123/what-is-a-group"
        ) == ("math", "123")
        assert _stackexchange_target("https://askubuntu.com/questions/42/") == ("askubuntu", "42")
        assert _stackexchange_target("https://stackoverflow.com/users/1/me") is None
        assert _stackexchange_target("https://example.com/questions/1/x") is None

    @pytest.mark.asyncio
    async def test_question_body_comes_from_the_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = MagicMock()
        response.json.return_value = {
            "items": [
                {
                    "title": "python asyncio aiohttp timeout",
                    "body": (
                        "<p>Use <code>asyncio.wait_for</code> to bound the call.</p>"
                        '<p>See <a href="https://docs.python.org/3/library/asyncio-task.html">'
                        "the docs</a>.</p>"
                    ),
                    "creation_date": 1424357903,
                }
            ]
        }
        request = AsyncMock(return_value=response)
        monkeypatch.setattr("backend.tools.web_fetcher._request_with_retry", request)

        result = await _fetch_stackexchange_question(
            "https://stackoverflow.com/questions/64534844/python-asyncio-aiohttp-timeout"
        )

        assert result is not None
        assert result["status"] == "fetched_stackexchange"
        assert result["title"] == "python asyncio aiohttp timeout"
        assert "asyncio.wait_for" in result["summary"]
        assert "https://docs.python.org/3/library/asyncio-task.html" in result["links"]
        assert result["published_date"].startswith("2015-02-19")
        assert request.await_args.args[2].startswith("https://api.stackexchange.com/2.3/questions/")
        assert request.await_args.kwargs["params"]["site"] == "stackoverflow"

    @pytest.mark.asyncio
    async def test_api_failure_returns_none_so_html_fetch_runs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "backend.tools.web_fetcher._request_with_retry",
            AsyncMock(side_effect=Exception("api down")),
        )
        assert (
            await _fetch_stackexchange_question(
                "https://stackoverflow.com/questions/1/example"
            )
            is None
        )

    @pytest.mark.asyncio
    async def test_fetch_and_summarize_prefers_the_api_for_stackoverflow(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = MagicMock()
        response.json.return_value = {
            "items": [{"title": "Question", "body": "<p>Answer text</p>", "creation_date": 0}]
        }
        request = AsyncMock(return_value=response)
        with (
            patch("backend.tools.web_fetcher.CACHE_DB_PATH", tmp_path / "test_web_cache.db"),
            patch("backend.tools.web_fetcher._request_with_retry", request),
        ):
            result = await fetch_and_summarize(
                "https://stackoverflow.com/questions/64534844/python-asyncio-aiohttp-timeout"
            )

        assert result["status"] == "fetched_stackexchange"
        assert "Answer text" in result["summary"]
        assert request.await_count == 1
