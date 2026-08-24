"""OpenAI-compatible provider for DeepSeek, Groq, OpenAI, etc.

Exposes usage data from the response via the internal ``_last_usage``
attribute (does not change the public API).
"""

from __future__ import annotations

import json
import logging
import ssl
from collections.abc import AsyncIterator
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _system_verify_context() -> ssl.SSLContext:
    """Build a TLS context that trusts operating-system certificates."""
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return ssl.create_default_context()


def _normalize_api_root(base_url: str) -> str:
    """Return an API root compatible with the provider's ``/v1/...`` paths.

    ``httpx`` appends a leading-slash request path to the configured base path.
    Passing the conventional ``https://api.example/v1`` base URL to a client
    that requests ``/v1/chat/completions`` therefore produced ``/v1/v1/...``.
    Keep endpoint paths centralised in this adapter and normalise the base to
    the root exactly once.
    """
    normalized = base_url.rstrip("/")
    return normalized[:-3] if normalized.endswith("/v1") else normalized


class OpenAIProvider:
    """Provider for OpenAI-compatible APIs (DeepSeek, Groq, OpenAI, etc.)."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        api_prefix: str = "/v1",
    ) -> None:
        self._base_url = _normalize_api_root(base_url)
        self._api_key = api_key
        self._api_prefix = "/" + api_prefix.strip("/") if api_prefix.strip("/") else ""
        self._client = self._new_client()
        # Internal — set after each successful chat_complete / chat_stream
        self._last_usage: dict[str, int] = {}

    def _api_path(self, path: str) -> str:
        suffix = path.lstrip("/")
        return f"{self._api_prefix}/{suffix}" if self._api_prefix else f"/{suffix}"

    def _new_client(self) -> httpx.AsyncClient:
        """Create the HTTP transport used by this provider."""
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                **({"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}),
                # OpenRouter uses these optional headers for attribution and
                # better provider routing. They are harmless for compatible
                # OpenAI endpoints.
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "NEXUS IDE",
            },
            # Free OpenRouter routes can spend time in a queue before the
            # first token. A short read timeout is indistinguishable from a
            # broken network in the UI.
            timeout=httpx.Timeout(connect=15.0, read=120.0, write=20.0, pool=20.0),
            verify=_system_verify_context(),
        )

    def _ensure_open(self) -> None:
        """Re-open the transport if a reload or hot-reload closed it."""
        if self._client.is_closed:
            logger.warning("Re-opening closed LLM HTTP client for %s", self._base_url)
            self._client = self._new_client()

    @property
    def last_usage(self) -> dict[str, int]:
        """Return the usage info from the most recent call.

        Returns a dict with ``input_tokens`` and ``output_tokens`` keys
        (or empty dict if none available).
        """
        return dict(self._last_usage)

    def _extract_usage(self, data: dict[str, Any]) -> dict[str, int]:
        """Extract token counts from an OpenAI-compatible response body."""
        usage = data.get("usage", {})
        return {
            "input_tokens": usage.get("prompt_tokens", 0) or 0,
            "output_tokens": usage.get("completion_tokens", 0) or 0,
            "total_tokens": usage.get("total_tokens", 0) or 0,
        }

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health_check(self, timeout: float = 5.0) -> bool:
        """Check the OpenAI-compatible models endpoint without raising."""
        try:
            self._ensure_open()
            response = await self._client.get(self._api_path("models"), timeout=timeout)
            return response.status_code == 200
        except Exception:
            return False

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream chat completion from OpenAI-compatible API."""
        self._ensure_open()
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            # An OpenAI-compatible provider does NOT send `usage` on a stream
            # unless it is asked to. Without this the session panel showed
            # "ENTRADA 0 / SAÍDA 0" forever while 380 tools had run (audit
            # 2026-08-16, P9d) and no cost or context-pressure signal existed.
            "stream_options": {"include_usage": True},
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
            # Native OpenAI-compatible function calling. When the agent supplies
            # a tool schema we forward it so the model returns structured
            # ``tool_calls`` instead of relying on the weaker prompt-injected
            # ``<tool_call>`` convention — which small/free models frequently
            # emit in an unparseable shape, starving the evidence gate.
            for key in ("tools", "tool_choice", "parallel_tool_calls"):
                if options.get(key):
                    payload[key] = options[key]

        self._last_usage = {}
        emitted_text = False
        # Accumulate streamed native tool-call fragments keyed by their index.
        # OpenAI streams ``function.name`` once and ``function.arguments`` in
        # arbitrary-sized chunks, so both are concatenated as they arrive.
        tool_calls_acc: dict[int, dict[str, str]] = {}
        async with self._client.stream("POST", self._api_path("chat/completions"), json=payload) as resp:
            if resp.status_code != 200:
                text = await resp.aread()
                raise RuntimeError(f"OpenAI API error {resp.status_code}: {text.decode()}")

            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if not isinstance(data, dict):
                            continue
                        if data.get("error"):
                            raise RuntimeError(f"OpenAI stream error: {data['error']}")
                        choices = data.get("choices", [])
                        if not choices or not isinstance(choices[0], dict):
                            usage = data.get("usage")
                            if usage:
                                self._last_usage = self._extract_usage(data)
                            continue
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            emitted_text = True
                            yield content
                        for frag in delta.get("tool_calls") or ():
                            if not isinstance(frag, dict):
                                continue
                            idx = frag.get("index", 0) or 0
                            slot = tool_calls_acc.setdefault(idx, {"name": "", "arguments": ""})
                            fn = frag.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]
                        # Try to extract usage from stream — some providers
                        # include it on the final chunk.
                        usage = data.get("usage")
                        if usage:
                            self._last_usage = self._extract_usage(data)
                    except (json.JSONDecodeError, IndexError, TypeError):
                        continue

        # Re-emit any native tool calls as the explicit ``<tool_call>`` wrapper
        # the agent loop already parses and enforces. This keeps a single,
        # audited execution path: whether the model used native function calling
        # or wrote the wrapper by hand, the same parser validates it.
        emitted_tool_call = False
        for _idx, slot in sorted(tool_calls_acc.items()):
            name = (slot.get("name") or "").strip()
            if not name:
                continue
            raw_args = (slot.get("arguments") or "").strip()
            try:
                parsed_args = json.loads(raw_args) if raw_args else {}
                if not isinstance(parsed_args, dict):
                    parsed_args = {}
            except json.JSONDecodeError:
                parsed_args = {}
            emitted_tool_call = True
            yield (
                "\n<tool_call>"
                + json.dumps({"name": name, "arguments": parsed_args})
                + "</tool_call>"
            )

        if not emitted_text and not emitted_tool_call:
            # A 200 response with no usable text used to look like a successful
            # empty reply.  Raising lets the orchestration layer select a
            # healthy fallback before anything is visible to the user.
            raise RuntimeError("OpenAI stream completed without text content")

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Non-streaming chat completion."""
        self._ensure_open()
        payload: dict[str, Any] = {
            "model": model,
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

        resp = await self._client.post(self._api_path("chat/completions"), json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text}")

        data = resp.json()
        self._last_usage = self._extract_usage(data)
        message = data["choices"][0]["message"]
        content = message.get("content") or ""
        # Fold any native tool calls back into the ``<tool_call>`` wrapper so the
        # agent loop's single parser handles both native and prompt-based calls.
        rendered: list[str] = []
        for call in message.get("tool_calls") or ():
            fn = (call or {}).get("function") or {}
            name = (fn.get("name") or "").strip()
            if not name:
                continue
            try:
                parsed_args = json.loads(fn.get("arguments") or "{}")
                if not isinstance(parsed_args, dict):
                    parsed_args = {}
            except json.JSONDecodeError:
                parsed_args = {}
            rendered.append(
                "<tool_call>"
                + json.dumps({"name": name, "arguments": parsed_args})
                + "</tool_call>"
            )
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
        self._ensure_open()
        resp = await self._client.post(
            self._api_path("embeddings"),
            json={"model": model, "input": texts},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text}")

        data = resp.json()
        return [item["embedding"] for item in data["data"]]
