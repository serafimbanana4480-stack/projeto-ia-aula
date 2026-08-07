"""Multi-LLM Manager with load balancing, failover, and parallel execution.

Includes TokenTracker for usage accounting and cost tracking.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import Counter
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from backend.llm.circuit_breaker import get_breaker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token usage tracking
# ---------------------------------------------------------------------------


@dataclass
class TokenUsage:
    """Token counts and cost for a single LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    provider: str = ""
    timestamp: float = 0.0


@dataclass
class UsageSnapshot:
    """Aggregate usage snapshot over a time window."""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    call_count: int = 0
    # Breakdowns
    by_model: dict[str, int] = field(default_factory=dict)
    by_provider: dict[str, int] = field(default_factory=dict)
    cost_by_model: dict[str, float] = field(default_factory=dict)


class TokenTracker:
    """In-memory token usage tracker with optional periodic flush to DB.

    The tracker accumulates usage from every LLM call.  A callback
    (*flush_hook*) can be registered to persist usage to the database
    or external monitoring system.

    Thread-safe for writes from multiple providers / callers.
    """

    def __init__(self, flush_hook: Callable[[TokenUsage], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._records: list[TokenUsage] = []
        self._flush_hook = flush_hook

    def record(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str = "",
        provider: str = "",
        cost_usd: float = 0.0,
    ) -> None:
        """Record a single LLM call's token usage."""
        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=cost_usd,
            model=model,
            provider=provider,
            timestamp=time.time(),
        )
        with self._lock:
            self._records.append(usage)

        # Call the flush hook (if set)
        if self._flush_hook:
            try:
                self._flush_hook(usage)
            except Exception as exc:
                logger.warning("TokenTracker flush hook failed: %s", exc)

    def snapshot(self, since: float = 0.0) -> UsageSnapshot:
        """Return aggregate usage from records since *since* (Unix timestamp).

        If *since* is 0.0, returns all records.
        """
        by_model: dict[str, int] = {}
        by_provider: dict[str, int] = {}
        cost_by_model: dict[str, float] = {}
        total_in = 0
        total_out = 0
        total_cost = 0.0
        count = 0

        with self._lock:
            for rec in self._records:
                if since and rec.timestamp < since:
                    continue
                total_in += rec.input_tokens
                total_out += rec.output_tokens
                total_cost += rec.cost_usd
                count += 1
                if rec.model:
                    by_model[rec.model] = by_model.get(rec.model, 0) + rec.total_tokens
                    cost_by_model[rec.model] = cost_by_model.get(rec.model, 0.0) + rec.cost_usd
                if rec.provider:
                    by_provider[rec.provider] = by_provider.get(rec.provider, 0) + rec.total_tokens
        # Keep a copy for external consumers even after release
        return UsageSnapshot(
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_cost_usd=round(total_cost, 4),
            call_count=count,
            by_model=dict(by_model),
            by_provider=dict(by_provider),
            cost_by_model=dict(cost_by_model),
        )

    def clear(self) -> None:
        """Reset all accumulated records."""
        with self._lock:
            self._records.clear()

    @property
    def total_calls(self) -> int:
        """Return total number of recorded calls."""
        with self._lock:
            return len(self._records)

    @property
    def total_input_tokens(self) -> int:
        with self._lock:
            return sum(r.input_tokens for r in self._records)

    @property
    def total_output_tokens(self) -> int:
        with self._lock:
            return sum(r.output_tokens for r in self._records)

    @property
    def total_cost_usd(self) -> float:
        with self._lock:
            return round(sum(r.cost_usd for r in self._records), 4)

    def get_recent_usage(self, limit: int = 100) -> list[TokenUsage]:
        """Return the most recent *limit* usage records."""
        with self._lock:
            return list(self._records[-limit:])


# Global tracker instance, used by routes/usage.py
_tracker: TokenTracker | None = None
_tracker_lock = threading.Lock()


def get_token_tracker() -> TokenTracker:
    """Return the global TokenTracker singleton."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = TokenTracker()
    return _tracker


# ---------------------------------------------------------------------------
# MultiLLMManager
# ---------------------------------------------------------------------------


def _estimate_tokens(text: str) -> int:
    """Quick token estimate (~4 chars ≈ 1 token for English text)."""
    return max(1, len(text) // 4)


def _extract_provider_usage(provider: Any) -> dict[str, int]:
    """Try to get usage info from a provider via its ``last_usage`` property.

    Returns an empty dict if the provider does not expose usage info.
    """
    try:
        if hasattr(provider, "last_usage"):
            return provider.last_usage  # type: ignore[return-value]
    except Exception:
        pass
    return {}


def _compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Look up pricing from the pricing table and compute cost in USD."""
    try:
        from backend.llm.pricing import PricingTable

        pt = PricingTable.get_instance()
        return pt.compute_cost(model=model, input_tokens=input_tokens, output_tokens=output_tokens)
    except Exception:
        return 0.0


class MultiLLMManager:
    """Manages multiple LLM providers with load balancing, failover, and parallel execution."""

    def __init__(self) -> None:
        self.providers: dict[str, Any] = {}  # name -> provider instance
        self.health_status: dict[str, dict[str, Any]] = {}  # name -> health info
        self._priority: dict[str, int] = {}  # name -> priority (lower = higher)
        self._tracker = get_token_tracker()

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
                if hasattr(provider, "health_check"):
                    healthy = await provider.health_check()
                else:
                    client = getattr(provider, "_client", None)
                    if isinstance(client, httpx.AsyncClient):
                        resp = await client.get("/models", timeout=5.0)
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

    def _record_usage(
        self,
        provider_name: str,
        model: str,
        messages: list[dict[str, str]],
        output_text: str | None,
    ) -> None:
        """Extract / estimate usage and record it in the tracker."""
        provider = self.providers.get(provider_name)
        usage = _extract_provider_usage(provider) if provider else {}

        if usage:
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
        else:
            # Fallback: estimate from text
            input_text = " ".join(m.get("content", "") for m in messages)
            input_tokens = _estimate_tokens(input_text)
            output_tokens = _estimate_tokens(output_text or "")

        if input_tokens == 0:
            input_tokens = _estimate_tokens(
                " ".join(m.get("content", "") for m in messages)
            )
        if output_tokens == 0 and output_text:
            output_tokens = _estimate_tokens(output_text)

        cost = _compute_cost(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        self._tracker.record(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            provider=provider_name,
            cost_usd=cost,
        )

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
            breaker = get_breaker(name)
            if not await breaker.is_call_permitted():
                logger.info(
                    "Circuit breaker: skipping provider '%s' (state=%s)", name, breaker.state
                )
                last_error = RuntimeError(f"Circuit breaker open for '{name}'")
                continue

            started = time.time()
            try:
                result = await self.providers[name].chat_complete(
                    model=model, messages=messages, options=options, **kwargs
                )
                await breaker.record_success()
                self._update_health(name, True, (time.time() - started) * 1000)
                # Record token usage
                self._record_usage(provider_name=name, model=model, messages=messages, output_text=result)
                logger.info("Provider '%s' succeeded for chat_complete", name)
                return result
            except Exception as exc:
                await breaker.record_failure()
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
        """Stream a completion, failing over only before visible output.

        A streaming provider can fail after it has already emitted tokens.
        Restarting that request on another provider corrupts the answer and can
        repeat downstream ReAct tool calls, so only pre-output failures are
        eligible for failover.
        """
        target = provider or self.get_best_provider()
        if target not in self.providers:
            raise RuntimeError(f"Provider '{target}' not registered")

        last_error: Exception | None = None
        names_to_try = [target] + [n for n in self.providers if n != target]
        for name in names_to_try:
            breaker = get_breaker(name)
            if not await breaker.is_call_permitted():
                logger.info(
                    "Circuit breaker: skipping provider '%s' (state=%s)", name, breaker.state
                )
                last_error = RuntimeError(f"Circuit breaker open for '{name}'")
                continue

            started = time.time()
            chunks: list[str] = []
            emitted_output = False
            try:
                async for token in self.providers[name].chat_stream(
                    model=model, messages=messages, options=options, **kwargs
                ):
                    if token:
                        emitted_output = True
                    chunks.append(token)
                    yield token
                if not emitted_output:
                    raise RuntimeError(f"Provider '{name}' returned an empty stream")
                await breaker.record_success()
                self._update_health(name, True, (time.time() - started) * 1000)
                # Record token usage after stream completes
                full_output = "".join(chunks)
                self._record_usage(provider_name=name, model=model, messages=messages, output_text=full_output)
                logger.info("Provider '%s' succeeded for chat_stream", name)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await breaker.record_failure()
                last_error = exc
                self._update_health(name, False, (time.time() - started) * 1000)
                logger.warning("Provider '%s' failed for chat_stream: %s", name, exc)
                if emitted_output:
                    # The response has already reached the user. Never append
                    # a second provider's response to it.
                    raise

        raise last_error or RuntimeError("All providers failed for chat_stream")

    async def embed(
        self,
        texts: list[str],
        model: str,
        provider: str | None = None,
        **kwargs: Any,
    ) -> list[list[float]]:
        """Embed text through the same health-aware provider failover path.

        ``create_llm_client()`` can return this manager when multi-provider
        mode is enabled.  Without this method, semantic memory and code search
        fail with ``AttributeError`` even when a registered provider supports
        embeddings.
        """
        target = provider or self.get_best_provider()
        if target not in self.providers:
            raise RuntimeError(f"Provider '{target}' not registered")

        last_error: Exception | None = None
        names_to_try = [target] + [name for name in self.providers if name != target]
        for name in names_to_try:
            candidate = self.providers[name]
            if not hasattr(candidate, "embed"):
                continue

            breaker = get_breaker(name)
            if not await breaker.is_call_permitted():
                last_error = RuntimeError(f"Circuit breaker open for '{name}'")
                continue

            started = time.time()
            try:
                vectors = await candidate.embed(texts, model=model, **kwargs)
                if not isinstance(vectors, list) or len(vectors) != len(texts):
                    raise RuntimeError(
                        f"Provider '{name}' returned {len(vectors) if isinstance(vectors, list) else 'invalid'} "
                        f"embeddings for {len(texts)} inputs"
                    )
                await breaker.record_success()
                self._update_health(name, True, (time.time() - started) * 1000)
                return vectors
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await breaker.record_failure()
                last_error = exc
                self._update_health(name, False, (time.time() - started) * 1000)
                logger.warning("Provider '%s' failed for embed: %s", name, exc)

        raise last_error or RuntimeError("No registered provider supports embeddings")

    async def batch_complete(
        self,
        messages_list: list[list[dict[str, str]]],
        *,
        model: str | None = None,
        options: dict[str, Any] | None = None,
        provider: str | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """Run a batch while preserving the manager's provider resilience."""
        if not messages_list:
            return []
        if not model:
            raise ValueError("MultiLLMManager.batch_complete requires an explicit model")

        target = provider or self.get_best_provider()
        if target not in self.providers:
            raise RuntimeError(f"Provider '{target}' not registered")

        candidate = self.providers[target]
        if hasattr(candidate, "batch_complete"):
            try:
                return await candidate.batch_complete(
                    messages_list, model=model, options=options, **kwargs
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Provider '%s' failed for batch_complete: %s", target, exc)

        return list(
            await asyncio.gather(
                *(
                    self.chat_complete(
                        model=model,
                        messages=messages,
                        options=options,
                        provider=provider,
                        **kwargs,
                    )
                    for messages in messages_list
                )
            )
        )

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
            breaker = get_breaker(name)
            if not await breaker.is_call_permitted():
                raise RuntimeError(f"Circuit breaker open for '{name}'")
            started = time.time()
            try:
                result = await self.providers[name].chat_complete(
                    model=model, messages=messages, options=options, **kwargs
                )
                await breaker.record_success()
                latency = (time.time() - started) * 1000
                self._update_health(name, True, latency)
                return name, result
            except Exception:
                await breaker.record_failure()
                raise

        tasks = {asyncio.create_task(_call(name)): name for name in valid_providers}
        pending: set[asyncio.Task] = set(tasks.keys())
        last_error: Exception | None = None
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    _, result = task.result()
                    for t in pending:
                        t.cancel()
                    return result
                except Exception as exc:
                    last_error = exc
                    self._update_health(tasks[task], False, 0.0)
                    logger.warning("Parallel provider '%s' failed: %s", tasks[task], exc)

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
                breaker = get_breaker(name)
                if not await breaker.is_call_permitted():
                    raise RuntimeError(f"Circuit breaker open for '{name}'")
                result = await self.providers[name].chat_complete(
                    model=model, messages=messages, options=options, **kwargs
                )
                await breaker.record_success()
                results[name] = result
            except Exception as exc:
                logger.warning("Consensus provider '%s' failed: %s", name, exc)

        await asyncio.gather(*(_call(name) for name in valid_providers))
        if not results:
            raise RuntimeError("All consensus providers failed")

        counter = Counter(results.values())
        most_common, _ = counter.most_common(1)[0]
        return most_common

    def provider_status(self) -> dict[str, dict[str, Any]]:
        """Return status for all providers, including health info and circuit breaker state."""
        from backend.llm.circuit_breaker import all_breakers

        status: dict[str, dict[str, Any]] = {}
        breaker_snapshots = all_breakers()
        for name in self.providers:
            health = self.health_status.get(name, {})
            cb = breaker_snapshots.get(name, {})
            status[name] = {**health, "circuit_breaker": cb}
        return status

    # ── Usage tracking convenience ─────────────────────────────────

    def get_tracker(self) -> TokenTracker:
        """Return the managed TokenTracker instance."""
        return self._tracker

    def usage_snapshot(self, since: float = 0.0) -> UsageSnapshot:
        """Return a usage snapshot for a time window."""
        return self._tracker.snapshot(since=since)
