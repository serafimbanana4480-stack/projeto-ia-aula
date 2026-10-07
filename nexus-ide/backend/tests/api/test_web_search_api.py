"""Authenticated Web and image search route contracts; provider traffic is mocked locally."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.middleware import auth as auth_module
from backend.orchestrator.routes import system as system_routes
from backend.tools import web_search as web_search_tools


async def _fake_user() -> dict[str, str]:
    return {"user_id": "search-test", "email": "search@test.local"}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(system_routes.router, prefix="/api")
    app.dependency_overrides[auth_module.require_auth] = _fake_user
    return TestClient(app)


def test_image_search_route_trims_query_bounds_limit_and_never_caches(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_search(query: str, max_results: int) -> dict[str, Any]:
        captured.update(query=query, max_results=max_results)
        return {"query": query, "hits": [], "count": 0, "configured": True}

    monkeypatch.setattr(system_routes, "search_images", fake_search)
    response = client.post("/api/web_search/images", json={"query": "  helmet  ", "limit": 500})

    assert response.status_code == 200
    assert captured == {"query": "helmet", "max_results": 50}
    assert response.headers["cache-control"] == "no-store"


def test_image_search_route_runs_adapter_against_local_provider_and_filters_bad_urls(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise route -> real adapter -> deterministic in-process HTTP provider."""
    provider_requests: list[httpx.Request] = []
    provider_payload = {
        "results": [
            {
                "title": "Imagem válida",
                "url": "https://example.org/fonte",
                "source": "example.org",
                "thumbnail": {
                    "src": "https://imgs.search.brave.com/preview-1",
                    "width": 640,
                    "height": 480,
                },
                "properties": {"url": "https://example.org/original.jpg"},
            },
            {
                "title": "Host de miniatura falso",
                "url": "https://example.org/fonte-2",
                "thumbnail": {"src": "https://imgs.search.brave.com.evil.test/preview.jpg"},
            },
            {
                "title": "Protocolo de miniatura inválido",
                "url": "https://example.org/fonte-3",
                "thumbnail": {"src": "http://imgs.search.brave.com/preview.jpg"},
            },
            {
                "title": "Porta de miniatura inválida",
                "url": "https://example.org/fonte-4",
                "thumbnail": {"src": "https://imgs.search.brave.com:444/preview.jpg"},
            },
            {
                "title": "URL de origem com protocolo inválido",
                "url": "javascript:alert(1)",
                "thumbnail": {"src": "https://imgs.search.brave.com/preview-5"},
            },
            {
                "title": "URL de origem malformado",
                "url": "https://example.org:99999/source",
                "thumbnail": {"src": "https://imgs.search.brave.com/preview-6"},
            },
            None,
        ]
    }

    def local_provider(request: httpx.Request) -> httpx.Response:
        provider_requests.append(request)
        return httpx.Response(200, json=provider_payload)

    real_async_client = httpx.AsyncClient

    def local_only_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        # web_search pins its own SSRF transport on every client it builds, so
        # the mock must replace it rather than be passed alongside it --
        # `httpx.AsyncClient()` rejects a duplicate `transport` keyword.
        kwargs["transport"] = httpx.MockTransport(local_provider)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(system_routes, "_web_search_enabled", lambda: True)
    monkeypatch.setattr(web_search_tools, "get_brave_api_key", lambda: "deterministic-test-key")
    monkeypatch.setattr(web_search_tools.httpx, "AsyncClient", local_only_async_client)

    response = client.post("/api/web_search/images", json={"query": "  bicicleta  ", "limit": 100})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert len(provider_requests) == 1
    request = provider_requests[0]
    assert request.url.host == "api.search.brave.com"
    assert request.url.path == "/res/v1/images/search"
    assert request.url.params["q"] == "bicicleta"
    assert request.url.params["count"] == "50"
    assert request.headers["x-subscription-token"] == "deterministic-test-key"

    body = response.json()
    assert body["configured"] is True
    assert body["provider"] == "brave"
    assert body["count"] == 1
    assert body["hits"] == [
        {
            "title": "Imagem válida",
            "url": "https://example.org/fonte",
            "thumbnail_url": "https://imgs.search.brave.com/preview-1",
            "source": "example.org",
            "width": 640,
            "height": 480,
        }
    ]


def test_image_search_route_rejects_empty_and_non_string_queries(client: TestClient) -> None:
    assert client.post("/api/web_search/images", json={"query": "  "}).status_code == 422
    assert client.post("/api/web_search/images", json={"query": 123}).status_code == 422


def test_image_search_route_requires_authentication() -> None:
    app = FastAPI()
    app.include_router(system_routes.router, prefix="/api")

    with TestClient(app) as unauthenticated:
        response = unauthenticated.post("/api/web_search/images", json={"query": "helmet"})

    assert response.status_code == 401


def test_web_and_image_search_honor_environment_feature_flag(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def fake_web(_query: str, max_results: int) -> dict[str, Any]:
        calls.append(f"web:{max_results}")
        return {"query": _query, "hits": [], "count": 0}

    async def fake_images(_query: str, max_results: int) -> dict[str, Any]:
        calls.append(f"images:{max_results}")
        return {"query": _query, "hits": [], "count": 0, "configured": True}

    monkeypatch.setattr(system_routes, "_web_search_enabled", lambda: False)
    monkeypatch.setattr(system_routes, "search_web", fake_web)
    monkeypatch.setattr(system_routes, "search_images", fake_images)

    web_response = client.post("/api/web_search", json={"query": "helmet"})
    image_response = client.post("/api/web_search/images", json={"query": "helmet"})

    assert web_response.status_code == image_response.status_code == 503
    assert web_response.json()["detail"]["code"] == "web_search_disabled"
    assert image_response.json()["detail"]["code"] == "web_search_disabled"
    assert calls == []


def test_web_search_route_bounds_bad_limits_and_trims_query(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_search(query: str, max_results: int) -> dict[str, Any]:
        captured.update(query=query, max_results=max_results)
        return {"query": query, "hits": [], "count": 0}

    monkeypatch.setattr(system_routes, "search_web", fake_search)
    response = client.post("/api/web_search", json={"query": "  docs  ", "limit": "bad"})

    assert response.status_code == 200
    assert captured == {"query": "docs", "max_results": 10}


def test_web_search_route_reports_provider_failure_as_gateway_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable(_query: str, max_results: int) -> dict[str, Any]:
        raise web_search_tools.SearchProvidersUnavailable(["brave", "duckduckgo"])

    monkeypatch.setattr(system_routes, "search_web", unavailable)
    response = client.post("/api/web_search", json={"query": "docs"})

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "providers_unavailable"


def test_web_search_route_does_not_return_unexpected_exception_details(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(_query: str, max_results: int) -> dict[str, Any]:
        raise RuntimeError("private provider endpoint and token leaked")

    monkeypatch.setattr(system_routes, "search_web", broken)
    response = client.post("/api/web_search", json={"query": "docs"})

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "search_internal_error",
        "message": "A pesquisa falhou por um erro interno.",
    }
    assert "private provider endpoint" not in response.text
