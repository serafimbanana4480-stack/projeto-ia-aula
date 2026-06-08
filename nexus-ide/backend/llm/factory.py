"""LLM Provider factory.

Creates the appropriate provider instance based on the LLM_PROVIDER
environment variable or configuration.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from backend.config.settings import get_settings
from backend.llm.airllm_provider import AirLLMProvider
from backend.llm.dev_provider import DevProvider
from backend.llm.multi_llm_manager import MultiLLMManager
from backend.llm.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)


class MockProvider:
    """Graceful degradation provider that returns helpful messages when all
    real providers are down.
    """

    async def aclose(self) -> None:
        pass

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        yield "The AI service is currently unavailable. "
        yield "Please check that Ollama is running with the required models, or configure a cloud provider like OpenAI or DeepSeek. "
        yield "You can set LLM_PROVIDER=openai and OPENAI_API_KEY=sk-... in your environment."

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        return (
            "The AI service is currently unavailable. "
            "Please check that Ollama is running with the required models, or configure a cloud provider like OpenAI or DeepSeek. "
            "You can set LLM_PROVIDER=openai and OPENAI_API_KEY=sk-... in your environment."
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

    def __init__(self, primary: Any, fallbacks: list[Any]) -> None:
        self.primary = primary
        self.fallbacks = fallbacks

    async def aclose(self) -> None:
        await self.primary.aclose()
        for fb in self.fallbacks:
            if hasattr(fb, "aclose"):
                await fb.aclose()

    async def _try_providers(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Try synchronous-style methods (chat_complete, embed, health_check)."""
        for provider in [self.primary, *self.fallbacks]:
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
        raise RuntimeError(f"All providers failed for {method}")

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        for provider in [self.primary, *self.fallbacks]:
            try:
                async for token in provider.chat_stream(model, messages, **kwargs):
                    yield token
                return
            except Exception as exc:
                logger.warning(
                    "Provider %s failed for chat_stream: %s",
                    provider.__class__.__name__,
                    exc,
                )
                continue
        raise RuntimeError("All providers failed for chat_stream")

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        return await self._try_providers("chat_complete", model, messages, **kwargs)

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
    """Build a list of fallback providers based on configured API keys."""
    fallbacks: list[Any] = []

    if primary_provider is None and primary_is_local is not None:
        primary_provider = "ollama" if primary_is_local else None

    if primary_provider == "ollama":
        fallback_host = overrides.get(
            "ollama_dashboard_host",
            getattr(settings, "ollama_dashboard_host", ""),
        )
        primary_host = overrides.get("ollama_host", getattr(settings, "ollama_host", ""))
        if fallback_host and fallback_host != primary_host:
            fallbacks.append(OllamaProvider(base_url=fallback_host))
            logger.info("Added Ollama fallback host %s to fallback chain", fallback_host)

    if primary_provider == "airllm" and getattr(settings, "ollama_host", ""):
        fallbacks.append(OllamaProvider(base_url=settings.ollama_host))
        logger.info("Added Ollama fallback host %s to AirLLM chain", settings.ollama_host)

    if settings.openai_api_key:
        from backend.llm.openai_provider import OpenAIProvider

        fallbacks.append(
            OpenAIProvider(
                base_url="https://api.openai.com/v1",
                api_key=settings.openai_api_key,
            )
        )

    if settings.kimi_api_key:
        from backend.llm.kimi_provider import KimiProvider

        fallbacks.append(
            KimiProvider(
                base_url="https://api.moonshot.cn/v1",
                api_key=settings.kimi_api_key,
            )
        )

    if settings.deepseek_api_key:
        from backend.llm.openai_provider import OpenAIProvider

        fallbacks.append(
            OpenAIProvider(
                base_url="https://api.deepseek.com/v1",
                api_key=settings.deepseek_api_key,
            )
        )

    if settings.groq_api_key:
        from backend.llm.openai_provider import OpenAIProvider

        fallbacks.append(
            OpenAIProvider(
                base_url="https://api.groq.com/openai/v1",
                api_key=settings.groq_api_key,
            )
        )

    # Add DevProvider for zero-cost local development before the ultimate mock fallback
    has_any_real_provider = bool(
        settings.openai_api_key
        or settings.kimi_api_key
        or settings.deepseek_api_key
        or settings.groq_api_key
    )
    if not has_any_real_provider:
        fallbacks.append(DevProvider())

    # Always add mock provider as ultimate fallback
    fallbacks.append(MockProvider())
    return fallbacks


