"""LLM Provider abstraction layer.

Supports multiple providers: Ollama, OpenAI-compatible (DeepSeek, Groq, etc.),
Anthropic, and Kimi.
"""

from backend.llm.factory import create_llm_client, create_multi_llm_manager
from backend.llm.kimi_provider import KimiProvider
from backend.llm.multi_llm_manager import MultiLLMManager
from backend.llm.ollama_provider import OllamaProvider
from backend.llm.openai_provider import OpenAIProvider

__all__ = [
    "create_llm_client",
    "create_multi_llm_manager",
    "MultiLLMManager",
    "OllamaProvider",
    "OpenAIProvider",
    "KimiProvider",
]
