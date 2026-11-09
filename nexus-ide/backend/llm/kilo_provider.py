"""Kilo AI Gateway provider.

Kilo exposes an OpenAI-compatible API under ``/api/gateway`` without the
usual ``/v1`` path segment.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal, InvalidOperation
from typing import Any

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


class KiloFreeModelUnavailable(ValueError):
    """The selected Kilo model cannot be verified as free."""


class AnonymousFreeKiloProvider(OpenAIProvider):
    """Free-only Kilo access, without account credentials or paid fallbacks."""

    provider_name = "kilo"

    def __init__(self) -> None:
        super().__init__("https://ai-gateway.kilo.ai/api", api_key=None, api_prefix="/v1")

    async def chat_stream(
        self, model: str, messages: list[dict[str, str]], **kwargs: Any
    ) -> AsyncIterator[str]:
        if not model.endswith(":free"):
            raise KiloFreeModelUnavailable("O modelo Kilo tem de ser explicitamente gratuito (:free).")
        response = await self._client.get(self._api_path("models"), timeout=15.0)
        response.raise_for_status()
        payload = response.json()
        entries = payload.get("data", []) if isinstance(payload, dict) else []
        entry = next((e for e in entries if isinstance(e, dict) and e.get("id") == model), None)
        pricing = entry.get("pricing", {}) if entry else {}
        if not isinstance(pricing, dict):
            pricing = {}
        try:
            free = all(Decimal(str(pricing[k])).is_finite() and Decimal(str(pricing[k])) == 0
                       for k in ("prompt", "completion"))
        except (KeyError, TypeError, InvalidOperation):
            free = False
        if not free:
            raise KiloFreeModelUnavailable(
                f"O modelo Kilo '{model}' não está disponível no catálogo gratuito atual. "
                "Escolhe outro modelo gratuito nas definições do bot."
            )
        async for token in super().chat_stream(model, messages, **kwargs):
            yield token


__all__ = ["KiloProvider", "AnonymousFreeKiloProvider"]
