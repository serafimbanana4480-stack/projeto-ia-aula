"""LLM Provider abstraction layer.

Supports multiple providers: Ollama (default local runtime), AirLLM
(experimental), OpenAI-compatible backends, and Kimi.
"""

from backend.llm.airllm_provider import (
    AirLLMProvider,
    ChatMessage,
    CircuitBreaker,
    CircuitState,
    LocalLLMConnectionError,
    LocalLLMError,
    LocalLLMModelError,
)
from backend.llm.anthropic_provider import AnthropicProvider
from backend.llm.dev_provider import DevProvider
from backend.llm.factory import (
    MockProvider,
    ResilientLLMProvider,
    create_llm_client,
    create_multi_llm_manager,
)
from backend.llm.gemini_provider import GeminiProvider
from backend.llm.kimi_provider import KimiProvider
from backend.llm.multi_llm_manager import MultiLLMManager
from backend.llm.ollama_provider import OllamaProvider
from backend.llm.openai_provider import OpenAIProvider
from backend.llm.openrouter_provider import OpenRouterProvider
from backend.tools.ollama_client import OllamaClient

__all__ = [
    "create_llm_client",
    "create_multi_llm_manager",
    "MockProvider",
    "MultiLLMManager",
    "AirLLMProvider",
    "OllamaProvider",
    "OllamaClient",
    "DevProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "OpenRouterProvider",
    "KimiProvider",
    "ResilientLLMProvider",
    "ChatMessage",
    "CircuitBreaker",
    "CircuitState",
    "LocalLLMError",
    "LocalLLMConnectionError",
    "LocalLLMModelError",
]
