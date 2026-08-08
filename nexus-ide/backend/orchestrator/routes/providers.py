"""LLM provider discovery, live model catalogs and API-key validation.

- ``GET  /api/providers``                    configured providers + health
- ``GET  /api/providers/catalog``            provider metadata for Settings
- ``GET  /api/providers/{id}/models``        live model list (cached, TTL 10m)
- ``POST /api/providers/{id}/validate-key``  test a key before saving it
- ``POST /api/providers/refresh``            drop the catalog cache
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.config.settings import get_settings, load_models_config
from backend.llm.factory import create_llm_client
from backend.llm.model_catalog import (
    PROVIDER_SPECS,
    aggregate_models,
    discover_models,
    invalidate_cache,
    list_provider_specs,
    validate_api_key,
)
from backend.llm.multi_llm_manager import MultiLLMManager
from backend.middleware.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter()


async def _check_provider_health(base_url: str, provider: str) -> dict:
    """Quick health check for a provider."""
    try:
        if provider == "ollama":
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{base_url}/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    return {"status": "healthy", "models_available": len(models)}
                return {"status": "unhealthy", "error": f"HTTP {resp.status_code}"}
        else:
            # Cloud providers — just check if the URL is reachable
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(base_url)
                return {"status": "reachable", "http_status": resp.status_code}
    except Exception as exc:
        return {"status": "unreachable", "error": str(exc)}


@router.get("/providers")
async def list_providers(_user: dict = Depends(require_auth)) -> dict:
    """Return configured LLM providers, their models, and health status."""
    settings = get_settings()
    cfg = load_models_config()
    providers_cfg = cfg.get("providers", {})

    active_provider = settings.llm_provider.lower()

    # Check health in parallel
    health_tasks = []
    for key, pcfg in providers_cfg.items():
        health_tasks.append(_check_provider_health(pcfg.get("base_url", ""), key))

    health_results = await asyncio.gather(*health_tasks, return_exceptions=True)

    result: list[dict] = []
    for (key, pcfg), health in zip(providers_cfg.items(), health_results, strict=False):
        requires_key = pcfg.get("requires_api_key", False)
        api_key_set = False
        if requires_key:
            key_attr = f"{key}_api_key"
            api_key_set = bool(getattr(settings, key_attr, ""))

        health_data = (
            health if isinstance(health, dict) else {"status": "error", "error": str(health)}
        )

        result.append(
            {
                "id": key,
                "name": pcfg.get("name", key),
                "base_url": pcfg.get("base_url", ""),
                "default_models": pcfg.get("default_models", []),
                "requires_api_key": requires_key,
                "api_key_set": api_key_set,
                "active": key == active_provider,
                "health": health_data,
            }
        )

    return {
        "providers": result,
        "active_provider": active_provider,
    }


@router.get("/providers/status")
async def providers_status(_user: dict = Depends(require_auth)) -> dict[str, Any]:
    """Runtime LLM availability and typed provider eligibility state."""
    is_demo = True
    client = None
    runtime: dict[str, Any] = {}
    blocked: dict[str, Any] | None = None
    try:
        client = create_llm_client()
        if isinstance(client, MultiLLMManager):
            is_demo = len(getattr(client, "providers", {}) or {}) == 0
            runtime = client.provider_status()
        else:
            is_demo = bool(getattr(client, "simulation", False))
            runtime = {
                getattr(client, "provider_name", client.__class__.__name__.lower()): {
                    "simulation": bool(getattr(client, "simulation", False)),
                    "free_only": bool(getattr(client, "free_only", False)),
                    "eligibility_reason": getattr(client, "eligibility_reason", ""),
                    "quota_available": getattr(client, "quota_available", None),
                    "validated_at": getattr(client, "validated_at", None),
                }
            }
    except Exception as exc:
        is_demo = True
        blocked = {
            "category": getattr(exc, "category", "provider_unavailable"),
            "error": str(exc),
            "provider": getattr(exc, "provider", None),
            "model": getattr(exc, "model", None),
            "retry_after": getattr(exc, "retry_after", None),
        }
    finally:
        close = getattr(client, "aclose", None)
        if callable(close):
            await close()
    try:
        prov = await list_providers(_user)
    except Exception:
        prov = {"providers": [], "active_provider": ""}
    return {
        "providers": prov.get("providers", []),
        "active_provider": prov.get("active_provider", ""),
        "runtime": runtime,
        "blocked": blocked,
        "llm_available": not is_demo and blocked is None,
        "demo_mode": is_demo,
    }


# ─────────────────── live model discovery ───────────────────
#
# Before these routes existed the UI model list was a hardcoded constant, so
# adding an API key never surfaced the models it unlocks. Each provider is now
# asked for its real catalog (see backend/llm/model_catalog.py).


class ValidateKeyRequest(BaseModel):
    """Body for ``POST /providers/{id}/validate-key``.

    ``api_key`` is optional: omit it to test the key already persisted in
    ``data/settings.json``/``.env`` without sending the secret again.
    """

    api_key: str | None = Field(default=None, max_length=512)


def _require_known_provider(provider_id: str) -> str:
    normalized = provider_id.strip().lower()
    if normalized not in PROVIDER_SPECS:
        raise HTTPException(
            status_code=404,
            detail=f"Provider desconhecido '{provider_id}'. Disponíveis: {', '.join(sorted(PROVIDER_SPECS))}",
        )
    return normalized


@router.get("/providers/catalog")
async def providers_catalog(_user: dict = Depends(require_auth)) -> dict[str, Any]:
    """Provider metadata for the Settings UI (label, docs URL, key present)."""
    return {"providers": list_provider_specs()}


@router.get("/providers/models")
async def all_provider_models(
    refresh: bool = False,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Union of every configured provider's catalog, plus per-provider status."""
    return await aggregate_models(refresh=refresh)


@router.get("/providers/{provider_id}/models")
async def provider_models(
    provider_id: str,
    refresh: bool = False,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Live model list for one provider.

    Served from a 10-minute on-disk cache unless ``refresh=true``. A failed
    lookup returns 200 with ``error`` set (and stale models when available) so
    the selector degrades instead of breaking.
    """
    normalized = _require_known_provider(provider_id)
    result = await discover_models(normalized, refresh=refresh)
    return result.to_dict()


@router.post("/providers/{provider_id}/validate-key")
async def validate_provider_key(
    provider_id: str,
    payload: ValidateKeyRequest | None = None,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Test an API key by listing models with it. Nothing is persisted.

    Lets the Settings UI show a real ✓/✗ before the user saves, instead of
    silently storing an invalid key and failing at the first chat message.
    """
    normalized = _require_known_provider(provider_id)
    api_key = payload.api_key if payload else None
    result = await validate_api_key(normalized, api_key)
    return {"provider": normalized, **result}


@router.post("/providers/refresh")
async def refresh_provider_catalog(
    provider: str | None = None,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Invalidate the cached catalog — call this after an API key changes."""
    normalized = _require_known_provider(provider) if provider else None
    invalidate_cache(normalized)
    return {"invalidated": normalized or "all"}
