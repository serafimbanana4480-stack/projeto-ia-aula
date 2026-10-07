from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException

from backend.llm import model_catalog
from backend.observability.routes import metrics as metrics_routes
from backend.observability.routes.metrics import (
    _validate_stream_auth,
    get_models_status,
    get_request_flow,
)


@pytest.mark.asyncio
async def test_request_flow_reports_unavailable_without_mock_topology() -> None:
    data = await get_request_flow()

    assert data["available"] is False
    assert data["nodes"] == []
    assert data["links"] == []
    assert data["summary"]["total_requests"] >= 0


@pytest.mark.asyncio
async def test_models_status_raises_when_ollama_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metrics_routes, "_configured_local_model_provider", lambda: "ollama")

    async def failing_get(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx.AsyncClient, "get", failing_get)

    with pytest.raises(HTTPException) as exc:
        await get_models_status()

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_lmstudio_model_inventory_uses_configured_endpoint_and_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metrics_routes, "_configured_local_model_provider", lambda: "lmstudio")
    monkeypatch.setattr(
        model_catalog,
        "resolve_credentials",
        lambda provider: ("local-key", "http://127.0.0.1:1234/v1"),
    )
    requests: list[tuple[str, dict[str, str]]] = []

    async def successful_get(
        _client: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str] | None,
    ) -> httpx.Response:
        requests.append((url, headers))
        return httpx.Response(
            200,
            json={"data": [{"id": "qwen-local"}, {"id": "llama-local"}]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", successful_get)

    models = await get_models_status()

    assert requests == [
        (
            "http://127.0.0.1:1234/v1/models",
            {"Authorization": "Bearer local-key"},
        )
    ]
    assert models == [
        {
            "id": "qwen-local",
            "size_bytes": None,
            "modified_at": None,
            "details": {},
            "provider": "lmstudio",
            "status": "available",
        },
        {
            "id": "llama-local",
            "size_bytes": None,
            "modified_at": None,
            "details": {},
            "provider": "lmstudio",
            "status": "available",
        },
    ]


@pytest.mark.asyncio
async def test_lmstudio_unavailable_returns_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metrics_routes, "_configured_local_model_provider", lambda: "lmstudio")

    async def failing_get(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx.AsyncClient, "get", failing_get)

    with pytest.raises(HTTPException) as exc:
        await get_models_status()

    assert exc.value.status_code == 503
    assert "lmstudio" in exc.value.detail.lower()


def test_runtime_provider_override_wins_over_environment_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        model_catalog, "_runtime_overrides", lambda: {"llm_provider": "lmstudio"}
    )
    monkeypatch.setattr(
        metrics_routes,
        "get_settings",
        lambda: SimpleNamespace(llm_provider="ollama", default_provider="ollama"),
    )

    assert metrics_routes._configured_local_model_provider() == "lmstudio"


def test_dashboard_stream_requires_auth() -> None:
    class DummyRequest:
        headers: dict[str, str] = {}

    with pytest.raises(HTTPException) as exc:
        _validate_stream_auth(DummyRequest(), None)  # type: ignore[arg-type]

    assert exc.value.status_code == 401
