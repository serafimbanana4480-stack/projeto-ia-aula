"""NEXUS IDE — Infinity v3 (port of the oh-my-pi advisor / vibe / model-roles).

Modules:
    model_roles    — role-based model routing with mid-session switching.
    comm           — typed AI↔AI envelopes (DIRECTIVE/RESULT/NOTE/STEER).
    advisor_engine — a live reviewer model that watches every run turn and
                     injects notes (nit/concern/blocker) mid-session.
    vibe_director  — persistent worker sessions driven by spawn/send/wait/
                     kill/list semantics.
"""

from __future__ import annotations

import os

INFINITY_STATE_DIR_NAME = "infinity"


def env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "off", "no", ""}


def advisor_live_enabled() -> bool:
    """Live advisor watches every primary run unless explicitly disabled."""
    return env_flag("NEXUS_ADVISOR_ENABLED", True)


def vibe_lane_enabled() -> bool:
    """Explicit ``/vibe-infinity <request>`` commands use the real vibe lane."""
    return env_flag("NEXUS_VIBE_LANE", True)


__all__ = [
    "INFINITY_STATE_DIR_NAME",
    "advisor_live_enabled",
    "env_flag",
    "vibe_lane_enabled",
]
