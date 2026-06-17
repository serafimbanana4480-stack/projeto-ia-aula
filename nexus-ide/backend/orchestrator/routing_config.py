"""
Shared routing configuration — single source of truth for tier→agent mapping.
Previously duplicated in smart_router.py and chat.py.
"""

from __future__ import annotations

# Maps model tiers to the default agent for that tier.
# This is the single source of truth — import from here everywhere.
MODEL_TIER_TO_AGENT: dict[str, str] = {
    # Direct tier → agent mapping
    "micro": "MICRO",
    "fast": "DOCUMENTER",
    "coder": "CODER",
    "reasoning": "ARCHITECT",
    "deep": "ARCHITECT",
    # Legacy compatibility aliases
    "nano": "MICRO",
    "small": "DOCUMENTER",
    "medium": "CODER",
    "large": "ARCHITECT",
    "expert": "ARCHITECT",
    "vision": "CODER",
    "embed": "MICRO",
    "dashboard": "DASHBOARD",
    # Legacy Qwen-specific aliases
    "q3b-4bit": "MICRO",
    "coder3b-4bit": "CODER",
}
