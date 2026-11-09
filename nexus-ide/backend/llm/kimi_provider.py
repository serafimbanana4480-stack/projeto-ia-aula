"""Kimi (Moonshot AI) provider.

Kimi's API is OpenAI-compatible (base_url = https://api.moonshot.cn/v1).
This provider uses httpx directly with retry logic and Kimi-specific model
defaults.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from backend.config.settings import get_settings
from backend.llm.openai_provider import (
    ProviderHTTPStatusError,
    _system_verify_context,
    retry_delay,
)
from backend.llm.tool_calls import render_tool_call
from backend.runtime.reasoning import REASONING_SINK_OPTION, deliver_reasoning

logger = logging.getLogger(__name__)


class KimiProvider:
    """Provider for Kimi (Moonshot AI) API."""

    # Kimi model aliases → actual API model names
    MODEL_ALIASES: dict[str, str] = {
        "moonshot-v1-8k": "moonshot-v1-8k",
        "moonshot-v1-32k": "moonshot-v1-32k",
        "moonshot-v1-128k": "moonshot-v1-128k",
        "kimi-k1": "kimi-k1",
        "kimi-k1.5": "kimi-k1.5",
        "kimi-k2": "kimi-k2",
        "kimi-k2.5": "kimi-k2.5",
        "kimi-light": "kimi-k2-light",
        "kimi-mini": "kimi-k2-mini",
        "kimi-embedding": "kimi-embedding-v1",
    }

    def __init__(
        self,
        base_url: str = "https://api.moonshot.cn/v1",
        api_key: str | None = None,
    ) -> None:
        if api_key is None:
            api_key = get_settings().kimi_api_key
        # All Kimi endpoints used below are relative to the API v1 root.  Keep
        # both user-friendly host-only overrides and the documented ``.../v1``
        # URL valid without producing a ``/v1/v1/...`` request path.
        self._base_url = base_url.rstrip("/")
        if not self._base_url.endswith("/v1"):
            self._base_url = f"{self._base_url}/v1"
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=httpx.Timeout(10.0, connect=10.0, read=60.0, write=10.0),
            verify=_system_verify_context(),
        )
        # Internal — set after each successful chat call
        self._last_usage: dict[str, int] = {}
        # The provider's own stop reason ("stop", "length", "tool_calls").
        # The runtime reads it to detect a token-limit truncation.
        self.last_finish_reason: str = ""

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def last_usage(self) -> dict[str, int]:
        """Return usage from the most recent call."""
        return dict(self._last_usage)

    def resolve_model(self, model: str) -> str:
        """Resolve a model alias to the actual Kimi model name."""
        return self.MODEL_ALIASES.get(model, model)

    @staticmethod
    def _extract_usage(data: Any) -> dict[str, int]:
        """Extract token counts from an OpenAI-compatible Kimi response."""
        if not isinstance(data, dict):
            return {}
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return {}
        details = usage.get("completion_tokens_details")
        reasoning = 0
        if isinstance(details, dict):
            for key in ("reasoning_tokens", "reasoning"):
                value = details.get(key)
                if isinstance(value, int | float) and value > 0:
                    reasoning = int(value)
                    break
        extracted = {
            "input_tokens": usage.get("prompt_tokens", 0) or 0,
            "output_tokens": usage.get("completion_tokens", 0) or 0,
            "total_tokens": usage.get("total_tokens", 0) or 0,
        }
        if reasoning:
            extracted["reasoning_tokens"] = reasoning
        return extracted

    async def _post_with_retry(
        self,
        path: str,
        json_payload: dict[str, Any],
        max_retries: int = 3,
    ) -> httpx.Response:
        """POST with exponential backoff retry for transient errors.

        A provider that answers with ``Retry-After`` knows when it will be
        available again; honouring it beats a fixed backoff that hammers an
        endpoint which explicitly asked for a pause.
        """
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = await self._client.post(path, json=json_payload)
                if resp.status_code < 500:
                    return resp
                last_exc = ProviderHTTPStatusError(
                    resp.status_code,
                    resp.text,
                    label="Kimi API",
                    headers=getattr(resp, "headers", None),
                )
                wait = retry_delay(resp, attempt)
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                last_exc = exc
                wait = 2 ** (attempt - 1)
            if attempt < max_retries:
                logger.warning(
                    "Kimi request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt,
                    max_retries,
                    wait,
                    last_exc,
                )
                await asyncio.sleep(wait)
        raise last_exc or RuntimeError("Kimi request failed after retries")

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream chat completion from Kimi API."""
        self._last_usage = {}
        self.last_finish_reason = ""
        payload: dict[str, Any] = {
            "model": self.resolve_model(model),
            "messages": messages,
            "stream": True,
        }
        if options:
            for key in (
                "temperature",
                "max_tokens",
                "top_p",
                "frequency_penalty",
                "presence_penalty",
            ):
                if key in options:
                    payload[key] = options[key]
            # Native function calling: Kimi is OpenAI-compatible, so the
            # neutral tool schema is forwarded as-is.
            for key in ("tools", "tool_choice", "parallel_tool_calls"):
                if options.get(key):
                    payload[key] = options[key]

        max_retries = 3
        last_exc: Exception | None = None
        emitted_output = False
        emitted_tool_call = False
        # Native tool-call fragments, keyed by their stream index.
        tool_calls_acc: dict[int, dict[str, str]] = {}
        for attempt in range(1, max_retries + 1):
            try:
                async with self._client.stream(
                    "POST", "/chat/completions", json=payload
                ) as resp:
                    if resp.status_code != 200:
                        text = await resp.aread()
                        if resp.status_code >= 500 and attempt < max_retries:
                            wait = retry_delay(resp, attempt)
                            logger.warning(
                                "Kimi stream error %d (attempt %d/%d), retrying in %.1fs",
                                resp.status_code,
                                attempt,
                                max_retries,
                                wait,
                            )
                            await asyncio.sleep(wait)
                            continue
                        raise ProviderHTTPStatusError(
                            resp.status_code,
                            text.decode(),
                            label="Kimi API",
                            headers=getattr(resp, "headers", None),
                        )
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        if line in ("data: [DONE]", "data:[DONE]"):
                            break
                        # The SSE spec allows ``data:`` with or without the
                        # space after the colon.
                        if not line.startswith("data:"):
                            continue
                        try:
                            data = json.loads(line[5:].lstrip())
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(data, dict):
                            continue
                        choices = data.get("choices", [])
                        choice = (
                            choices[0] if choices and isinstance(choices[0], dict) else {}
                        )
                        finish_reason = choice.get("finish_reason")
                        if finish_reason:
                            self.last_finish_reason = str(finish_reason).strip().lower()
                        usage = data.get("usage")
                        if usage:
                            self._last_usage.update(self._extract_usage(data))
                        # ``delta.reasoning_content`` is Kimi's own approach
                        # text; it belongs in the reasoning panel and never in
                        # the answer.
                        parsed = deliver_reasoning(
                            (options or {}).get(REASONING_SINK_OPTION), "openai", data
                        )
                        if parsed.usage:
                            self._last_usage.update(parsed.usage)
                        content = parsed.content
                        if content:
                            emitted_output = True
                            yield content
                        for frag in parsed.tool_calls:
                            if not isinstance(frag, dict):
                                continue
                            idx = frag.get("index", 0) or 0
                            slot = tool_calls_acc.setdefault(
                                idx, {"name": "", "arguments": ""}
                            )
                            fn = frag.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]
                # The stream ended without an error: fold Kimi's native tool
                # calls back into the explicit ``<tool_call>`` wrapper the
                # agent loop parses and enforces.
                for _idx, slot in sorted(tool_calls_acc.items()):
                    name = (slot.get("name") or "").strip()
                    if not name:
                        continue
                    emitted_tool_call = True
                    yield "\n" + render_tool_call(name, slot.get("arguments") or "")
                if emitted_output or emitted_tool_call:
                    return
                # A successful HTTP response without emitted assistant
                # text must not be reported as a blank successful answer.
                raise RuntimeError("Kimi stream completed without text content")
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                # Once text is visible to the user, restarting would append a
                # second response to an already-partial answer.
                if emitted_output:
                    raise
                last_exc = exc
                if attempt < max_retries:
                    wait = 2 ** (attempt - 1)
                    logger.warning(
                        "Kimi stream network error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt,
                        max_retries,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)
        if last_exc:
            raise last_exc
        raise RuntimeError("Kimi stream failed after retries")

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Non-streaming chat completion."""
        self.last_finish_reason = ""
        payload: dict[str, Any] = {
            "model": self.resolve_model(model),
            "messages": messages,
            "stream": False,
        }
        if options:
            for key in ("temperature", "max_tokens", "top_p"):
                if key in options:
                    payload[key] = options[key]
            for key in ("tools", "tool_choice", "parallel_tool_calls"):
                if options.get(key):
                    payload[key] = options[key]

        resp = await self._post_with_retry("/chat/completions", payload)
        if resp.status_code != 200:
            raise ProviderHTTPStatusError(
                resp.status_code,
                resp.text,
                label="Kimi API",
                headers=getattr(resp, "headers", None),
            )

        data = resp.json()
        self._last_usage = self._extract_usage(data)
        choices = data.get("choices") or []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        finish_reason = choice.get("finish_reason")
        if finish_reason:
            self.last_finish_reason = str(finish_reason).strip().lower()
        message = choice.get("message") or {}
        content = message.get("content") or ""
        rendered: list[str] = []
        for call in message.get("tool_calls") or ():
            fn = (call or {}).get("function") or {}
            name = (fn.get("name") or "").strip()
            if not name:
                continue
            rendered.append(render_tool_call(name, fn.get("arguments")))
        if rendered:
            content = (content + "\n" + "\n".join(rendered)).strip()
        return content

    async def embed(
        self,
        texts: list[str],
        model: str,
        **kwargs: Any,
    ) -> list[list[float]]:
        """Get embeddings for texts."""
        payload = {"model": self.resolve_model(model), "input": texts}
        resp = await self._post_with_retry("/embeddings", payload)
        if resp.status_code != 200:
            raise ProviderHTTPStatusError(
                resp.status_code,
                resp.text,
                label="Kimi API",
                headers=getattr(resp, "headers", None),
            )

        data = resp.json()
        return [item["embedding"] for item in data["data"]]
