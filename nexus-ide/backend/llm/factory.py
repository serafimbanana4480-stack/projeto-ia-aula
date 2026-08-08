"""LLM Provider factory.

Creates the appropriate provider instance based on the LLM_PROVIDER
environment variable or configuration.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from backend.config.settings import get_settings
from backend.llm.airllm_provider import AirLLMProvider
from backend.llm.dev_provider import DevProvider
from backend.llm.free_policy import ProviderUnavailableError
from backend.llm.multi_llm_manager import MultiLLMManager
from backend.llm.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)

RUNTIME_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "data" / "settings.json"


def _load_runtime_overrides() -> dict[str, str]:
    """Load user-configured settings written by the Settings REST endpoint.

    The backend reads ``.env`` at startup via Pydantic.  To allow hot-updating
    API keys without restarting the server, we also check ``data/settings.json``
    which is written by ``PUT /api/settings``.
    """
    if not RUNTIME_SETTINGS_PATH.exists():
        return {}
    try:
        with RUNTIME_SETTINGS_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {k: v for k, v in data.items() if isinstance(v, str) and v}
    except (OSError, json.JSONDecodeError):
        return {}


def _setting_value(settings: Any, overrides: dict[str, Any], name: str, default: Any = "") -> Any:
    """Resolve an explicit/runtime override before the startup settings value."""
    value = overrides.get(name)
    candidate = value if value not in (None, "") else getattr(settings, name, default)

    # Settings values ultimately come from Pydantic/environment or the JSON
    # settings file.  Reject accidental mock/object values here: they are
    # truthy, can be treated as API keys, and then fail much later while
    # building an HTTP Authorization header.
    if isinstance(candidate, (str, int, float, bool)) or candidate is None:
        return candidate
    return default


def _as_bool(value: Any, default: bool = False) -> bool:
    """Parse settings persisted by the UI, which are stored as strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value) if value in (0, 1) else default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return default
def _free_only_enabled(settings: Any, overrides: dict[str, Any]) -> bool:
    """Resolve the fail-closed runtime policy from settings/UI overrides."""
    import os

    configured = getattr(settings, "free_only", None)
    if not isinstance(configured, (bool, str, int, float)):
        configured = os.environ.get("NEXUS_FREE_ONLY", "true")
    value = _setting_value(settings, overrides, "free_only", configured)
    return _as_bool(value, True)

def _local_models_ready(value: Any) -> bool:
    if not isinstance(value, dict) or not _as_bool(value.get("enabled"), False):
        return False
    models = value.get("models", value.get("installed", []))
    return bool(models) and _as_bool(value.get("healthy", True), False)
def _usable_api_key(value: Any) -> str:
    """Return a real-looking API key, ignoring template placeholder values.

    ``.env.example`` values are sometimes copied into ``.env`` unchanged.
    Treating ``your-...-api-key-here`` as configured makes the provider win
    routing, then every request fails upstream before a healthy fallback gets
    a chance.
    """
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    lowered = candidate.lower()
    if not candidate or lowered.startswith("your-") or lowered in {
        "changeme",
        "replace-me",
        "replace_with_your_key",
        "xxx",
    }:
        return ""
    return candidate

