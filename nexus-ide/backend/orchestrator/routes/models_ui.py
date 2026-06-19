from pathlib import Path

import httpx
import yaml
from fastapi import APIRouter

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


@router.get("/models/available")
async def list_available_models() -> list[dict[str, object]]:
    """Return the curated OpenCode Go model catalog.

    Only one entry per model (no tier duplicates), so the chat selector
    stays clean. Tier is exposed via ``/api/models/tiers`` instead.
    """
    return list(OPENCODE_GO_MODEL_CATALOG)


@router.get("/models/tiers")
async def list_tier_mapping() -> dict[str, str]:
    """Return the tier -> OpenCode Go model mapping used by the smart router."""
    return dict(TIER_TO_OPENCODE_MODEL)
