"""LLM Provider factory.

Creates the appropriate provider instance based on the LLM_PROVIDER
environment variable or configuration.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.config.settings import get_settings
from backend.llm.kimi_provider import KimiProvider
from backend.llm.multi_llm_manager import MultiLLMManager
from backend.llm.ollama_provider import OllamaProvider
from backend.llm.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


def create_multi_llm_manager() -> MultiLLMManager:
    """Create and configure a MultiLLMManager with all available providers."""
    settings = get_settings()
    manager = MultiLLMManager()

    manager.register_provider(
        "ollama",
        OllamaProvider(base_url=settings.ollama_host),
        priority=1,
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
    Supported providers: ``ollama``, ``openai``, ``deepseek``, ``kimi``, ``groq``.

    If ``MULTI_LLM_ENABLED`` is true, returns a :class:`MultiLLMManager`
    configured with all available providers.

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

    if provider == "ollama":
        host = overrides.get("ollama_host", settings.ollama_host)
        logger.info("Using Ollama provider at %s", host)
        return OllamaProvider(base_url=host)

    if provider == "openai":
        api_key = overrides.get("openai_api_key", settings.openai_api_key)
        if not api_key:
            logger.warning("OPENAI_API_KEY not set — requests will fail")
        logger.info("Using OpenAI provider")
        return OpenAIProvider(
            base_url=overrides.get("openai_base_url", "https://api.openai.com/v1"),
            api_key=api_key,
        )

    if provider == "deepseek":
        api_key = overrides.get("deepseek_api_key", settings.deepseek_api_key)
        if not api_key:
            logger.warning("DEEPSEEK_API_KEY not set — requests will fail")
        logger.info("Using DeepSeek provider")
        return OpenAIProvider(
            base_url=overrides.get("deepseek_base_url", "https://api.deepseek.com/v1"),
            api_key=api_key,
        )

    if provider == "kimi":
        api_key = overrides.get("kimi_api_key", settings.kimi_api_key)
        if not api_key:
            logger.warning("KIMI_API_KEY not set — requests will fail")
        logger.info("Using Kimi provider")
        return KimiProvider(
            base_url=overrides.get("kimi_base_url", "https://api.moonshot.cn/v1"),
            api_key=api_key,
        )

    if provider == "groq":
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
    return OllamaProvider(base_url=settings.ollama_host)
