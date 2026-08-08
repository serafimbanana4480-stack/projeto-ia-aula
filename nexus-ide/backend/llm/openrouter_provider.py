"""OpenRouter provider for the NEXUS IDE.

OpenRouter exposes a fully OpenAI-compatible chat completions API at
https://openrouter.ai/api/v1.  We reuse :class:`OpenAIProvider` under the
hood but expose it as a first-party provider so that ``models.yaml`` and the
Settings page can list it alongside the other backends.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from backend.llm.free_policy import FreeModelRequirement, ProviderUnavailableError
from backend.llm.openai_provider import OpenAIProvider
from backend.observability.advanced_logging import get_structured_logger
logger = logging.getLogger(__name__)

# All agents in one backend process share the same OpenRouter account quota,
# even when a specialist consultation creates another provider instance.
_quota_loop: asyncio.AbstractEventLoop | None = None
_quota_lock: asyncio.Lock | None = None
_quota_next_request_at = 0.0
_quota_cooldown_until = 0.0


def _process_quota_lock() -> asyncio.Lock:
    global _quota_loop, _quota_lock, _quota_next_request_at, _quota_cooldown_until
    loop = asyncio.get_running_loop()
    if _quota_lock is None or _quota_loop is not loop:
        _quota_loop = loop
        _quota_lock = asyncio.Lock()
        _quota_next_request_at = 0.0
        _quota_cooldown_until = 0.0
    return _quota_lock


class OpenRouterProvider:
    """Provider wrapping OpenRouter's OpenAI-compatible API.

    Model aliases resolve to OpenRouter ``provider/{provider_name}/{model_name}``
    strings used in the ``model`` field of the chat completions request.
    """

    DEFAULT_BASE_URL = "https://openrouter.ai/api"
    provider_name = "openrouter"

    MODEL_ALIASES: dict[str, str] = {
        "auto": "auto",
        # Popular models available through OpenRouter
        "openai/gpt-4o": "openai/gpt-4o",
        "openai/gpt-4o-mini": "openai/gpt-4o-mini",
        "anthropic/claude-3.5-sonnet": "anthropic/claude-3.5-sonnet",
        "anthropic/claude-3-opus": "anthropic/claude-3-opus",
        "google/gemini-2.0-flash": "google/gemini-2.0-flash-exp:free",
        "google/gemini-1.5-pro": "google/gemini-1.5-pro",
        "deepseek/deepseek-chat": "deepseek/deepseek-chat",
        "deepseek/deepseek-v4-flash": "deepseek/deepseek-v4-flash",
        "meta-llama/llama-4-maverick": "meta-llama/llama-4-maverick",
        "mistral/mistral-large": "mistral/mistral-large",
        # FREE OpenRouter model aliases for NEXUS' internal tiers. Keep these
        # IDs in one place so the router and the UI cannot drift apart.
        "deepseek-v4-pro": "nvidia/nemotron-3-super-120b-a12b:free",
        # These aliases are deliberately pinned to IDs present in the live
        # catalog. The former ``tencent/hy3:free`` and ``laguna-m.1`` targets
        # returned 404/"no endpoints" and caused the fallback cascade to look
        # like a stalled autonomous agent.
        "glm-5.2": "google/gemma-4-31b-it:free",
        "deepseek-v4-flash": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "kimi-k2.7-code": "poolside/laguna-s-2.1:free",
        "minimax-m3": "openai/gpt-oss-20b:free",
        "qwen3.7-max": "nvidia/nemotron-3-super-120b-a12b:free",
        "mimo-v2.5": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "mimo-v2-pro": "google/gemma-4-31b-it:free",
        # Direct IDs are accepted as well, which makes this provider safe to
        # use from the model directory without introducing a second mapping.
        "tencent/hy3:free": "google/gemma-4-31b-it:free",
        "nvidia/nemotron-3-super-120b-a12b:free": "nvidia/nemotron-3-super-120b-a12b:free",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "poolside/laguna-m.1:free": "poolside/laguna-s-2.1:free",
        "poolside/laguna-s-2.1:free": "poolside/laguna-s-2.1:free",
        "openai/gpt-oss-20b:free": "openai/gpt-oss-20b:free",
        "google/gemma-4-31b-it:free": "google/gemma-4-31b-it:free",
    }

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        *,
        free_only: bool = False,
        catalog: Any = None,
        validation_ttl_seconds: int = 600,
        max_latency_ms: int = 30_000,
        local_embed_host: str | None = None,
    ) -> None:
        # OpenRouter's canonical ``/api`` URL and legacy config values ending
        # in ``/api/v1`` without ever producing ``/v1/v1``.
        normalized_base_url = base_url.rstrip("/")
        if normalized_base_url.endswith("/v1"):
            normalized_base_url = normalized_base_url[:-3]
        self._base_url = normalized_base_url
        self._api_key = api_key
        self._client = OpenAIProvider(base_url=self._base_url, api_key=api_key)
        # The configured account currently uses OpenRouter's free pool, whose
        # account-wide limit is 20 requests/minute. Agent-level semaphores do
        # not protect that shared quota: five different agents could each be
        # "within limit" while collectively causing a 429 storm. Reserve one
        # provider-wide slot every ~3.1s (19.3/min), including fallbacks.
        self.free_only = free_only
        self.eligibility_reason = "not checked"
        self.quota_available = None
        self.validated_at = None
        self._validation_ttl_seconds = max(1, int(validation_ttl_seconds))
        self._max_latency_ms = float(max_latency_ms)
        self._catalog = catalog
        self._local_embed_host = (local_embed_host or "").rstrip("/")
        try:
            self._min_request_interval = min(
                5.0,
                max(0.0, float(os.environ.get("NEXUS_OPENROUTER_MIN_INTERVAL_SECONDS", "3.1"))),
            )
        except ValueError:
            self._min_request_interval = 3.1

    @staticmethod
    def _rate_limit_reset_delay(error: BaseException) -> float | None:
        """Extract OpenRouter's account reset timestamp from a 429 error."""
        match = re.search(
            r'X-RateLimit-Reset[\\"\']*\s*:\s*[\\"\']*(\d+(?:\.\d+)?)',
            str(error),
            re.IGNORECASE,
        )
        if not match:
            return None
        reset = float(match.group(1))
        if reset > 10_000_000_000:
            reset /= 1000.0
        return max(0.0, reset - time.time())

    async def _reserve_request_slot(self, max_wait_seconds: float | None = None) -> None:
        """Serialize dispatch starts and honour an observed account cooldown.

        A quota reset is not useful work for an interactive chat turn.  When a
        caller supplies a bounded dispatch budget, fail immediately instead of
        putting the request to sleep for the provider's cooldown window.
        """
        global _quota_next_request_at
        async with _process_quota_lock():
            now = time.monotonic()
            ready_at = max(_quota_next_request_at, _quota_cooldown_until)
            delay = max(0.0, ready_at - now)
            budget = min(
                5.0,
                max(0.0, max_wait_seconds if max_wait_seconds is not None else 5.0),
            )
            if delay > budget:
                raise ProviderUnavailableError(
                    "OpenRouter dispatch budget exceeded; refusing to queue an interactive request",
                    category="quota",
                    provider=self.provider_name,
                    retry_after=delay,
                )
            if delay:
                logger.info("OpenRouter quota guard waiting %.2fs before dispatch", delay)
                await asyncio.sleep(min(delay, budget))
                now = time.monotonic()
            _quota_next_request_at = now + self._min_request_interval

    def _observe_provider_error(self, error: BaseException) -> None:
        global _quota_cooldown_until
        delay = self._rate_limit_reset_delay(error)
        if delay is None:
            return
        _quota_cooldown_until = max(
            _quota_cooldown_until,
            time.monotonic() + min(delay + 0.5, 65.0),
        )
        self.quota_available = False
        logger.warning("OpenRouter account quota exhausted; cooldown %.2fs", delay)

    def validate_model(
        self, model: str, requirement: FreeModelRequirement | None = None
    ) -> str:
        resolved = self.resolve_model(model)
        router_alias = model == "openrouter/free" and resolved == model
        if not self.free_only:
            return resolved
        entries = self._catalog
        if isinstance(entries, dict):
            entries = entries.get("models", entries.get("data", []))
        now = time.time()
        for entry in entries or []:
            entry_id = getattr(entry, "id", None) or (
                entry.get("id") if isinstance(entry, dict) else None
            )
            entry_provider = getattr(entry, "provider", None) or (
                entry.get("provider") if isinstance(entry, dict) else None
            )
            if router_alias:
                if str(entry_id) != "openrouter/free":
                    continue
            elif str(entry_id) != str(resolved):
                continue
            if entry_provider != "openrouter":
                continue
            def field(name: str, default: Any = None) -> Any:
                value = getattr(entry, name, default)
                return entry.get(name, value) if isinstance(entry, dict) else value
            input_price = field("input_price_per_1m")
            output_price = field("output_price_per_1m")
            quota = field("quota_available")
            validated_at = field("validated_at")
            capabilities = field("capabilities", ()) or ()
            try:
                context_window = int(field("context_window", 0) or 0)
            except (TypeError, ValueError):
                continue
            caps = {str(cap).lower().replace("-", "_") for cap in capabilities}
            if isinstance(capabilities, str):
                caps = {capabilities.lower().replace("-", "_")}
            requirement_ok = (
                requirement is None
                or (
                    context_window >= requirement.min_context
                    and (
                        not requirement.tool_calling
                        or bool(caps & {"tools", "tool_calling", "function_calling"})
                    )
                    and (
                        not requirement.structured_output
                        or bool(caps & {"json", "json_schema", "structured_output", "structured"})
                    )
                )
            )
            latency = field("latency_ms")
            try:
                validated_value = float(validated_at)
                latency_value = float(latency)
            except (TypeError, ValueError):
                continue
            if (
                input_price == 0
                and output_price == 0
                and requirement_ok
                and quota is True
                and 0 <= now - validated_value <= self._validation_ttl_seconds
                and 0 <= latency_value <= self._max_latency_ms
            ):
                self.quota_available = True
                self.validated_at = validated_value
                self.eligibility_reason = "catalog confirmed zero prices, quota and freshness"
                return resolved
        self.quota_available = False
        self.eligibility_reason = "model lacks current zero-price/quota validation"
        raise ProviderUnavailableError(
            f"OpenRouter model '{model}' is not confirmed free and available",
            category="eligibility",
            provider=self.provider_name,
            model=model,
        )

    async def health_check(self, timeout: float = 5.0) -> bool:
        """Bounded live health probe; free-only also requires validated catalog."""
        if self.free_only:
            if not self._catalog:
                self.eligibility_reason = "no validated catalog"
                return False
            try:
                self.validate_model("openrouter/free")
            except ProviderUnavailableError:
                return False
        return await self._client.health_check(timeout=min(float(timeout), 5.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    def resolve_model(self, model: str) -> str:
        """Resolve an alias to its OpenRouter model identifier."""
        override = os.environ.get("NEXUS_OPENROUTER_TOOL_MODEL", "").strip()
        if override and model != "auto":
            return override
        return self.MODEL_ALIASES.get(model, model)

    async def chat_stream(self, model, messages, **kwargs):
        resolved = self.validate_model(model)
        dispatch_timeout = kwargs.pop("_nexus_dispatch_timeout", None)
        try:
            dispatch_timeout = float(dispatch_timeout) if dispatch_timeout is not None else None
        except (TypeError, ValueError):
            dispatch_timeout = None
        get_structured_logger().info(
            "LLM SDK dispatch",
            source="llm",
            extra={
                "event": "llm_sdk_dispatch",
                "provider": self.provider_name,
                "model": resolved,
            },
        )
        await self._reserve_request_slot(max_wait_seconds=dispatch_timeout)
        try:
            async for token in self._client.chat_stream(resolved, messages, **kwargs):
                yield token
        except Exception as exc:
            self._observe_provider_error(exc)
            raise

    async def chat_complete(self, model, messages, **kwargs):
        resolved = self.validate_model(model)
        dispatch_timeout = kwargs.pop("_nexus_dispatch_timeout", None)
        try:
            dispatch_timeout = float(dispatch_timeout) if dispatch_timeout is not None else None
        except (TypeError, ValueError):
            dispatch_timeout = None
        await self._reserve_request_slot(max_wait_seconds=dispatch_timeout)
        try:
            return await self._client.chat_complete(resolved, messages, **kwargs)
        except Exception as exc:
            self._observe_provider_error(exc)
            raise

    async def embed(self, texts, model, **kwargs):
        """Use an explicitly configured, bounded local embedding service."""
        from backend.tools.ollama_client import OllamaClient

        if not self._local_embed_host:
            raise ProviderUnavailableError(
                "Local embedding host is not configured",
                category="eligibility",
                provider="ollama",
                model=model,
            )
        ollama = OllamaClient(base_url=self._local_embed_host)
        try:
            if not await ollama.health_check(timeout=0.75):
                raise ConnectionError("Ollama embedding service is unavailable")
            return await ollama.embed(texts, model=model or "nomic-embed-text")
        except Exception as exc:
            if isinstance(exc, ProviderUnavailableError):
                raise
            raise ProviderUnavailableError(
                "Ollama embedding service is unavailable; no synthetic embedding was produced",
                category="provider_unavailable",
                provider="ollama",
                model=model,
            ) from exc
        finally:
            await ollama.aclose()