def create_multi_llm_manager() -> MultiLLMManager:
    """Create and configure a MultiLLMManager with all available providers."""
    # Lazy imports to avoid loading unused provider classes at startup
    from backend.llm.kimi_provider import KimiProvider
    from backend.llm.openai_provider import OpenAIProvider

    settings = get_settings()
    manager = MultiLLMManager()

    ollama_provider = OllamaProvider(base_url=settings.ollama_host)
    manager.register_provider("ollama", ollama_provider, priority=1)
    manager.register_provider("local", ollama_provider, priority=1)

    if settings.airllm_experimental_enabled:
        manager.register_provider(
            "airllm",
            AirLLMProvider(
                device=settings.local_llm_device,
                compression=settings.local_llm_compression,
            ),
            priority=2,
        )

    if settings.openai_api_key:
        manager.register_provider(
            "openai",
            OpenAIProvider(
                base_url="https://api.openai.com/v1",
                api_key=settings.openai_api_key,
            ),
            priority=2,
        )

    if settings.kimi_api_key:
        manager.register_provider(
            "kimi",
            KimiProvider(
                base_url="https://api.moonshot.cn/v1",
                api_key=settings.kimi_api_key,
            ),
            priority=2,
        )

    if settings.deepseek_api_key:
        manager.register_provider(
            "deepseek",
            OpenAIProvider(
                base_url="https://api.deepseek.com/v1",
                api_key=settings.deepseek_api_key,
            ),
            priority=3,
        )

    if settings.groq_api_key:
        manager.register_provider(
            "groq",
            OpenAIProvider(
                base_url="https://api.groq.com/openai/v1",
                api_key=settings.groq_api_key,
            ),
            priority=3,
        )

    return manager


def create_llm_client(**overrides: Any) -> Any:
    """Create an LLM provider instance based on configuration.

    Reads ``llm_provider`` from settings (env var ``LLM_PROVIDER``).
    Supported providers: ``ollama``/``local``, ``airllm``, ``openai``, ``deepseek``, ``kimi``, ``groq``.

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

    if overrides.get("multi_llm_enabled", settings.multi_llm_enabled):
        logger.info("Multi-LLM manager enabled")
        return create_multi_llm_manager()

    provider = overrides.get("llm_provider", settings.llm_provider).lower().strip()

    if provider in ("local", "ollama"):
        base_url = overrides.get("ollama_host", settings.ollama_host)
        logger.info("Using Ollama provider at %s with fallback chain", base_url)
        primary = OllamaProvider(base_url=base_url)
        fallbacks = _build_fallback_chain(
            settings,
            overrides,
            primary_provider="ollama",
        )
        return ResilientLLMProvider(primary, fallbacks)

    if provider == "airllm":
        device = overrides.get("local_llm_device", settings.local_llm_device)
        compression = overrides.get("local_llm_compression", settings.local_llm_compression)
        logger.info(
            "Using AirLLM provider (device=%s, compression=%s) with fallback chain",
            device,
            compression,
        )
        primary = AirLLMProvider(device=device, compression=compression)
        fallbacks = _build_fallback_chain(
            settings,
            overrides,
            primary_provider="airllm",
        )
        return ResilientLLMProvider(primary, fallbacks)

    if provider == "dev":
        logger.info("Using DevProvider (zero-cost development mode)")
        return DevProvider()

    if provider == "openai":
        from backend.llm.openai_provider import OpenAIProvider

        api_key = overrides.get("openai_api_key", settings.openai_api_key)
        if not api_key:
            logger.warning("OPENAI_API_KEY not set — requests will fail")
        logger.info("Using OpenAI provider")
        return OpenAIProvider(
            base_url=overrides.get("openai_base_url", "https://api.openai.com/v1"),
            api_key=api_key,
        )

    if provider == "deepseek":
        from backend.llm.openai_provider import OpenAIProvider

        api_key = overrides.get("deepseek_api_key", settings.deepseek_api_key)
        if not api_key:
            logger.warning("DEEPSEEK_API_KEY not set — requests will fail")
        logger.info("Using DeepSeek provider")
        return OpenAIProvider(
            base_url=overrides.get("deepseek_base_url", "https://api.deepseek.com/v1"),
            api_key=api_key,
        )

    if provider == "kimi":
        from backend.llm.kimi_provider import KimiProvider

        api_key = overrides.get("kimi_api_key", settings.kimi_api_key)
        if not api_key:
            logger.warning("KIMI_API_KEY not set — requests will fail")
        logger.info("Using Kimi provider")
        return KimiProvider(
            base_url=overrides.get("kimi_base_url", "https://api.moonshot.cn/v1"),
            api_key=api_key,
        )

    if provider == "groq":
        from backend.llm.openai_provider import OpenAIProvider

        api_key = overrides.get("groq_api_key", settings.groq_api_key)
        if not api_key:
            logger.warning("GROQ_API_KEY not set — requests will fail")
        logger.info("Using Groq provider")
        return OpenAIProvider(
            base_url=overrides.get("groq_base_url", "https://api.groq.com/openai/v1"),
            api_key=api_key,
        )

    # Fallback to Ollama for unknown providers
    logger.warning("Unknown LLM provider '%s' — falling back to Ollama", provider)
    primary = OllamaProvider(base_url=overrides.get("ollama_host", settings.ollama_host))
    fallbacks = _build_fallback_chain(
        settings,
        overrides,
        primary_provider="ollama",
    )
    return ResilientLLMProvider(primary, fallbacks)
