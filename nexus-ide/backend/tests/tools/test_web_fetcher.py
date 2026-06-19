"""Tests for backend.tools.web_fetcher."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tools.web_fetcher import (
    _cache_get,
    _cache_set,
    _extract_text_bs4,
    _init_cache_db,
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
    async def test_jina_success(self, tmp_path: pytest.TempPathFactory) -> None:
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
    async def test_direct_fetch_fallback(self, tmp_path: pytest.TempPathFactory) -> None:
        with patch(
            "backend.tools.web_fetcher.CACHE_DB_PATH",
            tmp_path / "test_web_cache.db",
        ):
            # First call (Jina) fails
            with patch(
                "backend.tools.web_fetcher._request_with_retry",
                new_callable=AsyncMock,
                side_effect=Exception("jina down"),
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
