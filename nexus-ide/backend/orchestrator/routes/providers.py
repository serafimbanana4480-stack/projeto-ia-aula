"""LLM provider discovery, live model catalogs and API-key validation.

- ``GET  /api/providers``                    configured providers + health
- ``GET  /api/providers/runtime``            runtime policy/eligibility summary
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
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.config.settings import get_settings, load_models_config
from backend.llm.factory import create_llm_client
from backend.llm.model_catalog import (
    PROVIDER_SPECS,
    aggregate_models,
    apply_catalog_to_llm_client,
    discover_models,
    invalidate_cache,
    list_provider_specs,
    load_validated_models,
    validate_api_key,
)
from backend.llm.multi_llm_manager import MultiLLMManager
from backend.middleware.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter()


async def _check_provider_health(
    base_url: str, provider: str, api_key: str | None = None
) -> dict[str, Any]:
    """Check a provider and report what was actually observed.

    The previous implementation issued a bare ``GET {base_url}`` and reported
    ``reachable`` for *any* HTTP status. A provider with an invalid key
    answers 401, a dead endpoint answers 404, and both were presented to the
    user as a working connection — so the model selector happily listed
    models that could not answer a single prompt.

    The check now measures the thing that actually decides whether the
    provider can serve a chat turn:
      * local providers ask for their real model list;
      * OpenAI-compatible providers call ``{base_url}/models`` with the
        configured key and map the status code to a specific reason.

    The result is a typed status the UI can explain instead of a bare
    "reachable".
    """
    try:
        if provider == "ollama":
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{base_url}/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    return {
                        "status": "healthy",
                        "models_available": len(models),
                        "detail": "Servidor local a responder",
                    }
                return {
                    "status": "unhealthy",
                    "error": f"HTTP {resp.status_code}",
                    "detail": "O servidor local respondeu, mas sem uma lista de modelos.",
                }
        if provider in {"lmstudio", "local"}:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{base_url.rstrip('/')}/models")
                if resp.status_code == 200:
                    try:
                        models = resp.json().get("data", [])
                    except Exception:  # pragma: no cover - malformed body
                        models = []
                    return {
                        "status": "healthy",
                        "models_available": len(models),
                        "detail": "Servidor local a responder",
                    }
                return {
                    "status": "unhealthy",
                    "error": f"HTTP {resp.status_code}",
                    "detail": "O servidor local não devolveu a lista de modelos.",
                }

        # Cloud / OpenAI-compatible providers: ask for the catalog with the
        # key that would actually be used.
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)
        if resp.status_code == 200:
            try:
                models = resp.json().get("data", [])
            except Exception:  # pragma: no cover - malformed body
                models = []
            return {
                "status": "healthy",
                "models_available": len(models),
                "detail": "Credenciais aceites",
            }
        if resp.status_code in (401, 403):
            return {
                "status": "unauthenticated",
                "error": f"HTTP {resp.status_code}",
                "detail": "A chave da API foi recusada. Configura-a em Definições.",
            }
        if resp.status_code == 402:
            return {
                "status": "no_credit",
                "error": f"HTTP {resp.status_code}",
                "detail": "A conta não tem crédito disponível.",
            }
        if resp.status_code == 429:
            return {
                "status": "rate_limited",
                "error": f"HTTP {resp.status_code}",
                "detail": "O fornecedor limitou o ritmo de pedidos. Tenta mais tarde.",
            }
        return {
            "status": "unhealthy",
            "error": f"HTTP {resp.status_code}",
            "detail": "O fornecedor respondeu com um erro inesperado.",
        }
    except Exception as exc:
        return {"status": "unreachable", "error": str(exc)}


@router.get("/providers")
async def list_providers(_user: dict = Depends(require_auth)) -> dict:
    """Return configured LLM providers, their models, and health status."""
    settings = get_settings()
    cfg = load_models_config()
    providers_cfg = cfg.get("providers", {})

    active_provider = settings.llm_provider.lower()

    # Use the same provider-specific endpoints and live credentials as discovery.
    async def catalog_health(provider: str) -> dict[str, Any]:
        result = await validate_api_key(provider)
        if result.get("valid"):
            return {"status": "healthy", "models_available": result.get("models_count", 0),
                    "detail": "Catálogo consultado; disponibilidade no chat ainda não testada."}
        return {"status": "unhealthy", "error": result.get("error"), "detail": result.get("error")}

    health_tasks = []
    for key, pcfg in providers_cfg.items():
        requires_key = bool(pcfg.get("requires_api_key", False))
        key_attr = f"{key}_api_key"
        api_key = getattr(settings, key_attr, "") if requires_key else None
        health_tasks.append(
            catalog_health(key) if key in PROVIDER_SPECS
            else _check_provider_health(pcfg.get("base_url", ""), key, api_key)
        )

    health_results = await asyncio.gather(*health_tasks, return_exceptions=True)

    result: list[dict] = []
    for (key, pcfg), health in zip(providers_cfg.items(), health_results, strict=False):
        requires_key = pcfg.get("requires_api_key", False)
        api_key_set = False
        if requires_key:
            key_attr = f"{key}_api_key"
            api_key_set = bool(getattr(settings, key_attr, ""))
            if key in PROVIDER_SPECS:
                from backend.llm.model_catalog import resolve_credentials
                api_key_set = bool(resolve_credentials(key)[0])

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


@router.get("/providers/runtime")
async def providers_status(_user: dict = Depends(require_auth)) -> dict[str, Any]:
    """Runtime LLM availability and typed provider eligibility state.

    ``/providers/status`` belongs to the live metrics widget.  Keeping this
    policy/catalog view on a distinct path avoids an order-dependent FastAPI
    route collision where one of the two responses was unreachable.
    """
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
    provider_entries = prov.get("providers", [])
    llm_available = (
        not is_demo
        and blocked is None
        and _has_usable_provider(provider_entries, runtime)
    )
    return {
        "providers": provider_entries,
        "active_provider": prov.get("active_provider", ""),
        "runtime": runtime,
        "blocked": blocked,
        "llm_available": llm_available,
        "demo_mode": is_demo,
    }


def _has_usable_provider(
    providers: list[dict[str, Any]], runtime: dict[str, Any]
) -> bool:
    """Only report LLM readiness when a provider has a usable model now.

    A constructed client is not evidence of a working provider. Require a
    healthy provider response with at least one model, and honor runtime
    simulation, circuit-breaker, and free-only eligibility state.
    """
    local_providers = {"local", "lmstudio", "ollama"}
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        provider_id = str(provider.get("id") or "").strip().lower()
        health = provider.get("health")
        if not provider_id or not isinstance(health, dict):
            continue
        if str(health.get("status") or "").strip().lower() != "healthy":
            continue
        try:
            model_count = int(health.get("models_available") or 0)
        except (TypeError, ValueError):
            continue
        if model_count < 1:
            continue
        if provider.get("requires_api_key") and not provider.get("api_key_set"):
            continue

        state = runtime.get(provider_id, {})
        if not isinstance(state, dict) or state.get("simulation") is True:
            continue
        if state.get("healthy") is False:
            continue
        if state.get("healthy") is True or state.get("free_only") is not True:
            return True
        if provider_id in local_providers:
            return True

        validated_at = state.get("validated_at") or state.get("validation_timestamp")
        if state.get("quota_available") is True and validated_at is not None:
            return True
    return False


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
    request: Request,
    refresh: bool = False,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Union of every configured provider's catalog, plus per-provider status."""
    result = await aggregate_models(refresh=refresh)
    client = getattr(request.app.state, "llm_client", None)
    if client is not None:
        for entry in result.get("providers", []):
            if isinstance(entry, dict) and not entry.get("error"):
                provider = str(entry.get("provider") or "")
                models = load_validated_models(provider)
                if models:
                    apply_catalog_to_llm_client(client, provider, models)
    return result


@router.get("/providers/{provider_id}/models")
async def provider_models(
    provider_id: str,
    request: Request,
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
    client = getattr(request.app.state, "llm_client", None)
    # A successful discovery already validated these entries. Publish them to
    # the live adapter; stale/error fallback entries must never authorise it.
    if client is not None and result.models and not result.error:
        apply_catalog_to_llm_client(client, normalized, result.models)
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
