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
from backend.llm.free_policy import (
    FreeModelPolicy,
    FreeModelRequirement,
    ProviderUnavailableError,
)
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
    def __init__(
        self,
        *,
        free_only: bool = False,
        policy_candidates: list[Any] | None = None,
        local_models: Any = None,
        validation_ttl_seconds: int = 600,
        max_latency_ms: int | None = 30_000,
        requirement: FreeModelRequirement | None = None,
    ) -> None:
        self.providers: dict[str, Any] = {}
        self.health_status: dict[str, dict[str, Any]] = {}
        self._priority: dict[str, int] = {}
        self._tracker = get_token_tracker()
        self.free_only = free_only
        self.policy_candidates = policy_candidates or []
        self.local_models = local_models
        self.policy = FreeModelPolicy(validation_ttl_seconds=validation_ttl_seconds)
        self.requirement = requirement or FreeModelRequirement(max_latency_ms=max_latency_ms)
        self._selected_provider: str | None = None

        self._selected_model: str | None = None
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
            raise ProviderUnavailableError(
                "No providers registered",
                category="provider_unavailable",
            )
        def score(item: tuple[str, dict[str, Any]]) -> float:
            name, info = item
            p = self._priority.get(name, 1)
            lat = info.get("latency", 999999.0)
            sr = info.get("success_rate", 0.0)
            return p * 1000 + lat + (1 - sr) * 10000

        best, _ = min(candidates, key=score)
        return best

    def _ensure_dispatch_allowed(self, name: str, model: str) -> None:
        provider = self.providers[name]
        if getattr(provider, "simulation", False):
            raise ProviderUnavailableError(
                f"Provider '{name}' is simulation-only; no real completion was produced",
                category="simulation",
                provider=name,
                model=model,
            )
        if not self.free_only:
            return
        validator = getattr(provider, "validate_model", None)
        if callable(validator):
            validator(model)
            return
        if name == self._selected_provider:
            return
        if name.lower() in {"ollama", "local"} or getattr(provider, "free", False) is True:
            return
        raise ProviderUnavailableError(
            f"Provider '{name}' has no validated free model for '{model}'",
            category="eligibility",
            provider=name,
            model=model,
        )

    @staticmethod
    def _typed_provider_error(
        exc: BaseException, provider: str, model: str
    ) -> ProviderUnavailableError:
        if isinstance(exc, ProviderUnavailableError):
            return exc
        text = str(exc).lower()
        category = "provider_unavailable"
        if "quota" in text or "rate limit" in text or "429" in text:
            category = "quota"
        elif "timeout" in text:
            category = "timeout"
        return ProviderUnavailableError(
            str(exc) or exc.__class__.__name__,
            category=category,
            provider=provider,
            model=model,
            retry_after=getattr(exc, "retry_after", None),
        )

    def _attempt_names(self, target: str) -> list[str]:
        seen: set[int] = set()
        names: list[str] = []
        for name in [target, *self.providers]:
            if name not in self.providers:
                continue
            identity = id(self.providers[name])
            if identity in seen:
                continue
            seen.add(identity)
            names.append(name)
        return names

    def _select_policy_model(self, model: str) -> str:
        if not self.free_only:
            return model
        candidates = list(self.policy_candidates)
        for name, provider in self.providers.items():
            catalog = getattr(provider, "_catalog", None)
            if isinstance(catalog, dict):
                catalog = catalog.get("models", catalog.get("data", []))
            if catalog:
                candidates.extend(catalog)
        local_models = self.local_models
        if local_models is None:
            ollama = self.providers.get("ollama") or self.providers.get("local")
            if ollama is not None:
                local_models = getattr(ollama, "local_models", None)
        selection = self.policy.select(
            self.requirement,
            candidates,
            {name: get_breaker(name) for name in self.providers},
            local_models,
        )
        if selection is None:
            raise ProviderUnavailableError(
                "No validated free provider satisfies the request",
                category="eligibility",
                model=model,
            )
        self._selected_provider = selection.provider
        self._selected_model = selection.model
        return selection.model
    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
        provider: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Send a completion through validated, health-aware providers."""
        model = self._select_policy_model(model)
        target = provider or self._selected_provider or self.get_best_provider()
        if target not in self.providers:
            raise ProviderUnavailableError(
                f"Provider '{target}' not registered",
                category="provider_unavailable",
                provider=target,
                model=model,
            )
        last_error: ProviderUnavailableError | None = None
        names_to_try = self._attempt_names(target)
        for name in names_to_try:
            breaker = get_breaker(name)
            if not await breaker.is_call_permitted():
                last_error = ProviderUnavailableError(
                    f"Circuit breaker open for '{name}'",
                    category="breaker_open",
                    provider=name,
                    model=model,
                    retry_after=breaker.retry_after,
                )
                continue
            try:
                self._ensure_dispatch_allowed(name, model)
            except ProviderUnavailableError as exc:
                last_error = exc
                continue
            started = time.time()
            try:
                result = await self.providers[name].chat_complete(
                    model=model, messages=messages, options=options, **kwargs
                )
                if getattr(self.providers[name], "simulation", False):
                    raise ProviderUnavailableError(
                        "Simulation output cannot complete a real run",
                        category="simulation",
                        provider=name,
                        model=model,
                    )
                await breaker.record_success()
                self._update_health(name, True, (time.time() - started) * 1000)
                self._record_usage(
                    provider_name=name, model=model, messages=messages, output_text=result
                )
                logger.info("Provider '%s' succeeded for chat_complete", name)
                return result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await breaker.record_failure()
                last_error = self._typed_provider_error(exc, name, model)
                self._update_health(name, False, (time.time() - started) * 1000)
                logger.warning("Provider '%s' failed for chat_complete: %s", name, exc)
        raise last_error or ProviderUnavailableError(
            "All providers failed for chat_complete",
            category="provider_unavailable",
            model=model,
        )

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
        provider: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        model = self._select_policy_model(model)
        target = provider or self._selected_provider or self.get_best_provider()
        if target not in self.providers:
            raise ProviderUnavailableError(
                f"Provider '{target}' not registered",
                category="provider_unavailable",
                provider=target,
                model=model,
            )
        last_error: ProviderUnavailableError | None = None
        for name in self._attempt_names(target):
            breaker = get_breaker(name)
            if not await breaker.is_call_permitted():
                last_error = ProviderUnavailableError(
                    f"Circuit breaker open for '{name}'",
                    category="breaker_open",
                    provider=name,
                    model=model,
                    retry_after=breaker.retry_after,
                )
                continue
            try:
                self._ensure_dispatch_allowed(name, model)
            except ProviderUnavailableError as exc:
                last_error = exc
                continue
            started = time.time()
            emitted_output = False
            chunks: list[str] = []
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
                self._record_usage(
                    provider_name=name,
                    model=model,
                    messages=messages,
                    output_text="".join(chunks),
                )
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await breaker.record_failure()
                last_error = self._typed_provider_error(exc, name, model)
                self._update_health(name, False, (time.time() - started) * 1000)
                if emitted_output:
                    raise
        raise last_error or ProviderUnavailableError(
            "All providers failed for chat_stream",
            category="provider_unavailable",
            model=model,
        )

    async def embed(
        self,
        texts: list[str],
        model: str,
        provider: str | None = None,
        **kwargs: Any,
    ) -> list[list[float]]:
        model = self._select_policy_model(model)
        target = provider or self._selected_provider or self.get_best_provider()
        if target not in self.providers:
            raise ProviderUnavailableError(
                f"Provider '{target}' not registered",
                category="provider_unavailable",
                provider=target,
                model=model,
            )
        last_error: ProviderUnavailableError | None = None
        for name in self._attempt_names(target):
            candidate = self.providers[name]
            if not hasattr(candidate, "embed"):
                continue
            breaker = get_breaker(name)
            if not await breaker.is_call_permitted():
                last_error = ProviderUnavailableError(
                    f"Circuit breaker open for '{name}'",
                    category="breaker_open",
                    provider=name,
                    model=model,
                    retry_after=breaker.retry_after,
                )
                continue
            started = time.time()
            try:
                self._ensure_dispatch_allowed(name, model)
                vectors = await candidate.embed(texts, model=model, **kwargs)
                if not isinstance(vectors, list) or len(vectors) != len(texts):
                    raise RuntimeError("Provider returned invalid embeddings")
                await breaker.record_success()
                self._update_health(name, True, (time.time() - started) * 1000)
                return vectors
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await breaker.record_failure()
                last_error = self._typed_provider_error(exc, name, model)
                self._update_health(name, False, (time.time() - started) * 1000)
        raise last_error or ProviderUnavailableError(
            "No registered provider supports embeddings",
            category="provider_unavailable",
            model=model,
        )
    async def batch_complete(
        self,
        messages_list: list[list[dict[str, str]]],
        *,
        model: str | None = None,
        options: dict[str, Any] | None = None,
        provider: str | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if not messages_list:
            return []
        if not model:
            raise ValueError("MultiLLMManager.batch_complete requires an explicit model")
        model = self._select_policy_model(model)
        target = provider or self._selected_provider or self.get_best_provider()
        if target not in self.providers:
            raise ProviderUnavailableError(
                f"Provider '{target}' not registered",
                category="provider_unavailable",
                provider=target,
                model=model,
            )
        self._ensure_dispatch_allowed(target, model)
        candidate = self.providers[target]
        breaker = get_breaker(target)
        if not await breaker.is_call_permitted():
            raise ProviderUnavailableError(
                f"Circuit breaker open for '{target}'",
                category="breaker_open",
                provider=target,
                model=model,
                retry_after=breaker.retry_after,
            )
        try:
            if hasattr(candidate, "batch_complete"):
                result = await candidate.batch_complete(
                    messages_list, model=model, options=options, **kwargs
                )
                if getattr(candidate, "simulation", False):
                    raise ProviderUnavailableError(
                        "Simulation output cannot complete a real run",
                        category="simulation",
                        provider=target,
                        model=model,
                    )
                return result
            return list(
                await asyncio.gather(
                    *(
                        self.chat_complete(
                            model=model, messages=messages, options=options, provider=target, **kwargs
                        )
                        for messages in messages_list
                    )
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await breaker.record_failure()
            raise self._typed_provider_error(exc, target, model) from exc

    async def parallel_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        providers: list[str],
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        model = self._select_policy_model(model)
        if self.free_only and self._selected_provider:
            providers = [self._selected_provider]
        valid_providers = self._attempt_names(providers[0]) if providers else []
        valid_providers = [name for name in valid_providers if name in providers]
        if not valid_providers:
            raise ProviderUnavailableError(
                "No valid providers for parallel completion",
                category="provider_unavailable",
                model=model,
            )

        async def _call(name: str) -> tuple[str, str]:
            self._ensure_dispatch_allowed(name, model)
            breaker = get_breaker(name)
            if not await breaker.is_call_permitted():
                raise ProviderUnavailableError(
                    f"Circuit breaker open for '{name}'",
                    category="breaker_open",
                    provider=name,
                    model=model,
                    retry_after=breaker.retry_after,
                )
            try:
                result = await self.providers[name].chat_complete(
                    model=model, messages=messages, options=options, **kwargs
                )
                if getattr(self.providers[name], "simulation", False):
                    raise ProviderUnavailableError(
                        "Simulation output cannot complete a real run",
                        category="simulation",
                        provider=name,
                        model=model,
                    )
                await breaker.record_success()
                return name, result
            except Exception as exc:
                await breaker.record_failure()
                raise self._typed_provider_error(exc, name, model) from exc

        tasks = {asyncio.create_task(_call(name)): name for name in valid_providers}
        pending: set[asyncio.Task] = set(tasks)
        last_error: ProviderUnavailableError | None = None
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    _, result = task.result()
                    for other in pending:
                        other.cancel()
                    return result
                except Exception as exc:
                    last_error = self._typed_provider_error(exc, tasks[task], model)
        raise last_error or ProviderUnavailableError(
            "All parallel providers failed",
            category="provider_unavailable",
            model=model,
        )

    async def consensus_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        providers: list[str],
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        model = self._select_policy_model(model)
        if self.free_only and self._selected_provider:
            providers = [self._selected_provider]
        valid_providers: list[str] = []
        seen: set[int] = set()
        for name in providers:
            if name not in self.providers or id(self.providers[name]) in seen:
                continue
            seen.add(id(self.providers[name]))
            valid_providers.append(name)
        if not valid_providers:
            raise ProviderUnavailableError(
                "No valid providers for consensus completion",
                category="provider_unavailable",
                model=model,
            )
        results: dict[str, str] = {}

        async def _call(name: str) -> None:
            try:
                self._ensure_dispatch_allowed(name, model)
                breaker = get_breaker(name)
                if not await breaker.is_call_permitted():
                    raise ProviderUnavailableError(
                        f"Circuit breaker open for '{name}'",
                        category="breaker_open",
                        provider=name,
                        model=model,
                        retry_after=breaker.retry_after,
                    )
                result = await self.providers[name].chat_complete(
                    model=model, messages=messages, options=options, **kwargs
                )
                if getattr(self.providers[name], "simulation", False):
                    raise ProviderUnavailableError(
                        "Simulation output cannot complete a real run",
                        category="simulation",
                        provider=name,
                        model=model,
                    )
                await breaker.record_success()
                results[name] = result
            except Exception as exc:
                logger.warning("Consensus provider '%s' failed: %s", name, exc)

        await asyncio.gather(*(_call(name) for name in valid_providers))
        if not results:
            raise ProviderUnavailableError(
                "All consensus providers failed",
                category="provider_unavailable",
                model=model,
            )
        return Counter(results.values()).most_common(1)[0][0]
    def provider_status(self) -> dict[str, dict[str, Any]]:
        """Return health, eligibility, quota and breaker state."""
        from backend.llm.circuit_breaker import all_breakers

        status: dict[str, dict[str, Any]] = {}
        breaker_snapshots = all_breakers()
        for name in self.providers:
            health = self.health_status.get(name, {})
            cb = breaker_snapshots.get(name, {})
            provider = self.providers[name]
            status[name] = {
                **health,
                "free_only": self.free_only,
                "simulation": bool(getattr(provider, "simulation", False)),
                "eligibility_reason": getattr(provider, "eligibility_reason", None),
                "quota_available": getattr(provider, "quota_available", None),
                "validation_timestamp": getattr(provider, "validated_at", None),
                "circuit_breaker": cb,
                "retry_after": cb.get("retry_after"),
            }
        return status

    # ── Usage tracking convenience ─────────────────────────────────

    def get_tracker(self) -> TokenTracker:
        """Return the managed TokenTracker instance."""
        return self._tracker

    def usage_snapshot(self, since: float = 0.0) -> UsageSnapshot:
        """Return a usage snapshot for a time window."""
        return self._tracker.snapshot(since=since)
