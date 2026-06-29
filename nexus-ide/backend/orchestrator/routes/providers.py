"""GET /api/providers — LLM provider discovery and status.

Returns the list of configured providers, their models, and connection status.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends

from backend.config.settings import get_settings, load_models_config
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
