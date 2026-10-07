"""Model Roles — port of the oh-my-pi ``modelRoles`` routing.

A role maps to a concrete provider model id through a resolution chain:

1. explicit override (per-call / per-run temporary switch),
2. ``NEXUS_MODEL_ROLES`` env JSON (role → selector),
3. ``config/model-roles.yaml`` (``roles:`` map, supports ``@other-role``
   aliases and bare tier names),
4. built-in role → tier defaults resolved against ``config/models.yaml``.

A selector is either ``@role`` (alias chain), a tier name from
``config/models.yaml``, or a concrete model id. ``:thinking`` suffixes are
accepted on any selector and carried through in :attr:`RoleResolution.thinking`.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config"
MODEL_ROLES_YAML = CONFIG_DIR / "model-roles.yaml"
MODELS_YAML = CONFIG_DIR / "models.yaml"

ROLES: tuple[str, ...] = (
    "default", "smol", "slow", "plan",
    "designer", "task", "advisor", "tiny", "vision",
)

#: Built-in role→tier fallbacks. Every NEXUS agent already routes by tier,
#: so roles degrade gracefully into the existing catalog.
ROLE_DEFAULT_TIER: dict[str, str] = {
    "default": "coder",
    "smol": "fast",
    "tiny": "micro",
    "slow": "deep",
    "plan": "reasoning",
    "designer": "medium",
    "task": "coder",
    "advisor": "reasoning",
    "vision": "vision",
}

_THINKING_SUFFIXES = ("xhigh", "high", "medium", "low", "minimal", "off")


@dataclass(frozen=True, slots=True)
class RoleResolution:
    role: str
    model_id: str
    source: str
    chain: tuple[str, ...]
    thinking: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "model_id": self.model_id,
            "source": self.source,
            "chain": list(self.chain),
            "thinking": self.thinking,
        }


def _split_thinking(selector: str) -> tuple[str, str]:
    for suffix in _THINKING_SUFFIXES:
        marker = f":{suffix}"
        if selector.endswith(marker):
            return selector[: -len(marker)], suffix
    return selector, ""


def load_tiers() -> dict[str, str]:
    """tier → model id from ``config/models.yaml``."""
    try:
        with open(MODELS_YAML, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        logger.warning("models.yaml not found at %s", MODELS_YAML)
        return {}
    tiers: dict[str, str] = {}
    for tier, cfg in (raw.get("models") or {}).items():
        if isinstance(cfg, dict) and cfg.get("id"):
            tiers[str(tier)] = str(cfg["id"])
    return tiers


def load_role_config() -> dict[str, str]:
    """role → selector from ``config/model-roles.yaml`` + env override."""
    roles: dict[str, str] = {}
    try:
        with open(MODEL_ROLES_YAML, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        for name, selector in (raw.get("roles") or {}).items():
            if isinstance(selector, str) and selector.strip():
                roles[str(name)] = selector.strip()
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001 — config must never crash routing
        logger.exception("model-roles.yaml unreadable; ignoring")
    env_raw = os.environ.get("NEXUS_MODEL_ROLES", "")
    if env_raw.strip():
        try:
            parsed = json.loads(env_raw)
            if isinstance(parsed, dict):
                for name, selector in parsed.items():
                    if isinstance(selector, str) and selector.strip():
                        roles[str(name)] = selector.strip()
        except json.JSONDecodeError:
            logger.warning("NEXUS_MODEL_ROLES is not valid JSON; ignoring")
    return roles


def resolve_role(
    role: str,
    *,
    override: str | None = None,
    tiers: dict[str, str] | None = None,
    role_config: dict[str, str] | None = None,
) -> RoleResolution:
    """Resolve one role to a concrete model id (cycle-safe alias chains)."""
    name = (override or "").strip() or role.strip().lower()
    if override:
        selector, thinking = _split_thinking(override.strip())
        if not selector.startswith("@"):
            return RoleResolution(
                role=role,
                model_id=selector,
                source="override",
                chain=(f"@{role}",),
                thinking=thinking,
            )
        name = selector[1:].strip().lower()

    tiers = tiers if tiers is not None else load_tiers()
    role_config = role_config if role_config is not None else load_role_config()

    seen: list[str] = []
    current = name
    thinking = ""
    while True:
        if current in seen:
            logger.warning("model role alias cycle at %r; falling back", current)
            break
        seen.append(current)
        selector = role_config.get(current, "")
        selector, suffix = _split_thinking(selector)
        thinking = thinking or suffix
        if not selector:
            break
        if selector.startswith("@"):
            nxt = selector[1:].strip().lower()
            if not nxt:
                break
            current = nxt
            continue
        lowered = selector.lower()
        if lowered in tiers:
            return RoleResolution(role=role, model_id=tiers[lowered],
                                  source=f"tier:{lowered}", chain=tuple(seen),
                                  thinking=thinking)
        return RoleResolution(role=role, model_id=selector, source="config",
                              chain=tuple(seen), thinking=thinking)

    tier = ROLE_DEFAULT_TIER.get(name or role, ROLE_DEFAULT_TIER["default"])
    if tier in tiers:
        return RoleResolution(role=role, model_id=tiers[tier],
                              source=f"builtin-tier:{tier}",
                              chain=tuple([*seen, tier]), thinking=thinking)
    fallback = tiers.get("coder") or tiers.get("fast") or ""
    return RoleResolution(role=role, model_id=fallback, source="fallback",
                          chain=tuple(seen), thinking=thinking)


def resolve_all() -> dict[str, RoleResolution]:
    return {role: resolve_role(role) for role in ROLES}


def apply_temporary_override(agent_context: dict[str, Any], model_id: str) -> None:
    """Switch the running primary lane's model for its NEXT cycle.

    The signal-stream factory re-reads ``agent_context["_model_override"]``
    when composing each turn's request, so mutating it between cycles takes
    effect without rebuilding the pipeline. Context-scoped ⇒ automatically
    temporary: nothing outside this run observes the change.
    """
    if model_id:
        agent_context["_model_override"] = model_id


__all__ = [
    "ROLES",
    "ROLE_DEFAULT_TIER",
    "RoleResolution",
    "apply_temporary_override",
    "load_role_config",
    "load_tiers",
    "resolve_all",
    "resolve_role",
]
