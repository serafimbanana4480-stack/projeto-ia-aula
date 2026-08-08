from __future__ import annotations

import pytest

import backend.llm.openrouter_provider as openrouter_module
from backend.llm.openrouter_provider import OpenRouterProvider


def test_extracts_account_reset_from_openrouter_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openrouter_module.time, "time", lambda: 1_785_640_000.0)
    error = RuntimeError(
        '429 {"headers":{"X-RateLimit-Reset":"1785640060500"},'
        '"limit_source":"openrouter_free_tier_per_minute"}'
    )

    assert OpenRouterProvider._rate_limit_reset_delay(error) == pytest.approx(60.5)


@pytest.mark.asyncio
async def test_provider_wide_slot_guard_spaces_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenRouterProvider(api_key="test")
    second_provider = OpenRouterProvider(api_key="test")
    provider._min_request_interval = 3.1
    second_provider._min_request_interval = 3.1
    clock = {"now": 10.0}
    sleeps: list[float] = []

    monkeypatch.setattr(openrouter_module.time, "monotonic", lambda: clock["now"])

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        clock["now"] += delay

    monkeypatch.setattr(openrouter_module.asyncio, "sleep", fake_sleep)

    await provider._reserve_request_slot()
    await second_provider._reserve_request_slot()

    assert sleeps == [pytest.approx(3.1)]
    await provider.aclose()
    await second_provider.aclose()


@pytest.mark.asyncio
async def test_interactive_slot_does_not_sleep_through_quota_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenRouterProvider(api_key="test")
    provider._min_request_interval = 0.0
    monkeypatch.setattr(openrouter_module.time, "monotonic", lambda: 100.0)
    await openrouter_module._process_quota_lock()
    openrouter_module._quota_cooldown_until = 160.0

    with pytest.raises(RuntimeError, match="refusing to queue"):
        await provider._reserve_request_slot(max_wait_seconds=12.0)

    await provider.aclose()
