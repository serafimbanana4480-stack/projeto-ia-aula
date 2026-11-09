from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.orchestrator.routes import providers as provider_routes


class RuntimeClient:
    provider_name = "lmstudio"
    simulation = False
    free_only = True
    quota_available = None
    eligibility_reason = ""


@pytest.mark.asyncio
async def test_runtime_readiness_is_false_when_configured_providers_are_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider_routes, "create_llm_client", RuntimeClient)

    async def list_providers(_: dict[str, Any]) -> dict[str, Any]:
        return {
            "active_provider": "lmstudio",
            "providers": [
                {
                    "id": "lmstudio",
                    "active": True,
                    "requires_api_key": False,
                    "health": {"status": "unreachable", "models_available": 0},
                }
            ],
        }

    monkeypatch.setattr(provider_routes, "list_providers", list_providers)

    result = await provider_routes.providers_status({"user_id": "test"})

    assert result["demo_mode"] is False
    assert result["llm_available"] is False


@pytest.mark.asyncio
async def test_runtime_readiness_accepts_a_healthy_local_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider_routes, "create_llm_client", RuntimeClient)

    async def list_providers(_: dict[str, Any]) -> dict[str, Any]:
        return {
            "active_provider": "lmstudio",
            "providers": [
                {
                    "id": "lmstudio",
                    "active": True,
                    "requires_api_key": False,
                    "health": {"status": "healthy", "models_available": 1},
                }
            ],
        }

    monkeypatch.setattr(provider_routes, "list_providers", list_providers)

    result = await provider_routes.providers_status({"user_id": "test"})

    assert result["llm_available"] is True


@pytest.mark.asyncio
async def test_runtime_readiness_rejects_unvalidated_cloud_model_in_free_only_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        provider_routes,
        "create_llm_client",
        lambda: SimpleNamespace(
            provider_name="opencode_go",
            simulation=False,
            free_only=True,
            quota_available=None,
            eligibility_reason="",
        ),
    )

    async def list_providers(_: dict[str, Any]) -> dict[str, Any]:
        return {
            "active_provider": "opencode_go",
            "providers": [
                {
                    "id": "opencode_go",
                    "active": True,
                    "requires_api_key": True,
                    "api_key_set": True,
                    "health": {"status": "healthy", "models_available": 2},
                }
            ],
        }

    monkeypatch.setattr(provider_routes, "list_providers", list_providers)

    result = await provider_routes.providers_status({"user_id": "test"})

    assert result["llm_available"] is False

