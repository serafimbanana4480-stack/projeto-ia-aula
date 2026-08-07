"""Model catalog exposed to the chat/model selectors.

``/models/available`` used to ``return`` a hardcoded constant, so an API key
never revealed the models it unlocks. It now aggregates the live catalog of
every configured provider (see ``backend/llm/model_catalog.py``) and only falls
back to the curated list below when no provider answers — for example on a
fresh install with no keys, or offline.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from backend.llm.model_catalog import aggregate_models
from backend.middleware.auth import require_auth

logger = logging.getLogger(__name__)
router = APIRouter()


# Canonical list of OpenCode Go models. These are the only models exposed
# in the chat selector so the user has a clean, non-duplicated choice.
# ``tier`` here is purely a label used by the smart router to pick the agent
# (micro, fast, coder, reasoning, deep). Each tier maps to one canonical
# OpenCode Go model.
OPENCODE_GO_MODEL_CATALOG: list[dict[str, object]] = [
    {
        "id": "minimax-m3",
        "name": "MiniMax M3 (recomendado)",
        "provider": "opencode_go",
        "pricing": "paid",
        "estimated_tokens_per_sec": 80,
    },
    {
        "id": "deepseek-v4-flash",
        "name": "DeepSeek V4 Flash (rápido)",
        "provider": "opencode_go",
        "pricing": "paid",
        "estimated_tokens_per_sec": 120,
    },
    {
        "id": "deepseek-v4-pro",
        "name": "DeepSeek V4 Pro (qualidade)",
        "provider": "opencode_go",
        "pricing": "paid",
        "estimated_tokens_per_sec": 40,
    },
    {
        "id": "glm-5.2",
        "name": "GLM 5.2 (multilingue)",
        "provider": "opencode_go",
        "pricing": "paid",
        "estimated_tokens_per_sec": 60,
    },
    {
        "id": "kimi-k2.7-code",
        "name": "Kimi K2.7 Code (programação)",
        "provider": "opencode_go",
        "pricing": "paid",
        "estimated_tokens_per_sec": 50,
    },
    {
        "id": "qwen3.7-max",
        "name": "Qwen 3.7 Max (long context)",
        "provider": "opencode_go",
        "pricing": "paid",
        "estimated_tokens_per_sec": 45,
    },
    {
        "id": "mimo-v2-pro",
        "name": "MiMo V2 Pro (balanced)",
        "provider": "opencode_go",
        "pricing": "paid",
        "estimated_tokens_per_sec": 55,
    },
]


# Tier → model mapping. The smart router picks a tier and the chat route
# uses this to resolve the actual OpenCode Go model. ``auto`` is a special
# value that lets the smart router decide.
TIER_TO_OPENCODE_MODEL: dict[str, str] = {
    "micro": "deepseek-v4-flash",
    "fast": "deepseek-v4-flash",
    "coder": "kimi-k2.7-code",
    "reasoning": "deepseek-v4-pro",
    "deep": "deepseek-v4-pro",
    "small": "deepseek-v4-flash",
    "medium": "minimax-m3",
    "large": "deepseek-v4-pro",
    "expert": "deepseek-v4-pro",
    "nano": "deepseek-v4-flash",
    "dashboard": "glm-5.2",
}


OPENROUTER_FREE_MODELS: list[dict[str, object]] = [
    {
        "id": "tencent/hy3:free",
        "name": "Tencent Hy3",
        "provider": "OpenRouter",
        "tier": "reasoning",
        "free": True,
        "color": "#fbbf24",
        "pricing": "free",
        "estimated_tokens_per_sec": 28,
        "context_window": 262_144,
        "description": "Raciocínio e agentes para tarefas complexas.",
    },
    {
        "id": "nvidia/nemotron-3-super-120b-a12b:free",
        "name": "NVIDIA Nemotron 3 Super",
        "provider": "OpenRouter",
        "tier": "deep",
        "free": True,
        "color": "#76b900",
        "pricing": "free",
        "estimated_tokens_per_sec": 22,
        "context_window": 1_000_000,
        "description": "Agentes multi-passo e contexto muito longo.",
    },
    {
        "id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "name": "NVIDIA Nemotron 3 Nano Omni",
        "provider": "OpenRouter",
        "tier": "fast",
        "free": True,
        "color": "#22d3ee",
        "pricing": "free",
        "estimated_tokens_per_sec": 42,
        "context_window": 262_144,
        "description": "Rápido, económico e orientado a reasoning/código.",
    },
    {
        "id": "poolside/laguna-m.1:free",
        "name": "Poolside Laguna M.1",
        "provider": "OpenRouter",
        "tier": "coder",
        "free": True,
        "color": "#a78bfa",
        "pricing": "free",
        "estimated_tokens_per_sec": 34,
        "context_window": 262_144,
        "description": "Especialista gratuito para programação e agentes de código.",
    },
    {
        "id": "openai/gpt-oss-20b:free",
        "name": "OpenAI gpt-oss 20B",
        "provider": "OpenRouter",
        "tier": "medium",
        "free": True,
        "color": "#10b981",
        "pricing": "free",
        "estimated_tokens_per_sec": 38,
        "context_window": 128_000,
        "description": "Generalista open-weight para chat e tarefas diárias.",
    },
    {
        "id": "google/gemma-4-31b-it:free",
        "name": "Google Gemma 4 31B",
        "provider": "OpenRouter",
        "tier": "medium",
        "free": True,
        "color": "#60a5fa",
        "pricing": "free",
        "estimated_tokens_per_sec": 45,
        "context_window": 131_072,
        "description": "Modelo generalista gratuito com contexto muito longo.",
    },
]


@router.get("/models/available")
async def list_available_models(
    refresh: bool = False, _user: dict = Depends(require_auth)
) -> list[dict[str, object]]:
    """Every model reachable with the currently configured API keys.

    Queries each provider's own list-models endpoint (cached for 10 minutes)
    and returns the union, free models first. Falls back to
    :data:`OPENROUTER_FREE_MODELS` when discovery yields nothing so a fresh
    install still has a usable selector.
    """
    try:
        catalog = await aggregate_models(refresh=refresh)
    except Exception:  # noqa: BLE001 - the selector must never hard-fail
        logger.exception("Model aggregation failed; serving curated fallback")
        return list(OPENROUTER_FREE_MODELS)

    models = catalog.get("models") or []
    if models:
        return models

    reasons = [
        f"{p.get('label', p.get('provider'))}: {p.get('error')}"
        for p in catalog.get("providers", [])
        if p.get("error")
    ]
    logger.warning(
        "No models discovered from any provider, serving curated fallback. %s",
        "; ".join(reasons) or "no providers configured",
    )
    return list(OPENROUTER_FREE_MODELS)


@router.get("/models/catalog")
async def models_catalog(
    refresh: bool = False, _user: dict = Depends(require_auth)
) -> dict[str, object]:
    """Same data as ``/models/available`` plus per-provider status and errors.

    The plain list endpoint is kept for backwards compatibility; this one lets
    the UI explain *why* a provider contributed no models.
    """
    try:
        return await aggregate_models(refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Model aggregation failed")
        return {
            "models": list(OPENROUTER_FREE_MODELS),
            "providers": [],
            "error": str(exc)[:200],
        }


@router.get("/models/tiers")
async def list_tier_mapping(_user: dict = Depends(require_auth)) -> dict[str, str]:
    """Return the tier -> OpenCode Go model mapping used by the smart router."""
    return dict(TIER_TO_OPENCODE_MODEL)
