"""Multi-LLM Manager with load balancing, failover, and parallel execution."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from collections.abc import AsyncIterator
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class MultiLLMManager:
    """Manages multiple LLM providers with load balancing, failover, and parallel execution."""

    def __init__(self) -> None:
        self.providers: dict[str, Any] = {}  # name -> provider instance
        self.health_status: dict[str, dict[str, Any]] = {}  # name -> health info
        self._priority: dict[str, int] = {}  # name -> priority (lower = higher)

    def register_provider(self, name: str, provider: Any, priority: int = 1) -> None:
        """Register a provider with priority (lower = higher priority)."""
        self.providers[name] = provider
        self._priority[name] = priority
        self.health_status[name] = {
            "healthy": True,
            "latency": 0.0,
            "last_check": 0.0,
            "success_rate": 1.0,
            "request_count": 0,
            "failure_count": 0,
        }
        logger.info("Registered LLM provider '%s' with priority %d", name, priority)

    async def aclose(self) -> None:
        """Close all registered providers."""
        await asyncio.gather(
            *(
                provider.aclose()
                for provider in self.providers.values()
                if hasattr(provider, "aclose")
            ),
            return_exceptions=True,
        )

    async def health_check_all(self) -> dict[str, dict[str, Any]]:
        """Check health of all providers."""
        results: dict[str, dict[str, Any]] = {}
        for name, provider in self.providers.items():
            started = time.time()
            healthy = False
            latency = 0.0
            try:
                client = getattr(provider, "_client", None)
                if isinstance(client, httpx.AsyncClient):
                    # OpenAI-compatible providers (OpenAIProvider, KimiProvider)
                    resp = await client.get("/models", timeout=5.0)
                    healthy = resp.status_code == 200
                elif hasattr(client, "_client") and isinstance(
                    client._client, httpx.AsyncClient
                ):
                    # OllamaProvider -> OllamaClient -> httpx.AsyncClient
                    base_url = str(client._client.base_url).rstrip("/")
                    async with httpx.AsyncClient(timeout=5.0) as temp:
                        resp = await temp.get(f"{base_url}/api/tags")
                        healthy = resp.status_code == 200
                else:
                    healthy = True
                latency = (time.time() - started) * 1000
            except Exception as exc:
                logger.warning("Health check failed for provider '%s': %s", name, exc)
                healthy = False
                latency = (time.time() - started) * 1000

            health = self.health_status.setdefault(name, {})
            health["healthy"] = healthy
            health["latency"] = latency
            health["last_check"] = time.time()
            results[name] = dict(health)
        return results

    def _update_health(self, name: str, success: bool, latency_ms: float) -> None:
        health = self.health_status.setdefault(name, {})
        health["request_count"] = health.get("request_count", 0) + 1
        if not success:
            health["failure_count"] = health.get("failure_count", 0) + 1
        total = health["request_count"]
        failures = health["failure_count"]
        health["success_rate"] = (total - failures) / total if total > 0 else 1.0
        if success:
            old_latency = health.get("latency", 0.0)
            if old_latency == 0.0:
                health["latency"] = latency_ms
            else:
                health["latency"] = old_latency * 0.7 + latency_ms * 0.3

    def get_best_provider(self) -> str:
        """Return the healthiest provider based on latency and success rate."""
        candidates = [
            (name, info)
            for name, info in self.health_status.items()
            if info.get("healthy", False) and name in self.providers
        ]
        if not candidates:
            if self.providers:
                return next(iter(self.providers))
            raise RuntimeError("No providers registered")

        def score(item: tuple[str, dict[str, Any]]) -> float:
            name, info = item
            p = self._priority.get(name, 1)
            lat = info.get("latency", 999999.0)
            sr = info.get("success_rate", 0.0)
            return p * 1000 + lat + (1 - sr) * 10000

        best, _ = min(candidates, key=score)
        return best

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
        provider: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Send chat completion. If provider specified, use it. Otherwise use best available."""
        target = provider or self.get_best_provider()
        if target not in self.providers:
            raise RuntimeError(f"Provider '{target}' not registered")

        last_error: Exception | None = None
        names_to_try = [target] + [n for n in self.providers if n != target]
        for name in names_to_try:
            started = time.time()
            success = False
            try:
                result = await self.providers[name].chat_complete(
                    model=model, messages=messages, options=options, **kwargs
                )
                success = True
                self._update_health(name, True, (time.time() - started) * 1000)
                return result
            except Exception as exc:
                last_error = exc
                self._update_health(name, False, (time.time() - started) * 1000)
                logger.warning("Provider '%s' failed for chat_complete: %s", name, exc)

        raise last_error or RuntimeError("All providers failed for chat_complete")

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
        provider: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream chat completion with same logic."""
        target = provider or self.get_best_provider()
        if target not in self.providers:
            raise RuntimeError(f"Provider '{target}' not registered")

        last_error: Exception | None = None
        names_to_try = [target] + [n for n in self.providers if n != target]
        for name in names_to_try:
            started = time.time()
            success = False
            try:
                async for token in self.providers[name].chat_stream(
                    model=model, messages=messages, options=options, **kwargs
                ):
                    yield token
                success = True
                self._update_health(name, True, (time.time() - started) * 1000)
                return
            except Exception as exc:
                last_error = exc
                self._update_health(name, False, (time.time() - started) * 1000)
                logger.warning("Provider '%s' failed for chat_stream: %s", name, exc)

        raise last_error or RuntimeError("All providers failed for chat_stream")

    async def parallel_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        providers: list[str],
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Send same request to multiple providers in parallel, return fastest successful response."""
        valid_providers = [p for p in providers if p in self.providers]
        if not valid_providers:
            raise RuntimeError("No valid providers for parallel completion")

        async def _call(name: str) -> tuple[str, str]:
            started = time.time()
            result = await self.providers[name].chat_complete(
                model=model, messages=messages, options=options, **kwargs
            )
            latency = (time.time() - started) * 1000
            self._update_health(name, True, latency)
            return name, result

        tasks = {asyncio.create_task(_call(name)): name for name in valid_providers}
        pending: set[asyncio.Task] = set(tasks.keys())
        last_error: Exception | None = None
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                try:
                    _, result = task.result()
                    for t in pending:
                        t.cancel()
                    return result
                except Exception as exc:
                    last_error = exc
                    self._update_health(tasks[task], False, 0.0)
                    logger.warning(
                        "Parallel provider '%s' failed: %s", tasks[task], exc
                    )

        raise last_error or RuntimeError("All parallel providers failed")

    async def consensus_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        providers: list[str],
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Send to multiple providers and return the consensus (most common) response."""
        valid_providers = [p for p in providers if p in self.providers]
        if not valid_providers:
            raise RuntimeError("No valid providers for consensus completion")

        results: dict[str, str] = {}

        async def _call(name: str) -> None:
            try:
                result = await self.providers[name].chat_complete(
                    model=model, messages=messages, options=options, **kwargs
                )
                results[name] = result
            except Exception as exc:
                logger.warning("Consensus provider '%s' failed: %s", name, exc)

        await asyncio.gather(*(_call(name) for name in valid_providers))
        if not results:
            raise RuntimeError("All consensus providers failed")

        counter = Counter(results.values())
        most_common, _ = counter.most_common(1)[0]
        return most_common