class MockProvider:
    """Simulation provider; its text is never a real completed run."""

    simulation = True
    eligibility_reason = "deterministic simulation only"

    _last_usage: dict[str, int] = {}

    @property
    def last_usage(self) -> dict[str, int]:
        """Return usage from the most recent call."""
        return dict(self._last_usage)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate (~4 chars per token)."""
        return max(1, len(text) // 4)

    async def aclose(self) -> None:
        pass

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        result = (
            "The AI service is currently unavailable. "
            "Please check that Ollama is running with the required models, or configure a cloud provider like OpenAI or DeepSeek. "
            "You can set LLM_PROVIDER=openai and OPENAI_API_KEY=sk-... in your environment."
        )
        input_text = " ".join(m.get("content", "") for m in messages)
        self._last_usage = {
            "input_tokens": self._estimate_tokens(input_text),
            "output_tokens": self._estimate_tokens(result),
            "total_tokens": self._estimate_tokens(input_text) + self._estimate_tokens(result),
        }
        for word in result.split():
            yield word + " "

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        result = (
            "The AI service is currently unavailable. "
            "Please check that Ollama is running with the required models, or configure a cloud provider like OpenAI or DeepSeek. "
            "You can set LLM_PROVIDER=openai and OPENAI_API_KEY=sk-... in your environment."
        )
        input_text = " ".join(m.get("content", "") for m in messages)
        self._last_usage = {
            "input_tokens": self._estimate_tokens(input_text),
            "output_tokens": self._estimate_tokens(result),
            "total_tokens": self._estimate_tokens(input_text) + self._estimate_tokens(result),
        }
        return result

    async def batch_complete(
        self,
        messages_list: list[list[dict[str, str]]],
        *,
        model: str | None = None,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """Default sequential batch implementation.

        Providers can override this for true batching; the default is
        sequential and concurrency-safe (uses ``asyncio.gather``).
        """
        effective_model = model or "mock"
        return list(
            await asyncio.gather(
                *(self.chat_complete(effective_model, msgs, **kwargs) for msgs in messages_list)
            )
        )

    async def embed(
        self,
        texts: list[str],
        model: str,
        **kwargs: Any,
    ) -> list[list[float]]:
        return [self._hash_embed(text) for text in texts]

    async def health_check(self) -> bool:
        return True

    @staticmethod
    def _hash_embed(text: str, dim: int = 384) -> list[float]:
        import hashlib
        import math

        seed = hashlib.sha256(text.encode("utf-8")).digest()
        vec: list[float] = []
        round_num = 0
        while len(vec) < dim:
            block = hashlib.sha256(seed + round_num.to_bytes(4, "big")).digest()
            vec.extend(((b / 255.0) - 0.5) * 2.0 for b in block)
            round_num += 1
        vec = vec[:dim]
        norm = math.sqrt(sum(v * v for v in vec))
        return vec if norm == 0 else [v / norm for v in vec]


class ResilientLLMProvider:
    """Wraps a primary provider and a chain of fallbacks.

    Tries the primary first, then falls back through the chain.  The final
    fallback is always :class:`MockProvider` so the user sees a helpful
    message instead of a raw traceback.
    """

    def __init__(self, primary: Any, fallbacks: list[Any], *, free_only: bool = False) -> None:
        self.primary = primary
        self.fallbacks = fallbacks
        self.free_only = free_only

    async def aclose(self) -> None:
        await self.primary.aclose()
        for fb in self.fallbacks:
            if hasattr(fb, "aclose"):
                await fb.aclose()

    async def _try_providers(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Try providers without allowing simulation to claim real success."""
        for provider in [self.primary, *self.fallbacks]:
            if self.free_only and (
                getattr(provider, "simulation", False)
                or (
                    provider.__class__.__name__.lower().startswith("ollama")
                    and not getattr(provider, "_free_validated", False)
                )
            ):
                continue
            try:
                return await getattr(provider, method)(*args, **kwargs)
            except Exception as exc:
                logger.warning(
                    "Provider %s failed for %s: %s",
                    provider.__class__.__name__,
                    method,
                    exc,
                )
                continue
        raise ProviderUnavailableError(
            f"All providers failed for {method}",
            category="provider_unavailable",
        )

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        for provider in [self.primary, *self.fallbacks]:
            if self.free_only and (
                getattr(provider, "simulation", False)
                or (
                    provider.__class__.__name__.lower().startswith("ollama")
                    and not getattr(provider, "_free_validated", False)
                )
            ):
                continue
            emitted_output = False
            try:
                async for token in provider.chat_stream(model, messages, **kwargs):
                    if token:
                        emitted_output = True
                    yield token
                if not emitted_output:
                    raise RuntimeError(
                        f"Provider {provider.__class__.__name__} returned an empty stream"
                    )
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Provider %s failed for chat_stream: %s",
                    provider.__class__.__name__,
                    exc,
                )
                if emitted_output:
                    # The response has already been observed by the user. A
                    # fallback here would splice a second answer onto it and
                    # can repeat tool calls in a ReAct response.
                    raise
                continue
            finally:
                kwargs.pop("_stream_retry_attempt", None)
        raise ProviderUnavailableError(
            "All providers failed for chat_stream",
            category="provider_unavailable",
        )

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        return await self._try_providers("chat_complete", model, messages, **kwargs)

    async def batch_complete(
        self,
        messages_list: list[list[dict[str, str]]],
        *,
        model: str | None = None,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """Default sequential batch implementation.

        Providers can override this for true batching; the default is
        sequential and concurrency-safe (uses ``asyncio.gather``).  When the
        underlying provider exposes its own ``batch_complete`` we delegate
        to it; otherwise we call :meth:`chat_complete` once per message
        set through the resilient fallback chain.
        """
        for provider in [self.primary, *self.fallbacks]:
            if self.free_only and (
                getattr(provider, "simulation", False)
                or (
                    provider.__class__.__name__.lower().startswith("ollama")
                    and not getattr(provider, "_free_validated", False)
                )
            ):
                continue
            try:
                if hasattr(provider, "batch_complete"):
                    return await provider.batch_complete(
                        messages_list,
                        model=model,
                        options=options,
                        **kwargs,
                    )
                return list(
                    await asyncio.gather(
                        *(
                            provider.chat_complete(model or "", msgs, options=options, **kwargs)
                            for msgs in messages_list
                        )
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Provider %s failed for batch_complete: %s",
                    provider.__class__.__name__,
                    exc,
                )
        raise ProviderUnavailableError(
            "All providers failed for batch_complete",
            category="provider_unavailable",
        )

    async def embed(
        self,
        texts: list[str],
        model: str,
        **kwargs: Any,
    ) -> list[list[float]]:
        return await self._try_providers("embed", texts, model, **kwargs)

    async def health_check(self) -> bool:
        return await self._try_providers("health_check")


def _build_fallback_chain(
    settings: Any,
    overrides: dict[str, Any],
    *,
    primary_provider: str | None = None,
    primary_is_local: bool | None = None,
) -> list[Any]:
    """Build a policy-filtered list of fallback providers."""
    fallbacks: list[Any] = []
    free_only = _free_only_enabled(settings, overrides)
    if free_only:
        ollama_host = _setting_value(settings, overrides, "ollama_host", "")
        ollama_enabled = _as_bool(
            _setting_value(
                settings,
                overrides,
                "nexus_enable_ollama",
                getattr(settings, "nexus_enable_ollama", False),
            )
        )
        local_ready = _local_models_ready(overrides.get("local_models"))
        if local_ready and primary_provider == "ollama" and ollama_host:
            fallback_host = _setting_value(settings, overrides, "ollama_dashboard_host", "")
            if fallback_host and fallback_host != ollama_host:
                fallback = OllamaProvider(base_url=fallback_host)
                fallback._free_validated = True
                fallbacks.append(fallback)
        elif local_ready and ollama_enabled and ollama_host:
            fallback = OllamaProvider(base_url=ollama_host)
            fallback._free_validated = True
            fallbacks.append(fallback)
        return fallbacks

    if primary_provider is None and primary_is_local is not None:
        primary_provider = "ollama" if primary_is_local else None

    if primary_provider == "ollama":
        fallback_host = _setting_value(settings, overrides, "ollama_dashboard_host", "")
        primary_host = _setting_value(settings, overrides, "ollama_host", "")
        if fallback_host and fallback_host != primary_host:
            fallbacks.append(OllamaProvider(base_url=fallback_host))
            logger.info("Added Ollama fallback host %s to fallback chain", fallback_host)

    ollama_host = _setting_value(settings, overrides, "ollama_host", "")
    if primary_provider == "airllm" and ollama_host:
        fallbacks.append(OllamaProvider(base_url=ollama_host))
        logger.info("Added Ollama fallback host %s to AirLLM chain", ollama_host)

    if openai_api_key := _setting_value(settings, overrides, "openai_api_key", ""):
        from backend.llm.openai_provider import OpenAIProvider

        fallbacks.append(
            OpenAIProvider(
                base_url=_setting_value(settings, overrides, "openai_base_url", "https://api.openai.com/v1"),
                api_key=openai_api_key,
            )
        )

    if kimi_api_key := _setting_value(settings, overrides, "kimi_api_key", ""):
        from backend.llm.kimi_provider import KimiProvider

        fallbacks.append(
            KimiProvider(
                base_url=_setting_value(settings, overrides, "kimi_base_url", "https://api.moonshot.cn/v1"),
                api_key=kimi_api_key,
            )
        )

    if deepseek_api_key := _setting_value(settings, overrides, "deepseek_api_key", ""):
        from backend.llm.openai_provider import OpenAIProvider

        fallbacks.append(
            OpenAIProvider(
                base_url=_setting_value(settings, overrides, "deepseek_base_url", "https://api.deepseek.com/v1"),
                api_key=deepseek_api_key,
            )
        )

    if groq_api_key := _setting_value(settings, overrides, "groq_api_key", ""):
        from backend.llm.openai_provider import OpenAIProvider

        fallbacks.append(
            OpenAIProvider(
                base_url=_setting_value(settings, overrides, "groq_base_url", "https://api.groq.com/openai/v1"),
                api_key=groq_api_key,
            )
        )

    if anthropic_api_key := _setting_value(settings, overrides, "anthropic_api_key", ""):
        from backend.llm.anthropic_provider import AnthropicProvider

        fallbacks.append(
            AnthropicProvider(
                base_url=_setting_value(settings, overrides, "anthropic_base_url", "https://api.anthropic.com"),
                api_key=anthropic_api_key,
            )
        )

    if gemini_api_key := _setting_value(settings, overrides, "gemini_api_key", ""):
        from backend.llm.gemini_provider import GeminiProvider

        fallbacks.append(
            GeminiProvider(
                base_url=_setting_value(
                    settings,
                    overrides,
                    "gemini_base_url",
                    "https://generativelanguage.googleapis.com/v1beta",
                ),
                api_key=gemini_api_key,
            )
        )

    if openrouter_api_key := _setting_value(settings, overrides, "openrouter_api_key", ""):
        from backend.llm.openrouter_provider import OpenRouterProvider

        fallbacks.append(
            OpenRouterProvider(
                base_url=_setting_value(settings, overrides, "openrouter_base_url", "https://openrouter.ai/api"),
                api_key=openrouter_api_key,
            )
        )

    # A local host is already the primary in the Ollama path and is explicitly
    # added above for AirLLM.  Do not append it to unrelated cloud chains:
    # silently changing a cloud request into a local answer is surprising, and
    # adding the same host twice only repeats a failing request.

    # Add DevProvider for zero-cost local development before the ultimate mock fallback
    has_any_real_provider = bool(
        openai_api_key
        or kimi_api_key
        or deepseek_api_key
        or groq_api_key
        or gemini_api_key
        or openrouter_api_key
    )
    if not has_any_real_provider:
        fallbacks.append(DevProvider())

    # Always add mock provider as ultimate fallback
    fallbacks.append(MockProvider())
    return fallbacks


def create_multi_llm_manager(*, overrides: dict[str, Any] | None = None) -> MultiLLMManager:
    """Create and configure a MultiLLMManager with all available providers.

    **OpenCode Go is the primary cloud provider.** Other cloud providers
    (OpenAI, Anthropic, Gemini, Kimi, etc.) are only registered when their
    API key is explicitly set. Ollama is only registered when
    ``NEXUS_ENABLE_OLLAMA=true`` is set (kept for backward compatibility and
    local development).
    """
    # Lazy imports to avoid loading unused provider classes at startup
    from backend.llm.kimi_provider import KimiProvider
    from backend.llm.openai_provider import OpenAIProvider

    settings = get_settings()
    # Settings written from the UI are strings and intentionally do not alter
    # process environment.  Merge them here as well as in direct-provider
    # mode, otherwise the default multi-provider path silently ignores a key
    # the user just saved.
    values: dict[str, Any] = {**_load_runtime_overrides(), **(overrides or {})}
    preferred_provider = str(
        _setting_value(
            settings,
            values,
            "llm_provider",
            _setting_value(settings, values, "default_provider", ""),
        )
    ).strip().lower()

    def priority_for(name: str, default: int) -> int:
        return 0 if name == preferred_provider else default

    free_only = _free_only_enabled(settings, values)
    policy_candidates = values.get("policy_candidates")
    if not isinstance(policy_candidates, list):
        from backend.llm.model_catalog import load_validated_models
        policy_candidates = load_validated_models("openrouter")
    local_models = values.get("local_models")
    validation_ttl = _setting_value(
        settings, values, "provider_validation_ttl_seconds", 600
    )
    max_latency = _setting_value(settings, values, "max_provider_latency_ms", 30_000)
    manager = MultiLLMManager(
        free_only=free_only,
        policy_candidates=policy_candidates if isinstance(policy_candidates, list) else [],
        local_models=local_models,
        validation_ttl_seconds=int(validation_ttl),
        max_latency_ms=int(max_latency),
    )

    # ------------------------------------------------------------------
    # PRIMARY: OpenCode Go (only registered when its API key is set)
    # ------------------------------------------------------------------
    from backend.llm.opencode_go_provider import OpenCodeGoProvider

    opencode_go_api_key = _usable_api_key(
        _setting_value(settings, values, "opencode_go_api_key", "")
    )
    if not free_only and opencode_go_api_key:
        manager.register_provider(
            "opencode_go",
            OpenCodeGoProvider(
                base_url=_setting_value(
                    settings, values, "opencode_go_base_url", "https://opencode.ai/zen/go/v1"
                ),
                api_key=opencode_go_api_key,
            ),
            priority=priority_for("opencode_go", 1),
        )

    # ------------------------------------------------------------------
    # OPTIONAL: Local Ollama (only if NEXUS_ENABLE_OLLAMA=true)
    # ------------------------------------------------------------------
    ollama_enabled = _as_bool(
        _setting_value(
            settings,
            values,
            "nexus_enable_ollama",
            getattr(settings, "nexus_enable_ollama", os.environ.get("NEXUS_ENABLE_OLLAMA", "")),
        )
    ) 
    if ollama_enabled and _local_models_ready(values.get("local_models")):
        ollama_provider = OllamaProvider(base_url=_setting_value(settings, values, "ollama_host", ""))
        manager.register_provider("ollama", ollama_provider, priority=priority_for("ollama", 4))
        manager.register_provider("local", ollama_provider, priority=priority_for("local", 4))
        logger.info("Ollama provider registered")

    # ------------------------------------------------------------------
    # OPTIONAL: AirLLM experimental (only if explicitly enabled)
    # ------------------------------------------------------------------
    if not free_only and _as_bool(
        _setting_value(settings, values, "airllm_experimental_enabled", False),
        bool(getattr(settings, "airllm_experimental_enabled", False)),
    ):
        manager.register_provider(
            "airllm",
            AirLLMProvider(
                device=_setting_value(settings, values, "local_llm_device", "auto"),
                compression=_setting_value(settings, values, "local_llm_compression", ""),
            ),
            priority=priority_for("airllm", 5),
        )

    # ------------------------------------------------------------------
    # OPTIONAL: Other cloud providers (only if API key is set)
    # ------------------------------------------------------------------
    if not free_only and (openai_api_key := _usable_api_key(_setting_value(settings, values, "openai_api_key", ""))):
        manager.register_provider(
            "openai",
            OpenAIProvider(
                base_url=_setting_value(settings, values, "openai_base_url", "https://api.openai.com/v1"),
                api_key=openai_api_key,
            ),
            priority=priority_for("openai", 3),
        )

    if not free_only and (kimi_api_key := _usable_api_key(_setting_value(settings, values, "kimi_api_key", ""))):
        manager.register_provider(
            "kimi",
            KimiProvider(
                base_url=_setting_value(settings, values, "kimi_base_url", "https://api.moonshot.cn/v1"),
                api_key=kimi_api_key,
            ),
            priority=priority_for("kimi", 3),
        )

    if not free_only and (deepseek_api_key := _usable_api_key(_setting_value(settings, values, "deepseek_api_key", ""))):
        manager.register_provider(
            "deepseek",
            OpenAIProvider(
                base_url=_setting_value(settings, values, "deepseek_base_url", "https://api.deepseek.com/v1"),
                api_key=deepseek_api_key,
            ),
            priority=priority_for("deepseek", 3),
        )

    if not free_only and (groq_api_key := _usable_api_key(_setting_value(settings, values, "groq_api_key", ""))):
        manager.register_provider(
            "groq",
            OpenAIProvider(
                base_url=_setting_value(settings, values, "groq_base_url", "https://api.groq.com/openai/v1"),
                api_key=groq_api_key,
            ),
            priority=priority_for("groq", 3),
        )

    if not free_only and (anthropic_api_key := _usable_api_key(_setting_value(settings, values, "anthropic_api_key", ""))):
        from backend.llm.anthropic_provider import AnthropicProvider

        manager.register_provider(
            "anthropic",
            AnthropicProvider(
                base_url=_setting_value(settings, values, "anthropic_base_url", "https://api.anthropic.com"),
                api_key=anthropic_api_key,
            ),
            priority=priority_for("anthropic", 3),
        )

    if not free_only and (gemini_api_key := _usable_api_key(_setting_value(settings, values, "gemini_api_key", ""))):
        from backend.llm.gemini_provider import GeminiProvider

        manager.register_provider(
            "gemini",
            GeminiProvider(
                base_url=_setting_value(
                    settings, values, "gemini_base_url", "https://generativelanguage.googleapis.com/v1beta"
                ),
                api_key=gemini_api_key,
            ),
            priority=priority_for("gemini", 3),
        )
    if openrouter_api_key := _usable_api_key(_setting_value(settings, values, "openrouter_api_key", "")):
        from backend.llm.openrouter_provider import OpenRouterProvider

        manager.register_provider(
            "openrouter",
            OpenRouterProvider(
                base_url=_setting_value(
                    settings, values, "openrouter_base_url", "https://openrouter.ai/api"
                ),
                api_key=openrouter_api_key,
                free_only=free_only,
                catalog=policy_candidates if isinstance(policy_candidates, list) else None,
                validation_ttl_seconds=int(validation_ttl),
                max_latency_ms=int(max_latency),
            ),
            priority=priority_for("openrouter", 3),
        )

    if not manager.list_providers() if hasattr(manager, "list_providers") else not manager.providers:
        logger.error("No providers configured; add an API key or enable a local provider.")
    return manager


def create_llm_client(**overrides: Any) -> Any:
    """Create an LLM provider instance based on configuration.

    Reads ``llm_provider`` from settings (env var ``LLM_PROVIDER``).
    Supported providers: ``ollama``/``local``, ``airllm``, ``openai``, ``deepseek``, ``kimi``, ``groq``, ``anthropic``, ``gemini``, ``openrouter``, ``opencode_go``, ``dev``.

    If ``MULTI_LLM_ENABLED`` is true, returns a :class:`MultiLLMManager`
    configured with all available providers.

    When the primary provider is local and multi-LLM is disabled, returns a
    :class:`ResilientLLMProvider` that tries the configured local backend first,
    then falls back to any configured cloud providers and finally :class:`MockProvider`.

    Args:
        overrides: Optional keyword args to override settings (for testing).

    Returns:
        A provider instance with ``chat_stream()``, ``chat_complete()``, and ``embed()`` methods.
    """
    settings = get_settings()
    # Runtime overrides from data/settings.json (set via Settings UI)
    _runtime = _load_runtime_overrides()
    if _runtime:
        logger.info("Loaded %d runtime settings overrides", len(_runtime))
    effective_overrides: dict[str, Any] = {**_runtime, **overrides}
    if "policy_candidates" not in effective_overrides:
        from backend.llm.model_catalog import load_validated_models
        effective_overrides["policy_candidates"] = load_validated_models("openrouter")
    free_only = _free_only_enabled(settings, effective_overrides)
    multi_llm_enabled = _as_bool(
        _setting_value(settings, effective_overrides, "multi_llm_enabled", settings.multi_llm_enabled),
        bool(settings.multi_llm_enabled),
    )
    if multi_llm_enabled:
        logger.info("Multi-LLM manager enabled")
        return create_multi_llm_manager(overrides=effective_overrides)

    provider = (
        _setting_value(settings, effective_overrides, "llm_provider", settings.llm_provider)
        .lower()
        .strip()
    )

    if free_only and provider not in {"local", "ollama", "openrouter", "dev"}:
        raise ProviderUnavailableError(
            f"Configured provider '{provider}' is not validated free",
            category="eligibility",
            provider=provider,
        )
    if provider in ("local", "ollama"):
        if not _as_bool(_setting_value(settings, effective_overrides, "nexus_enable_ollama", False)):
            raise ProviderUnavailableError(
                "Ollama is disabled; enable NEXUS_ENABLE_OLLAMA explicitly",
                category="eligibility",
                provider="ollama",
            )
        base_url = _setting_value(settings, effective_overrides, "ollama_host", settings.ollama_host)
        logger.info("Using Ollama provider at %s with fallback chain", base_url)
        primary = OllamaProvider(base_url=base_url)
        primary._free_validated = _local_models_ready(effective_overrides.get("local_models"))
        fallbacks = _build_fallback_chain(
            settings,
            effective_overrides,
            primary_provider="ollama",
        )
        return ResilientLLMProvider(primary, fallbacks, free_only=free_only)

    if provider == "airllm":
        device = _setting_value(settings, effective_overrides, "local_llm_device", settings.local_llm_device)
        compression = _setting_value(
            settings, effective_overrides, "local_llm_compression", settings.local_llm_compression
        )
        logger.info(
            "Using AirLLM provider (device=%s, compression=%s) with fallback chain",
            device,
            compression,
        )
        primary = AirLLMProvider(device=device, compression=compression)
        fallbacks = _build_fallback_chain(
            settings,
            effective_overrides,
            primary_provider="airllm",
        )
        return ResilientLLMProvider(primary, fallbacks, free_only=free_only)

    if provider == "dev":
        if free_only:
            raise ProviderUnavailableError(
                "Dev provider is simulation-only and cannot complete a real run",
                category="simulation",
                provider="dev",
            )
        logger.info("Using DevProvider (zero-cost development mode)")
        return DevProvider()
    if provider == "openai":
        from backend.llm.openai_provider import OpenAIProvider

        api_key = (
            _setting_value(settings, effective_overrides, "openai_api_key", "")
        )
        if not api_key:
            logger.warning("OPENAI_API_KEY not set — requests will fail")
        logger.info("Using OpenAI provider")
        return OpenAIProvider(
            base_url=_setting_value(settings, effective_overrides, "openai_base_url", "https://api.openai.com/v1"),
            api_key=api_key,
        )

    if provider == "deepseek":
        from backend.llm.openai_provider import OpenAIProvider

        api_key = (
            _setting_value(settings, effective_overrides, "deepseek_api_key", "")
        )
        if not api_key:
            logger.warning("DEEPSEEK_API_KEY not set — requests will fail")
        logger.info("Using DeepSeek provider")
        return OpenAIProvider(
            base_url=_setting_value(settings, effective_overrides, "deepseek_base_url", "https://api.deepseek.com/v1"),
            api_key=api_key,
        )

    if provider == "kimi":
        from backend.llm.kimi_provider import KimiProvider

        api_key = (
            _setting_value(settings, effective_overrides, "kimi_api_key", "")
        )
        if not api_key:
            logger.warning("KIMI_API_KEY not set — requests will fail")
        logger.info("Using Kimi provider")
        return KimiProvider(
            base_url=_setting_value(settings, effective_overrides, "kimi_base_url", "https://api.moonshot.cn/v1"),
            api_key=api_key,
        )

    if provider == "groq":
        from backend.llm.openai_provider import OpenAIProvider

        api_key = (
            _setting_value(settings, effective_overrides, "groq_api_key", "")
        )
        if not api_key:
            logger.warning("GROQ_API_KEY not set — requests will fail")
        logger.info("Using Groq provider")
        return OpenAIProvider(
            base_url=_setting_value(settings, effective_overrides, "groq_base_url", "https://api.groq.com/openai/v1"),
            api_key=api_key,
        )

    if provider == "anthropic":
        from backend.llm.anthropic_provider import AnthropicProvider

        api_key = (
            _setting_value(settings, effective_overrides, "anthropic_api_key", "")
        )
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set — requests will fail")
        logger.info("Using Anthropic provider")
        return AnthropicProvider(
            base_url=_setting_value(settings, effective_overrides, "anthropic_base_url", "https://api.anthropic.com"),
            api_key=api_key,
        )

    if provider == "gemini":
        from backend.llm.gemini_provider import GeminiProvider

        api_key = (
            _setting_value(settings, effective_overrides, "gemini_api_key", "")
        )
        if not api_key:
            logger.warning("GEMINI_API_KEY not set — requests will fail")
        logger.info("Using Gemini provider")
        return GeminiProvider(
            base_url=_setting_value(
                settings,
                effective_overrides,
                "gemini_base_url",
                "https://generativelanguage.googleapis.com/v1beta",
            ),
            api_key=api_key,
        )

    if provider == "openrouter":
        from backend.llm.openrouter_provider import OpenRouterProvider

        api_key = _setting_value(settings, effective_overrides, "openrouter_api_key", "")
        if not api_key:
            logger.warning("OPENROUTER_API_KEY not set — requests will fail")
        logger.info("Using OpenRouter provider")
        primary = OpenRouterProvider(
            base_url=_setting_value(
                settings, effective_overrides, "openrouter_base_url", "https://openrouter.ai/api"
            ),
            api_key=api_key,
            free_only=free_only,
            catalog=effective_overrides.get("policy_candidates"),
            validation_ttl_seconds=int(
                _setting_value(settings, effective_overrides, "provider_validation_ttl_seconds", 600)
            ),
            max_latency_ms=int(
                _setting_value(settings, effective_overrides, "max_provider_latency_ms", 30_000)
            ),
        )
        fallbacks = _build_fallback_chain(
            settings, effective_overrides, primary_provider="openrouter"
        )
        return ResilientLLMProvider(primary, fallbacks, free_only=free_only)

    if provider == "opencode_go":
        from backend.llm.opencode_go_provider import OpenCodeGoProvider

        api_key = (
            _setting_value(settings, effective_overrides, "opencode_go_api_key", "")
        )
        if not api_key:
            logger.warning("OPENCODE_GO_API_KEY not set — requests will fail")
        logger.info("Using OpenCode Go provider at https://opencode.ai/zen/go/v1")
        return OpenCodeGoProvider(
            base_url=_setting_value(
                settings, effective_overrides, "opencode_go_base_url", "https://opencode.ai/zen/go/v1"
            ),
            api_key=api_key,
        )

    # Fallback to Ollama for unknown providers
    logger.warning("Unknown LLM provider '%s' — falling back to Ollama", provider)
    primary = OllamaProvider(
        base_url=_setting_value(settings, effective_overrides, "ollama_host", settings.ollama_host)
    )
    fallbacks = _build_fallback_chain(
        settings,
        effective_overrides,
        primary_provider="ollama",
    )
    return ResilientLLMProvider(primary, fallbacks, free_only=free_only)
