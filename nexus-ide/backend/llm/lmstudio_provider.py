"""LM Studio provider — OpenAI-compatible local inference server.

LM Studio exposes a ``/v1/chat/completions`` endpoint compatible with the
OpenAI API contract.  This provider reuses :class:`OpenAIProvider` so
streaming, tool-call folding, and usage extraction all work without
duplication.  The only LM Studio-specific behaviour is:

* Default base URL ``http://localhost:1234/v1`` (Ollama uses 11434).
* Optional API key (LM Studio does not require one by default).
* ``provider_name`` set to ``"lmstudio"`` so the model catalog and factory
  can distinguish it from other OpenAI-compatible backends.
* Long read timeout (default 600s, env ``LMSTUDIO_READ_TIMEOUT``) — the
  server cold-loads the model from disk on the first prompt.
* Router-tier aliases (``micro``/``fast``/``coder``) resolved from the
  ``LMSTUDIO_*_MODEL`` settings, mirroring the AirLLM/Ollama registries.
* ``stream_options`` retry: a strict server that rejects the parameter is
  retried once without it, before any token reaches the user.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from backend.llm.openai_provider import OpenAIProvider, ProviderHTTPStatusError

logger = logging.getLogger(__name__)

DEFAULT_READ_TIMEOUT = 600.0
DEFAULT_MODEL = "lfm2.5-2.6b-heretic-abliterated"


def _lmstudio_defaults() -> dict[str, Any]:
    """Read ``LMSTUDIO_*`` settings without failing when settings are stubbed."""
    try:
        from backend.config.settings import get_settings

        settings = get_settings()
        return {
            "read_timeout": float(getattr(settings, "lmstudio_read_timeout", DEFAULT_READ_TIMEOUT)),
            "default_model": str(getattr(settings, "lmstudio_default_model", "") or ""),
            "fast_model": str(getattr(settings, "lmstudio_fast_model", "") or ""),
            "coder_model": str(getattr(settings, "lmstudio_coder_model", "") or ""),
        }
    except Exception:  # noqa: BLE001 - provider must work without a Settings object
        return {}


class LMStudioProvider(OpenAIProvider):
    """Provider for LM Studio local inference server.

    Inherits all streaming, completion, and embedding behaviour from
    :class:`OpenAIProvider`.  The constructor only overrides the LM Studio
    defaults.
    """

    provider_name: str = "lmstudio"

    DEFAULT_BASE_URL: str = "http://localhost:1234/v1"

    # Set to True by the factory once the local catalog confirms the models —
    # mirrors the Ollama ``_free_validated`` contract.
    _free_validated: bool = False
    _free_candidates: list[str] = []

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        *,
        read_timeout: float | None = None,
        send_stream_options: bool = True,
        default_model: str = "",
        fast_model: str = "",
        coder_model: str = "",
    ) -> None:
        defaults = _lmstudio_defaults()
        effective_read_timeout = (
            float(read_timeout)
            if read_timeout is not None
            else float(defaults.get("read_timeout") or DEFAULT_READ_TIMEOUT)
        )
        self._default_model = default_model or str(defaults.get("default_model") or DEFAULT_MODEL)
        self._fast_model = fast_model or str(defaults.get("fast_model") or self._default_model)
        self._coder_model = coder_model or str(defaults.get("coder_model") or self._default_model)
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            read_timeout=effective_read_timeout,
            send_stream_options=send_stream_options,
        )

    def resolve_model(self, model: str) -> str:
        """Map router tiers and aliases onto the configured LM Studio models.

        Concrete model ids (anything the LM Studio server exposes) are used
        verbatim, exactly like the Ollama/AirLLM registries handle them.
        """
        selector = (model or "").strip().lower()
        aliases = {
            "micro": self._default_model,
            "nano": self._default_model,
            "auto": self._default_model,
            "default": self._default_model,
            "medium": self._default_model,
            "reasoning": self._default_model,
            "fast": self._fast_model,
            "small": self._fast_model,
            "coder": self._coder_model,
        }
        return aliases.get(selector, selector or self._default_model)

    def validate_model(self, model: str, requirement: Any = None) -> str:
        """Accept any model id for local LM Studio inference.

        LM Studio exposes whatever models the user has loaded; there is no
        server-side catalog to query at startup, so we fail open here and
        let the API return 404 if the model id is wrong.
        """
        return model

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Non-streaming completion with tier resolution."""
        return await super().chat_complete(
            self.resolve_model(model), messages, options=options, **kwargs
        )

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Streaming completion with tier resolution and ``stream_options`` retry.

        Modern LM Studio builds accept ``stream_options.include_usage`` and
        answer with a usage chunk; older or stricter builds reject the whole
        request with HTTP 400. When that happens *before any token has been
        emitted*, retry once without the parameter so local chat still works
        (usage is simply unavailable for that turn).
        """
        resolved = self.resolve_model(model)
        emitted = False
        try:
            async for token in super().chat_stream(resolved, messages, options=options, **kwargs):
                emitted = True
                yield token
            return
        except (ProviderHTTPStatusError, RuntimeError) as exc:
            if emitted or "stream_options" not in str(exc).lower():
                raise
            self._send_stream_options = False
            logger.warning(
                "LM Studio rejected stream_options; retrying the stream without it"
            )
        async for token in super().chat_stream(resolved, messages, options=options, **kwargs):
            yield token


__all__ = ["LMStudioProvider"]
