from __future__ import annotations

import asyncio
import pytest

from backend.llm.circuit_breaker import CircuitBreaker, get_breaker, reset_all_breakers
from backend.llm.free_policy import ProviderUnavailableError
from backend.llm.multi_llm_manager import MultiLLMManager


class FailingProvider:
    async def chat_complete(self, **_: object) -> str:
        raise RuntimeError("429 rate limit quota exceeded")


class WorkingProvider:
    async def chat_complete(self, **_: object) -> str:
        return "validated free response"


class SimulationProvider:
    simulation = True

    async def chat_complete(self, **_: object) -> str:
        return "simulated response"


@pytest.mark.asyncio
async def test_failure_trips_breaker_and_falls_to_next_provider_without_sleep() -> None:
    reset_all_breakers()
    manager = MultiLLMManager()
    manager.register_provider("primary", FailingProvider(), priority=0)
    manager.register_provider("fallback", WorkingProvider(), priority=1)
    result = await manager.chat_complete("openrouter/free", [{"role": "user", "content": "hi"}])
    assert result == "validated free response"
    assert get_breaker("primary").snapshot()["failures"] == 1
    reset_all_breakers()


@pytest.mark.asyncio
async def test_open_breaker_fails_fast_with_typed_error() -> None:
    reset_all_breakers()
    manager = MultiLLMManager()
    manager.register_provider("primary", FailingProvider())
    breaker = get_breaker("primary", failure_threshold=1, cooldown_seconds=60)
    await breaker.record_failure()
    with pytest.raises(ProviderUnavailableError) as error:
        await manager.chat_complete("openrouter/free", [{"role": "user", "content": "hi"}], provider="primary")
    assert error.value.category == "breaker_open"
    assert error.value.retry_after is not None
    reset_all_breakers()


@pytest.mark.asyncio
async def test_simulation_cannot_complete_a_real_run() -> None:
    reset_all_breakers()
    manager = MultiLLMManager()
    manager.register_provider("dev", SimulationProvider())
    with pytest.raises(ProviderUnavailableError) as error:
        await manager.chat_complete("dev", [{"role": "user", "content": "hi"}], provider="dev")
    assert error.value.category == "simulation"
    reset_all_breakers()

def test_existing_typed_error_is_enriched_with_lane_identity() -> None:
    error = ProviderUnavailableError("blocked", category="quota")
    enriched = MultiLLMManager._typed_provider_error(error, "openrouter", "openrouter/free")
    assert enriched is error
    assert enriched.provider == "openrouter"
    assert enriched.model == "openrouter/free"
    assert enriched.category == "quota"


def test_half_open_transition_reserves_single_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    breaker = CircuitBreaker("probe", failure_threshold=1, cooldown_seconds=0, half_open_max_calls=1)
    asyncio.run(breaker.record_failure())
    assert asyncio.run(breaker.is_call_permitted()) is True
    assert asyncio.run(breaker.is_call_permitted()) is False