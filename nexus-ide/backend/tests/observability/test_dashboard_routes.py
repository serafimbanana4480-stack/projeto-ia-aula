from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException

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
    async def failing_get(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx.AsyncClient, "get", failing_get)

    with pytest.raises(HTTPException) as exc:
        await get_models_status()

    assert exc.value.status_code == 503


def test_dashboard_stream_requires_auth() -> None:
    class DummyRequest:
        headers: dict[str, str] = {}

    with pytest.raises(HTTPException) as exc:
        _validate_stream_auth(DummyRequest(), None)  # type: ignore[arg-type]

    assert exc.value.status_code == 401
