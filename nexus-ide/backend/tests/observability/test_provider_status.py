"""Provider status must reflect a directly configured LLM client."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.observability.routes.metrics import get_providers_status


class OpenRouterProvider:
    pass


@pytest.mark.asyncio
async def test_direct_provider_is_reported_as_available() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(llm_client=OpenRouterProvider()))
    )

    result = await get_providers_status(request, _user={"id": "test"})

    assert result["providers"]["openrouter"]["healthy"] is True
    assert "Unsupported LLM client" not in result.get("note", "")
