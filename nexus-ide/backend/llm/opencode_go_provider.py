"""OpenCode Go provider for the NEXUS IDE.

OpenCode Go exposes a fully OpenAI-compatible chat completions API at
https://opencode.ai/zen/go/v1. This provider reuses the existing
:class:`OpenAIProvider` under the hood and adds the OpenCode Go specific
model list so the Settings UI and ``models.yaml`` can list all available
models.

Available models (as of 2026-06-19):
    minimax-m3, minimax-m2.7, minimax-m2.5
    kimi-k2.7-code, kimi-k2.6, kimi-k2.5
    glm-5.2, glm-5.1, glm-5
    deepseek-v4-pro, deepseek-v4-flash
    qwen3.7-max, qwen3.7-plus, qwen3.6-plus, qwen3.5-plus
    mimo-v2-pro, mimo-v2-omni, mimo-v2.5-pro, mimo-v2.5
    hy3-preview
"""

from __future__ import annotations

import logging

from backend.llm.openai_provider import OpenAIProvider, _system_verify_context
from backend.observability.advanced_logging import get_structured_logger

logger = logging.getLogger(__name__)


class OpenCodeGoProvider:
    """Provider wrapping the OpenCode Go OpenAI-compatible API.

    The base URL is ``https://opencode.ai/zen/go/v1``; requests are
    authenticated with a Bearer token (the ``OPENCODE_GO_API_KEY`` setting).
    """

    DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
    provider_name = "opencode_go"

    # Canonical list of models offered by OpenCode Go. The chat API
    # accepts the same identifiers in the ``model`` field of the request.
    MODELS: list[str] = [
        "minimax-m3",
        "minimax-m2.7",
        "minimax-m2.5",
        "kimi-k2.7-code",
        "kimi-k2.6",
        "kimi-k2.5",
        "glm-5.2",
        "glm-5.1",
        "glm-5",
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "qwen3.7-max",
        "qwen3.7-plus",
        "qwen3.6-plus",
        "qwen3.5-plus",
        "mimo-v2-pro",
        "mimo-v2-omni",
        "mimo-v2.5-pro",
        "mimo-v2.5",
        "hy3-preview",
    ]

    # Map NEXUS model IDs to the canonical OpenCode Go model names.
    # NEXUS uses ``provider/model`` aliases (e.g. ``deepseek/deepseek-v4-flash``)
    # from its models.yaml; OpenCode Go expects the bare model name.
    MODEL_ALIASES: dict[str, str] = {
        "deepseek/deepseek-v4-flash": "deepseek-v4-flash",
        "deepseek/deepseek-v4-pro": "deepseek-v4-pro",
        "deepseek/deepseek-chat": "minimax-m3",
        "openai/gpt-4o": "minimax-m3",
        "openai/gpt-4o-mini": "minimax-m3",
        "anthropic/claude-3.5-sonnet": "glm-5.2",
        "anthropic/claude-3-opus": "glm-5.2",
        "google/gemini-2.0-flash": "glm-5.2",
        "google/gemini-1.5-pro": "glm-5.2",
        "meta-llama/llama-4-maverick": "qwen3.7-max",
        "mistral/mistral-large": "qwen3.7-max",
        "auto": "minimax-m3",
    }

    DEFAULT_MODEL = "minimax-m3"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key=None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = OpenAIProvider(
            base_url=self._base_url,
            api_key=self._api_key,
        )
        logger.info("OpenCodeGoProvider initialised at %s", self._base_url)

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def last_usage(self) -> dict[str, int]:
        """Return usage from the most recent call (delegates to OpenAIProvider)."""
        return dict(getattr(self._client, "_last_usage", {}))

    def list_models(self) -> list[str]:
        """Return the catalog of models offered by OpenCode Go."""
        return list(self.MODELS)

    def resolve_model(self, model: str) -> str:
        """Resolve a NEXUS model alias to the canonical OpenCode Go name.

        Falls back to the default model if the alias is unknown.
        """
        if not model:
            return self.DEFAULT_MODEL
        if model in self.MODELS:
            return model
        return self.MODEL_ALIASES.get(model, self.DEFAULT_MODEL)

    async def chat_stream(
        self,
        model: str,
        messages: list[dict],
        *,
        options=None,
        **kwargs,
    ):
        """Stream chat completion tokens from OpenCode Go."""
        resolved = self.resolve_model(model)
        get_structured_logger().info(
            "LLM SDK dispatch",
            source="llm",
            extra={
                "event": "llm_sdk_dispatch",
                "provider": self.provider_name,
                "model": resolved,
            },
        )
        async for token in self._client.chat_stream(resolved, messages, options=options, **kwargs):
            yield token

    async def chat_complete(
        self,
        model: str,
        messages: list[dict],
        *,
        options=None,
        **kwargs,
    ) -> str:
        """Return a non-streaming chat completion from OpenCode Go."""
        resolved = self.resolve_model(model)
        return await self._client.chat_complete(resolved, messages, options=options, **kwargs)

    async def health_check(self) -> bool:
        """Hit the models endpoint to verify connectivity + auth."""
        try:
            import httpx

            headers = {"Authorization": "Bearer " + str(self._api_key)} if self._api_key else {}
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=5.0,
                verify=_system_verify_context(),
            ) as c:
                resp = await c.get("/models")
                return resp.status_code == 200
        except Exception as exc:  # pragma: no cover - best-effort
            logger.debug("OpenCode Go health check failed: %s", exc)
            return False
