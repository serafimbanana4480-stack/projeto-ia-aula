"""Anthropic Claude provider for NEXUS IDE.

Uses the Anthropic Messages API directly via httpx.  The provider is
OpenAI-compatible in the sense that it exposes the same ``chat_stream``,
``chat_complete`` and ``embed`` interface used by the rest of the system.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from backend.config.settings import get_settings
from backend.llm.openai_provider import ProviderHTTPStatusError, _system_verify_context
from backend.llm.tool_calls import (
    anthropic_tool_choice,
    openai_tools_to_anthropic,
    render_tool_call,
)
from backend.runtime.reasoning import (
    REASONING_REQUEST_OPTION,
    REASONING_SINK_OPTION,
    deliver_reasoning,
)

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """Provider for Anthropic's Claude API."""

    DEFAULT_BASE_URL = "https://api.anthropic.com"

    # Small set of aliases to help users that configure legacy model names.
    MODEL_ALIASES: dict[str, str] = {
        "claude-opus": "claude-3-opus-20240229",
        "claude-sonnet": "claude-3-5-sonnet-20241022",
        "claude-haiku": "claude-3-haiku-20240307",
        "claude-3-5-sonnet": "claude-3-5-sonnet-20241022",
    }

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        if api_key is None:
            api_key = get_settings().anthropic_api_key
        self._api_key = api_key
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        headers: dict[str, str] = {
            "x-api-key": api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0),
            verify=_system_verify_context(),
        )
        # Internal — populated after each successful chat call
        self._last_usage: dict[str, int] = {}
        # The provider's own stop reason ("end_turn", "max_tokens", "tool_use").
        # The runtime reads it to tell a normal stop from a token-limit
        # truncation, so it has to survive on the provider.
        self.last_finish_reason: str = ""

    async def aclose(self) -> None:
        await self._client.aclose()

    def resolve_model(self, model: str) -> str:
        """Resolve a model alias to the official Anthropic model name."""
        return self.MODEL_ALIASES.get(model, model)

    @property
    def last_usage(self) -> dict[str, int]:
        """Return usage from the most recent call."""
        return dict(self._last_usage)

    @staticmethod
    def _openai_to_anthropic_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """Normalize messages for the Anthropic Messages API.

        Anthropic only supports ``user`` and ``assistant`` roles and does not
        accept a leading ``system`` message in the ``messages`` array.  We move
        any system message to the dedicated ``system`` field.
        """
        system_texts: list[str] = []
        normalized: list[dict[str, str]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_texts.append(content)
                continue
            if role not in ("user", "assistant"):
                role = "user"
            normalized.append({"role": role, "content": content})
        system = "\n".join(system_texts) if system_texts else None
        return normalized, system

    def _extract_usage_from_message(self, data: dict[str, Any]) -> dict[str, int]:
        """Extract token counts from an Anthropic Messages API response.

        Extended thinking is billed as output tokens; some gateways also report
        it separately as ``thinking_tokens``. Both are surfaced so the session
        panel can attribute tokens to the reasoning pass.
        """
        usage = data.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        reasoning = 0
        for key in ("thinking_tokens", "reasoning_tokens"):
            value = usage.get(key)
            if isinstance(value, int | float) and value > 0:
                reasoning = int(value)
                break
        usage_out = {
            "input_tokens": usage.get("input_tokens", 0) or 0,
            "output_tokens": usage.get("output_tokens", 0) or 0,
            "total_tokens": (usage.get("input_tokens", 0) or 0)
            + (usage.get("output_tokens", 0) or 0),
        }
        if reasoning:
            # Additive only: a non-thinking turn keeps the historical shape.
            usage_out["reasoning_tokens"] = reasoning
        return usage_out

    def _merge_usage(self, usage: Any) -> None:
        """Merge one usage frame into the accumulated usage.

        A frame that does not carry a field must never reset it.  Anthropic
        reports ``input_tokens`` in ``message_start`` and ``output_tokens`` in
        ``message_delta``; overwriting the accumulated usage with the missing
        field's default of ``0`` erased the input tokens, so the request was
        never billed and the session panel showed ``ENTRADA 0``.
        """
        if not isinstance(usage, dict):
            return
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            self._last_usage[key] = int(value)
        for key in ("thinking_tokens", "reasoning_tokens"):
            value = usage.get(key)
            if isinstance(value, int | float) and value > 0:
                self._last_usage["reasoning_tokens"] = int(value)
                break
        if "total_tokens" not in usage:
            known = self._last_usage.get("input_tokens", 0) + self._last_usage.get(
                "output_tokens", 0
            )
            if known:
                self._last_usage["total_tokens"] = known

    @staticmethod
    def _tool_payload(options: dict[str, Any] | None) -> tuple[list[dict], dict | None]:
        """Translate the neutral tool options into Anthropic's own schema."""
        if not isinstance(options, dict):
            return [], None
        tools = options.get("tools")
        if not tools:
            return [], None
        converted = openai_tools_to_anthropic(tools)
        if not converted:
            return [], None
        return converted, anthropic_tool_choice(options.get("tool_choice"))

    @staticmethod
    def _thinking_payload(
        payload: dict[str, Any], options: dict[str, Any] | None
    ) -> bool:
        """Add the extended-thinking block when the caller asked for reasoning.

        Anthropic requires ``budget_tokens < max_tokens`` and rejects the whole
        request otherwise, so the budget is derived from the *resolved*
        ``max_tokens`` and the largest budget is never requested. Returns
        ``True`` when the block was added.
        """
        if not isinstance(options, dict):
            return False
        if not options.get(REASONING_REQUEST_OPTION) and not options.get(
            REASONING_SINK_OPTION
        ):
            return False
        try:
            max_tokens = int(payload.get("max_tokens") or 4096)
        except (TypeError, ValueError):
            max_tokens = 4096
        # Anthropic needs headroom above the budget for the actual answer.
        budget = min(2048, max(1024, max_tokens // 2))
        if budget >= max_tokens:
            return False
        payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
        # Extended thinking is incompatible with a non-default temperature.
        payload.pop("temperature", None)
        payload.pop("top_p", None)
        payload.pop("top_k", None)
        return True

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a chat completion from the Anthropic Messages API."""
        self._last_usage = {}
        self.last_finish_reason = ""
        normalized_messages, system = self._openai_to_anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": self.resolve_model(model),
            "messages": normalized_messages,
            "max_tokens": 4096,
            "stream": True,
        }
        if system:
            payload["system"] = system

        if options:
            if "temperature" in options:
                payload["temperature"] = options["temperature"]
            if "max_tokens" in options:
                payload["max_tokens"] = options["max_tokens"]
            if "top_p" in options:
                payload["top_p"] = options["top_p"]
            # Native tool calling: Anthropic speaks its own ``input_schema``
            # dialect, so the neutral OpenAI-style schema has to be translated
            # before it is sent.
            tools, tool_choice = self._tool_payload(options)
            if tools:
                payload["tools"] = tools
                if tool_choice:
                    payload["tool_choice"] = tool_choice
        self._thinking_payload(payload, options)

        emitted_text = False
        emitted_reasoning = False
        emitted_tool_call = False
        # Native tool-use blocks, keyed by the content-block index Anthropic
        # streams them under.
        tool_blocks: dict[int, dict[str, str]] = {}
        current_tool_index: int | None = None

        async with self._client.stream("POST", "/v1/messages", json=payload) as resp:
            if resp.status_code != 200:
                text = await resp.aread()
                raise ProviderHTTPStatusError(
                    resp.status_code,
                    text.decode(),
                    label="Anthropic API",
                    headers=getattr(resp, "headers", None),
                )

            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or line.startswith("event:"):
                    continue
                # The SSE spec allows ``data:`` with or without the space
                # after the colon; requiring the exact ``"data: "`` prefix
                # dropped legal frames.
                if not line.startswith("data:"):
                    continue
                data = line[5:].lstrip()
                if data == "[DONE]":
                    continue
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                # ``thinking_delta`` / ``signature_delta`` /
                # ``redacted_thinking`` are the extended-thinking channel.
                # They are parsed and routed to the caller's sink and are
                # NEVER yielded as answer text: the answer is whatever
                # ``text_delta`` carries.
                parsed = deliver_reasoning(
                    (options or {}).get(REASONING_SINK_OPTION), "anthropic", event
                )
                if parsed.usage:
                    self._last_usage.update(parsed.usage)
                if parsed.reasoning:
                    emitted_reasoning = True
                if parsed.content:
                    emitted_text = True
                    yield parsed.content
                event_type = event.get("type")
                if event_type == "content_block_start":
                    block = event.get("content_block")
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        try:
                            index = int(event.get("index") or 0)
                        except (TypeError, ValueError):
                            index = 0
                        current_tool_index = index
                        slot = tool_blocks.setdefault(index, {"name": "", "arguments": ""})
                        slot["name"] = str(block.get("name") or "")
                        initial = block.get("input")
                        if isinstance(initial, dict) and initial:
                            slot["arguments"] = json.dumps(initial)
                elif event_type == "content_block_delta":
                    delta = event.get("delta")
                    if (
                        isinstance(delta, dict)
                        and delta.get("type") == "input_json_delta"
                        and current_tool_index is not None
                    ):
                        slot = tool_blocks.setdefault(
                            current_tool_index, {"name": "", "arguments": ""}
                        )
                        slot["arguments"] += str(delta.get("partial_json") or "")
                elif event_type == "content_block_stop":
                    current_tool_index = None
                elif event_type == "message_delta":
                    # End-of-stream — ``usage`` here usually carries the final
                    # output tokens only.  It must MERGE with what
                    # ``message_start`` already reported, never replace it.
                    delta = event.get("delta")
                    if isinstance(delta, dict):
                        stop_reason = delta.get("stop_reason")
                        if stop_reason:
                            self.last_finish_reason = str(stop_reason).strip().lower()
                    self._merge_usage(event.get("usage"))
                elif event_type == "message_start":
                    msg = event.get("message")
                    if isinstance(msg, dict):
                        self._merge_usage(msg.get("usage"))

        # Fold Anthropic's native ``tool_use`` blocks back into the explicit
        # ``<tool_call>`` wrapper the agent loop parses and enforces, so a
        # native call and a hand-written wrapper share one execution path.
        for _index, slot in sorted(tool_blocks.items()):
            name = (slot.get("name") or "").strip()
            if not name:
                continue
            emitted_tool_call = True
            yield "\n" + render_tool_call(name, slot.get("arguments") or "")

        if not emitted_text and not emitted_tool_call:
            if emitted_reasoning:
                raise RuntimeError(
                    "Anthropic stream completed with reasoning but no text content"
                )
            raise RuntimeError("Anthropic stream completed without text content")

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Non-streaming chat completion from the Anthropic Messages API."""
        self.last_finish_reason = ""
        normalized_messages, system = self._openai_to_anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": self.resolve_model(model),
            "messages": normalized_messages,
            "max_tokens": 4096,
            "stream": False,
        }
        if system:
            payload["system"] = system

        if options:
            if "temperature" in options:
                payload["temperature"] = options["temperature"]
            if "max_tokens" in options:
                payload["max_tokens"] = options["max_tokens"]
            if "top_p" in options:
                payload["top_p"] = options["top_p"]
            tools, tool_choice = self._tool_payload(options)
            if tools:
                payload["tools"] = tools
                if tool_choice:
                    payload["tool_choice"] = tool_choice
        self._thinking_payload(payload, options)

        resp = await self._client.post("/v1/messages", json=payload)
        if resp.status_code != 200:
            raise ProviderHTTPStatusError(
                resp.status_code,
                resp.text,
                label="Anthropic API",
                headers=getattr(resp, "headers", None),
            )

        data = resp.json()
        self._last_usage = self._extract_usage_from_message(data)
        contents = data.get("content", [])
        text_parts: list[str] = []
        tool_calls: list[tuple[str, Any]] = []
        for block in contents:
            if not isinstance(block, dict):
                continue
            # ``thinking``/``redacted_thinking`` blocks are the reasoning
            # channel; a non-streaming call still has to route them somewhere
            # bounded instead of returning them as the answer.
            deliver_reasoning(
                (options or {}).get(REASONING_SINK_OPTION), "anthropic", block
            )
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(str(block.get("text") or ""))
            elif block_type == "tool_use":
                name = str(block.get("name") or "").strip()
                if name:
                    tool_calls.append((name, block.get("input") or {}))
        stop_reason = data.get("stop_reason")
        if stop_reason:
            self.last_finish_reason = str(stop_reason).strip().lower()
        answer = "".join(text_parts)
        for name, arguments in tool_calls:
            rendered = render_tool_call(name, arguments)
            answer = f"{answer}\n{rendered}".strip() if answer else rendered
        return answer

    async def embed(
        self,
        texts: list[str],
        model: str,
        **kwargs: Any,
    ) -> list[list[float]]:
        """Anthropic does not expose an embedding API.

        Raise a clear error so callers can fall back to another provider or
        to the deterministic mock embedding.
        """
        raise NotImplementedError(
            "Anthropic does not provide an embedding endpoint. "
            "Use Ollama embeddings or another provider for RAG."
        )

    async def health_check(self) -> bool:
        """Check API key validity by issuing a minimal request."""
        if not self._api_key:
            return False
        try:
            resp = await self._client.get("/v1/models", timeout=10.0)
            return resp.status_code == 200
        except Exception as exc:
            logger.debug("Anthropic health check failed: %s", exc)
            return False
