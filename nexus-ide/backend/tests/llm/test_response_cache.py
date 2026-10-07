"""Testes do ResponseCache (exact-match LLM response cache, 2026-08-25).

Cobre: hit/miss, expiração por TTL, eviction LRU, configuração por env,
thread-safety e integração com o MultiLLMManager (incluindo a decisão de
ordem: cache ANTES do cost governor — um hit custa $0 e nunca é bloqueado).
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from backend.llm.multi_llm_manager import MultiLLMManager
from backend.llm.response_cache import (
    ResponseCache,
    get_response_cache,
    reset_response_cache,
)


@pytest.fixture(autouse=True)
def _cache_env(monkeypatch: pytest.MonkeyPatch):
    """Cache desligado + singleton novo em cada teste."""
    monkeypatch.delenv("NEXUS_LLM_CACHE_TTL", raising=False)
    monkeypatch.delenv("NEXUS_LLM_CACHE_SIZE", raising=False)
    reset_response_cache()
    yield
    reset_response_cache()


class TestResponseCacheUnit:
    def test_disabled_by_default(self) -> None:
        cache = ResponseCache()
        assert cache.enabled is False
        key = cache.cache_key("prov", "model", [{"role": "user", "content": "oi"}])
        cache.store(key, "resposta")
        assert cache.get(key) is None
        stats = cache.get_stats()
        assert stats["llm_cache_size"] == 0
        assert stats["enabled"] is False

    def test_hit_and_miss(self) -> None:
        cache = ResponseCache(ttl_seconds=60)
        key = cache.cache_key("prov", "model", [{"role": "user", "content": "oi"}])
        assert cache.get(key) is None  # miss
        cache.store(key, "resposta")
        assert cache.get(key) == "resposta"  # hit
        stats = cache.get_stats()
        assert stats["llm_cache_hits"] == 1
        assert stats["llm_cache_misses"] == 1

    def test_different_messages_produce_different_keys(self) -> None:
        cache = ResponseCache(ttl_seconds=60)
        k1 = cache.cache_key("prov", "model", [{"role": "user", "content": "a"}])
        k2 = cache.cache_key("prov", "model", [{"role": "user", "content": "b"}])
        assert k1 != k2

    def test_key_includes_provider_model_and_params(self) -> None:
        messages = [{"role": "user", "content": "oi"}]
        base = ResponseCache.cache_key("p1", "m1", messages)
        assert ResponseCache.cache_key("p2", "m1", messages) != base
        assert ResponseCache.cache_key("p1", "m2", messages) != base
        assert ResponseCache.cache_key("p1", "m1", messages, {"temperature": 0.2}) != base

    def test_message_normalization_ignores_extra_fields_and_objects(self) -> None:
        dict_msg = {"role": "user", "content": "oi", "name": "extra"}

        class _Msg:
            role = "user"
            content = "oi"

        assert ResponseCache.cache_key(
            "p", "m", [dict_msg]
        ) == ResponseCache.cache_key("p", "m", [_Msg()])

    def test_non_serializable_kwargs_do_not_change_key(self) -> None:
        messages = [{"role": "user", "content": "oi"}]

        def _callback() -> None:  # pragma: no cover - never called
            return None

        plain = ResponseCache.cache_key("p", "m", messages)
        with_cb = ResponseCache.cache_key("p", "m", messages, on_final_chunk=_callback)
        assert plain == with_cb

    async def test_ttl_expiry(self) -> None:
        cache = ResponseCache(ttl_seconds=0.05)
        key = cache.cache_key("prov", "model", [{"role": "user", "content": "oi"}])
        cache.store(key, "resposta")
        assert cache.get(key) == "resposta"
        await asyncio.sleep(0.08)
        assert cache.get(key) is None
        # Entrada expirada é removida
        assert cache.get_stats()["llm_cache_size"] == 0


class TestLRUEviction:
    def test_evicts_least_recently_used(self) -> None:
        cache = ResponseCache(ttl_seconds=60, max_entries=2)
        ka = cache.cache_key("p", "m", [{"role": "user", "content": "a"}])
        kb = cache.cache_key("p", "m", [{"role": "user", "content": "b"}])
        kc = cache.cache_key("p", "m", [{"role": "user", "content": "c"}])
        cache.store(ka, "A")
        cache.store(kb, "B")
        # Tocar em A torna-o mais recente que B
        assert cache.get(ka) == "A"
        cache.store(kc, "C")  # excede max_entries → evict B (LRU)
        assert cache.get(kb) is None
        assert cache.get(ka) == "A"
        assert cache.get(kc) == "C"
        assert cache.get_stats()["llm_cache_size"] == 2

    def test_env_size_is_respected_by_singleton(self, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_LLM_CACHE_TTL", "60")
        monkeypatch.setenv("NEXUS_LLM_CACHE_SIZE", "1")
        cache = get_response_cache()
        assert cache.max_entries == 1
        ka = cache.cache_key("p", "m", [{"role": "user", "content": "a"}])
        kb = cache.cache_key("p", "m", [{"role": "user", "content": "b"}])
        cache.store(ka, "A")
        cache.store(kb, "B")
        assert cache.get(ka) is None
        assert cache.get(kb) == "B"


class TestEnvConfig:
    def test_ttl_zero_means_disabled(self) -> None:
        assert ResponseCache().enabled is False

    def test_ttl_positive_enables_singleton(self, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_LLM_CACHE_TTL", "120")
        cache = get_response_cache()
        assert cache.enabled is True
        assert cache.ttl_seconds == pytest.approx(120.0)

    def test_invalid_env_falls_back_to_default(self, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_LLM_CACHE_TTL", "abc")
        monkeypatch.setenv("NEXUS_LLM_CACHE_SIZE", "-4")
        cache = ResponseCache()
        assert cache.enabled is False
        assert cache.max_entries == 256


class TestThreadSafety:
    def test_concurrent_get_store_never_exceeds_max_entries(self) -> None:
        cache = ResponseCache(ttl_seconds=60, max_entries=16)
        errors: list[Exception] = []

        def worker(worker_id: int) -> None:
            try:
                for i in range(200):
                    key = f"key-{worker_id}-{i % 32}"
                    cache.store(key, f"value-{worker_id}")
                    cache.get(key)
            except Exception as exc:  # pragma: no cover - only on failure
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert not errors
        assert cache.get_stats()["llm_cache_size"] <= 16


# ---------------------------------------------------------------------------
# Integração com MultiLLMManager
# ---------------------------------------------------------------------------


class _CountingProvider:
    """Provider real (não-simulação) que conta chamadas."""

    simulation = False

    def __init__(self) -> None:
        self.complete_calls = 0
        self.stream_calls = 0
        self.seen_kwargs: list[dict] = []

    async def chat_complete(self, model, messages, **kwargs) -> str:
        self.complete_calls += 1
        self.seen_kwargs.append(dict(kwargs))
        return f"answer:{messages[-1]['content']}:{self.complete_calls}"

    async def chat_stream(self, model, messages, **kwargs):
        self.stream_calls += 1
        for word in f"stream:{messages[-1]['content']}".split():
            yield word


class TestManagerIntegration:
    async def test_second_identical_call_is_served_from_cache(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("NEXUS_LLM_CACHE_TTL", "300")
        reset_response_cache()

        manager = MultiLLMManager(free_only=False)
        provider = _CountingProvider()
        manager.register_provider("cache-fake", provider)

        messages = [{"role": "user", "content": "olá"}]
        first = await manager.chat_complete("modelo-x", messages)
        second = await manager.chat_complete("modelo-x", messages)

        assert first == second == "answer:olá:1"
        assert provider.complete_calls == 1
        assert get_response_cache().get_stats()["llm_cache_hits"] == 1

    async def test_cache_miss_on_different_messages(self, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_LLM_CACHE_TTL", "300")
        reset_response_cache()

        manager = MultiLLMManager(free_only=False)
        provider = _CountingProvider()
        manager.register_provider("cache-fake-diff", provider)

        first = await manager.chat_complete("m", [{"role": "user", "content": "um"}])
        second = await manager.chat_complete("m", [{"role": "user", "content": "dois"}])

        assert first != second
        assert provider.complete_calls == 2

    async def test_run_id_kwarg_never_reaches_provider(self, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_LLM_CACHE_TTL", "300")
        reset_response_cache()

        manager = MultiLLMManager(free_only=False)
        provider = _CountingProvider()
        manager.register_provider("cache-fake-runid", provider)

        await manager.chat_complete(
            "m", [{"role": "user", "content": "oi"}], run_id="run-abc"
        )
        assert provider.complete_calls == 1
        assert all("run_id" not in kwargs for kwargs in provider.seen_kwargs)

    async def test_streaming_is_never_cached(self, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_LLM_CACHE_TTL", "300")
        reset_response_cache()

        manager = MultiLLMManager(free_only=False)
        provider = _CountingProvider()
        manager.register_provider("cache-fake-stream", provider)

        chunks: list[str] = []
        for _ in range(2):
            async for token in manager.chat_stream(
                "m", [{"role": "user", "content": "oi"}]
            ):
                chunks.append(token)

        assert len(chunks) == 2
        assert provider.stream_calls == 2
        # O stream não popular a cache: um chat_complete seguinte despacha.
        assert provider.complete_calls == 0

    async def test_cache_hit_survives_exhausted_budget(
        self, monkeypatch, tmp_path
    ) -> None:
        """Decisão de ordem: hit é servido mesmo com o orçamento esgotado."""
        from backend.llm import multi_llm_manager as mlm_module
        from backend.llm.cost_governor import (
            get_cost_governor,
            reset_cost_governor,
        )
        from backend.llm.free_policy import ProviderUnavailableError

        monkeypatch.setenv("NEXUS_LLM_CACHE_TTL", "300")
        monkeypatch.setenv("NEXUS_DAILY_BUDGET_USD", "0.10")
        reset_response_cache()
        reset_cost_governor()
        original_compute = mlm_module._compute_cost
        try:
            get_cost_governor(tmp_path / "nexus.db")
            monkeypatch.setattr(
                mlm_module, "_compute_cost", lambda *args, **kwargs: 0.50
            )

            manager = MultiLLMManager(free_only=False)
            provider = _CountingProvider()
            manager.register_provider("cache-budget-fake", provider)

            messages = [{"role": "user", "content": "olá"}]
            first = await manager.chat_complete("m", messages)  # gasta $0.50
            # Orçamento diário agora exaurido ($0.50 ≥ $0.10):
            # um HIT tem de ser devolvido — custa $0.
            hit = await manager.chat_complete("m", messages)
            with pytest.raises(ProviderUnavailableError) as excinfo:
                await manager.chat_complete(
                    "m", [{"role": "user", "content": "outro"}]
                )

            assert first.startswith("answer:")
            assert hit == first
            assert excinfo.value.category == "budget_exceeded"
            assert provider.complete_calls == 1  # só a primeira chamada despachou
        finally:
            monkeypatch.setattr(mlm_module, "_compute_cost", original_compute)
            reset_cost_governor()
