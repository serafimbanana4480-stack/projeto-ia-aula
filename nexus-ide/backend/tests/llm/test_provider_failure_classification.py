"""Tests for provider-failure classification.

When every provider fails, the user only sees one string. That string has to
say *what kind* of failure happened — a refused key, an exhausted quota and a
local server that is not running need three different actions — and the
message has to carry the remediation, not only the raw exception text.
"""

from __future__ import annotations

import pytest

from backend.llm.factory import (
    FAILURE_REMEDIATION,
    _aggregate_failure_category,
    classify_provider_failure,
)


class _FakeError(Exception):
    """An exception that carries the attributes a provider error can carry."""

    def __init__(self, message: str, *, status_code: int | None = None, category: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.category = category


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_FakeError("All connection attempts failed"), "network"),
        (_FakeError("HTTP 401", status_code=401), "auth"),
        (_FakeError("HTTP 403", status_code=403), "auth"),
        (_FakeError("HTTP 402", status_code=402), "quota"),
        (_FakeError("HTTP 429", status_code=429), "rate_limit"),
        (_FakeError("request timed out"), "timeout"),
        (_FakeError("OpenAI stream completed without text content"), "empty_stream"),
        (_FakeError("Cost budget exceeded for this run"), "budget"),
        # A provider's own dispatch budget is a rate limit, not a cost limit.
        (
            _FakeError("OpenRouter dispatch budget exceeded; refusing to queue"),
            "rate_limit",
        ),
        # An explicit category always wins over the message text.
        (
            _FakeError("dispatch budget exceeded", category="quota"),
            "quota",
        ),
    ],
)
def test_classify_provider_failure(error: Exception, expected: str) -> None:
    assert classify_provider_failure(error) == expected


def test_aggregate_prefers_the_failure_the_user_must_decide() -> None:
    # A refused key and a local server that is down: the key is the decision.
    assert _aggregate_failure_category(["network", "auth"]) == "auth"
    # Only rate limits: that is the story.
    assert _aggregate_failure_category(["rate_limit", "rate_limit"]) == "rate_limit"
    # Nothing classified: no aggregate.
    assert _aggregate_failure_category([]) == ""


def test_every_category_has_remediation_text() -> None:
    for category in (
        "auth",
        "quota",
        "rate_limit",
        "network",
        "timeout",
        "empty_stream",
        "budget",
        "unknown",
    ):
        assert FAILURE_REMEDIATION.get(category), f"missing remediation for {category}"
