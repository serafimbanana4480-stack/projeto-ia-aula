"""Structured, explicit Infinity actions that can be run from chat."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class StructuredModeAction:
    mode_id: str
    action: str
    payload: dict[str, Any]


_MODE_ACTIONS = {
    "advisor-infinity": "review",
    "multiverse": "rank",
    "sentinel": "gate",
}


def _reject_non_json_constant(value: str) -> None:
    raise ValueError(f"JSON não aceita o valor {value}")


def parse_structured_mode_action(
    mode_id: str, arguments: str
) -> StructuredModeAction | None:
    """Parse one explicit ``<action> <JSON object>`` mode subcommand.

    Plain natural-language mode requests return ``None`` and continue through
    their existing agent adapter. Structured actions call the same backend
    evaluation methods as the corresponding REST endpoints.
    """
    expected_action = _MODE_ACTIONS.get(mode_id)
    if expected_action is None:
        return None

    parts = (arguments or "").strip().split(None, 1)
    if not parts or parts[0].casefold() != expected_action:
        return None
    if len(parts) != 2 or not parts[1].lstrip().startswith("{"):
        raise ValueError(
            f"Usa: /{mode_id} {expected_action} <objeto JSON>"
        )

    try:
        payload = json.loads(parts[1], parse_constant=_reject_non_json_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"JSON inválido para /{mode_id} {expected_action}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("A entrada tem de ser um objeto JSON.")
    if mode_id == "sentinel" and "risk_level" not in payload:
        raise ValueError("Indica explicitamente risk_level entre 0 e 4.")

    return StructuredModeAction(
        mode_id=mode_id,
        action=expected_action,
        payload=payload,
    )


__all__ = ["StructuredModeAction", "parse_structured_mode_action"]
