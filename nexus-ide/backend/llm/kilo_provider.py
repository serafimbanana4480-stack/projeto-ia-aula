"""Kilo AI Gateway provider.

Kilo exposes an OpenAI-compatible API under ``/api/gateway`` without the
usual ``/v1`` path segment.
"""

from __future__ import annotations

from backend.llm.openai_provider import OpenAIProvider


class KiloProvider(OpenAIProvider):
    """OpenAI-compatible client for the Kilo AI Gateway."""

    provider_name = "kilo"
    DEFAULT_BASE_URL = "https://api.kilo.ai/api/gateway"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
    ) -> None:
        super().__init__(base_url, api_key, api_prefix="")


__all__ = ["KiloProvider"]
