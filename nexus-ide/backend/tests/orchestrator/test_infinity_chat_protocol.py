from __future__ import annotations

import pytest

from backend.orchestrator.infinity.chat_protocol import parse_structured_mode_action


def test_structured_mode_actions_are_opt_in_and_require_json_objects() -> None:
    assert parse_structured_mode_action("sentinel", "check install safety") is None

    action = parse_structured_mode_action(
        "sentinel",
        'gate {"action":"Install package","risk_level":2,"files":[]}',
    )
    assert action is not None
    assert action.mode_id == "sentinel"
    assert action.action == "gate"
    assert action.payload["risk_level"] == 2


@pytest.mark.parametrize(
    ("mode_id", "arguments"),
    [
        ("advisor-infinity", "review"),
        ("advisor-infinity", 'review ["not", "an", "object"]'),
        ("advisor-infinity", 'review {"claim": NaN}'),
        ("multiverse", "rank {broken}"),
        ("sentinel", 'gate {"action":"read"}'),
    ],
)
def test_structured_mode_actions_reject_invalid_input(mode_id: str, arguments: str) -> None:
    with pytest.raises(ValueError):
        parse_structured_mode_action(mode_id, arguments)
