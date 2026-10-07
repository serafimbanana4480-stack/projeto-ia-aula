from __future__ import annotations

from backend.agents.micro import MicroAgent


def test_micro_keeps_simple_answers_brief_but_honors_requested_detail() -> None:
    prompt = MicroAgent().system_prompt()

    assert "Match the language, format, and level of detail" in prompt
    assert "with no requested structure or length" in prompt
    assert "at most three sentences" in prompt
    assert "follow that request" in prompt
