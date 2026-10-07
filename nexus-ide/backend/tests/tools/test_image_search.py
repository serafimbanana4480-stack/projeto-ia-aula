"""Tests for image search mapping, safe fallbacks and provider request shape."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.tools import web_search


def test_normalize_brave_image_results_keeps_safe_display_fields() -> None:
    payload = {
        "results": [
            {
                "title": "Example photo",
                "url": "https://example.org/photo-page",
                "source": "example.org",
                "thumbnail": {
                    "src": "https://imgs.search.brave.com/thumb-1",
                    "width": 640,
                    "height": 480,
                },
                "properties": {"url": "https://example.org/photo.jpg"},
            },
            {
                "title": "Unsafe image",
                "url": "https://example.org/unsafe",
                "thumbnail": {"src": "javascript:alert(1)"},
            },
            {
                "title": "Untrusted preview host",
                "url": "https://example.org/untrusted",
                "thumbnail": {"src": "https://evil.example/preview.jpg"},
            },
            {
                "title": "Lookalike Brave host",
                "url": "https://example.org/lookalike",
                "thumbnail": {"src": "https://imgs.search.brave.com.evil.example/preview.jpg"},
            },
            {
                "title": "Non-standard preview port",
                "url": "https://example.org/port",
                "thumbnail": {"src": "https://imgs.search.brave.com:444/preview.jpg"},
            },
            {
                "title": "Credential-bearing preview URL",
                "url": "https://example.org/credentials",
                "thumbnail": {"src": "https://user:pass@imgs.search.brave.com/preview.jpg"},
            },
            {
                "title": "Unsafe source page",
                "url": "javascript:alert(1)",
                "thumbnail": {"src": "https://imgs.search.brave.com/unsafe-page.jpg"},
            },
            {
                "title": "Missing source page",
                "thumbnail": {"src": "https://imgs.search.brave.com/thumb-2"},
            },
        ]
    }

    hits = web_search.normalize_brave_image_results(payload, limit=10)

    assert hits == [
        {
            "title": "Example photo",
            "url": "https://example.org/photo-page",
            "thumbnail_url": "https://imgs.search.brave.com/thumb-1",
            "source": "example.org",
            "width": 640,
            "height": 480,
        }
    ]
    # ``url`` is the origin page; ``properties.url`` remains the original
    # image URL and is deliberately not substituted for the source link.
    assert hits[0]["url"] == "https://example.org/photo-page"


def test_image_search_returns_clear_unconfigured_state_without_network(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(web_search, "get_brave_api_key", lambda: "")

    result = asyncio.run(web_search.search_images("motorcycle"))

    assert result["configured"] is False
    assert result["hits"] == []
    assert "configurar a chave Brave" in result["error"]
    assert result["error_code"] == "not_configured"


def test_image_search_uses_safe_search_and_does_not_cache_results(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(web_search, "get_brave_api_key", lambda: "test-only-key")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, Any]:
            return {
                "results": [
                    {
                        "title": "Helmet",
                        "url": "https://example.org/helmet",
                            "thumbnail": {"src": "https://imgs.search.brave.com/helmet"},
                    }
                ]
            }

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured["client_options"] = kwargs

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, url: str, *, headers: dict[str, str], params: dict[str, Any]) -> FakeResponse:
            captured.update(url=url, headers=headers, params=params)
            return FakeResponse()

    monkeypatch.setattr(web_search.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(web_search.search_images("motorcycle helmet", max_results=120))

    assert captured["url"] == "https://api.search.brave.com/res/v1/images/search"
    assert captured["params"]["count"] == 50
    assert captured["params"]["safesearch"] == "strict"
    assert captured["headers"]["Cache-Control"] == "no-cache"
    assert result["hits"][0]["title"] == "Helmet"


def test_runtime_brave_key_overrides_environment_without_exposing_it(monkeypatch: Any) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(web_search, "get_settings", lambda: SimpleNamespace(brave_api_key="environment-key"))
    monkeypatch.setattr(
        "backend.orchestrator.routes.settings._load_runtime_settings",
        lambda: {"brave_api_key": "runtime-key"},
    )

    assert web_search.get_brave_api_key() == "runtime-key"


def test_image_search_classifies_invalid_brave_credentials_without_echoing_them(
    monkeypatch: Any,
) -> None:
    import httpx

    secret_stub = "local-test-secret-never-print"
    monkeypatch.setattr(web_search, "get_brave_api_key", lambda: secret_stub)

    class FakeClient:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, *_args: Any, **_kwargs: Any) -> Any:
            request = httpx.Request("GET", "https://api.search.brave.com/res/v1/images/search")
            response = httpx.Response(401, request=request)
            raise httpx.HTTPStatusError("unauthorized", request=request, response=response)

    monkeypatch.setattr(web_search.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(web_search.search_images("motorcycle"))

    assert result["configured"] is True
    assert result["error_code"] == "invalid_credentials"
    assert result["hits"] == []
    assert secret_stub not in repr(result)


def test_image_search_does_not_forward_brave_token_on_provider_redirect(
    monkeypatch: Any,
) -> None:
    import httpx

    secret_stub = "local-test-secret-never-forward"
    seen_requests: list[httpx.Request] = []
    client_options: dict[str, Any] = {}
    monkeypatch.setattr(web_search, "get_brave_api_key", lambda: secret_stub)

    def redirect_to_untrusted_host(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(
            302,
            headers={"Location": "https://attacker.example/collect"},
            request=request,
        )

    real_async_client = httpx.AsyncClient

    def local_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        client_options.update(kwargs)
        kwargs["transport"] = httpx.MockTransport(redirect_to_untrusted_host)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(web_search.httpx, "AsyncClient", local_async_client)
    result = asyncio.run(web_search.search_images("motorcycle"))

    assert result["error_code"] == "provider_error"
    assert client_options["follow_redirects"] is False
    assert len(seen_requests) == 1
    assert seen_requests[0].url.host == "api.search.brave.com"
    assert seen_requests[0].headers["x-subscription-token"] == secret_stub
    assert secret_stub not in repr(result)


def test_image_search_rejects_same_origin_provider_redirect(
    monkeypatch: Any,
) -> None:
    import httpx

    seen_requests: list[httpx.Request] = []
    client_options: dict[str, Any] = {}
    monkeypatch.setattr(web_search, "get_brave_api_key", lambda: "local-test-key")

    def redirect_within_brave(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(
            302,
            headers={"Location": "/res/v1/images/search/"},
            request=request,
        )

    real_async_client = httpx.AsyncClient

    def local_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        client_options.update(kwargs)
        kwargs["transport"] = httpx.MockTransport(redirect_within_brave)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(web_search.httpx, "AsyncClient", local_async_client)
    result = asyncio.run(web_search.search_images("motorcycle"))

    assert result["error_code"] == "provider_error"
    assert client_options["follow_redirects"] is False
    assert len(seen_requests) == 1
    assert seen_requests[0].url.host == "api.search.brave.com"
