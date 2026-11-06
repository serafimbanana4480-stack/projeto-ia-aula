"""Gemini (Google AI) provider for NEXUS IDE.

Uses the Google Generative AI API via the Google AI Python SDK. The provider
exposes the same chat_stream, chat_complete and embed interface used by the
rest of the system.

Endpoint:
    POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}
    POST https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?key={api_key}
    POST https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent?key={api_key}

Python SDK alternative (used here):
    pip install google-generativeai
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
from backend.llm.tool_calls import (
    gemini_tool_config,
    openai_tools_to_gemini,
    render_tool_call,
)
from backend.runtime.reasoning import REASONING_SINK_OPTION, deliver_reasoning

logger = logging.getLogger(__name__)

# Defaults for the Google Generative AI API (as an OpenAI-compatible proxy also exists via Google)
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    """Provider for Google Gemini API (via REST v1beta)."""

    DEFAULT_BASE_URL = DEFAULT_BASE_URL

    # Model aliases → canonical API model names
    MODEL_ALIASES: dict[str, str] = {
        "gemini-2.0-flash": "gemini-2.0-flash",
        "gemini-2.0-flash-lite": "gemini-2.0-flash-lite",
        "gemini-2.5-flash": "gemini-2.5-flash",
        "gemini-2.5-pro": "gemini-2.5-pro",
        "gemini-1.5-pro": "gemini-1.5-pro",
        "gemini-1.5-flash": "gemini-1.5-flash",
        "gemini-1.5-flash-8b": "gemini-1.5-flash-8b",
        "gemini-embedding": "text-embedding-004",
        "gemini-embedding-001": "gemini-embedding-001",
    }

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
    ) -> None:
        if api_key is None:
            api_key = get_settings().gemini_api_key
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0),
            verify=_system_verify_context(),
        )
        # Internal — set after each successful chat call
        self._last_usage: dict[str, int] = {}
        # The provider's own stop reason ("STOP", "MAX_TOKENS", …). The runtime
        # reads it to detect a token-limit truncation.
        self.last_finish_reason: str = ""

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def last_usage(self) -> dict[str, int]:
        """Return usage from the most recent call."""
        return dict(self._last_usage)

    def resolve_model(self, model: str) -> str:
        """Resolve a model alias to the canonical Gemini model name."""
        return self.MODEL_ALIASES.get(model, model)

    def _key_param(self) -> dict[str, str]:
        return {"key": self._api_key} if self._api_key else {}

    def _convert_messages(self, messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Convert OpenAI-format messages to Gemini ``contents`` format.

        Maps: system → model instruction/bias, user → role=user, assistant → role=model.
        Gemini does not have a system role in contents; we fold the system message
        into the first user turn as a ``system_instruction`` field.
        """
        contents: list[dict[str, Any]] = []
        system_instruction: str | None = None
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_instruction = content
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})
            else:
                contents.append({"role": "user", "parts": [{"text": content}]})

        result: dict[str, Any] = {"contents": contents}
        if system_instruction:
            result["system_instruction"] = {"parts": [{"text": system_instruction}]}
        return result

    def _get_model_url(self, model: str, action: str) -> str:
        return f"/models/{model}:{action}"

    async def _post_with_retry(
        self,
        url: str,
        json_payload: dict[str, Any],
        max_retries: int = 3,
    ) -> httpx.Response:
        """POST with exponential backoff retry for transient errors.

        A provider that answers with ``Retry-After`` knows when it will be
        available again; honouring it is the difference between a polite
        backoff and hammering a struggling endpoint.
        """
        params = self._key_param()
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = await self._client.post(url, json=json_payload, params=params)
                if resp.status_code < 500:
                    return resp
                last_exc = ProviderHTTPStatusError(
                    resp.status_code,
                    resp.text,
                    label="Gemini API",
                    headers=getattr(resp, "headers", None),
                )
                wait = retry_delay(resp, attempt)
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                last_exc = exc
                wait = 2 ** (attempt - 1)
            if attempt < max_retries:
                logger.warning(
                    "Gemini request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt,
                    max_retries,
                    wait,
                    last_exc,
                )
                await asyncio.sleep(wait)
        raise last_exc or RuntimeError("Gemini request failed after retries")

    def _extract_usage_from_gemini(self, data: dict[str, Any]) -> dict[str, int]:
        """Extract token counts from a Gemini generateContent response.

        ``thoughtsTokenCount`` is the model's reasoning spend. It is only added
        to the result when the provider actually reported it, so a run without
        reasoning keeps exactly the dictionary shape callers already expect.
        """
        usage_meta = data.get("usageMetadata", {})
        if not isinstance(usage_meta, dict):
            usage_meta = {}
        usage = {
            "input_tokens": usage_meta.get("promptTokenCount", 0) or 0,
            "output_tokens": usage_meta.get("candidatesTokenCount", 0) or 0,
            "total_tokens": usage_meta.get("totalTokenCount", 0) or 0,
        }
        thoughts = usage_meta.get("thoughtsTokenCount", 0) or 0
        if thoughts:
            usage["reasoning_tokens"] = int(thoughts)
        return usage

    @staticmethod
    def _tool_payload(options: dict[str, Any] | None) -> tuple[list[dict], dict | None]:
        """Translate the neutral tool options into Gemini's own schema."""
        if not isinstance(options, dict):
            return [], None
        tools = options.get("tools")
        if not tools:
            return [], None
        converted = openai_tools_to_gemini(tools)
        if not converted:
            return [], None
        return converted, gemini_tool_config(options.get("tool_choice"))

    @staticmethod
    def _function_calls(chunk: dict[str, Any]) -> list[tuple[str, Any]]:
        """Return the native ``functionCall`` parts of one Gemini frame."""
        calls: list[tuple[str, Any]] = []
        candidates = chunk.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return calls
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            return calls
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            return calls
        for part in parts:
            if not isinstance(part, dict):
                continue
            call = part.get("functionCall") or part.get("function_call")
            if not isinstance(call, dict):
                continue
            name = str(call.get("name") or "").strip()
            if not name:
                continue
            calls.append((name, call.get("args") or call.get("arguments") or {}))
        return calls

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream chat completion from Gemini API."""
        self._last_usage = {}
        self.last_finish_reason = ""
        resolved = self.resolve_model(model)
        payload: dict[str, Any] = self._convert_messages(messages)
        # Gemini uses camelCase generationConfig fields.  Accept the common
        # OpenAI/Ollama option names too, since agents use one provider-neutral
        # options dictionary.
        gen_config = self._generation_config(options)
        if gen_config:
            payload["generationConfig"] = gen_config
        # Native function calling: Gemini speaks ``functionDeclarations``.
        tools, tool_config = self._tool_payload(options)
        if tools:
            payload["tools"] = tools
            if tool_config:
                payload["toolConfig"] = tool_config

        url = self._get_model_url(resolved, "streamGenerateContent")
        # Gemini only delivers incremental SSE frames when ``alt=sse`` is
        # requested.  Authentication uses the query key for this REST API.
        params = {**self._key_param(), "alt": "sse"}

        max_retries = 3
        last_exc: Exception | None = None
        emitted_text = False
        emitted_thinking = False
        tool_calls: list[tuple[str, Any]] = []
        for attempt in range(1, max_retries + 1):
            try:
                async with self._client.stream("POST", url, json=payload, params=params) as resp:
                    if resp.status_code != 200:
                        text = await resp.aread()
                        if resp.status_code >= 500 and attempt < max_retries:
                            wait = retry_delay(resp, attempt)
                            logger.warning(
                                "Gemini stream error %d (attempt %d/%d), retrying in %.1fs",
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
                            label="Gemini API",
                            headers=getattr(resp, "headers", None),
                        )

                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue

                        # REST streaming frames have the standard SSE ``data:``
                        # prefix.  The parser also accepts the older raw JSON
                        # array format for backwards-compatible proxies.
                        if line.startswith("data:"):
                            line = line[5:].lstrip()
                        if line in ("[DONE]", "[]"):
                            break

                        try:
                            decoded = json.loads(line)
                        except json.JSONDecodeError:
                            logger.debug(
                                "Skipping malformed Gemini stream frame: %s", line[:200]
                            )
                            continue

                        chunks = decoded if isinstance(decoded, list) else [decoded]
                        for chunk in chunks:
                            if not isinstance(chunk, dict):
                                continue
                            usage_gemini = chunk.get("usageMetadata", {})
                            if usage_gemini:
                                self._last_usage.update(
                                    self._extract_usage_from_gemini(chunk)
                                )
                            candidates = chunk.get("candidates", [])
                            if not candidates:
                                continue
                            candidate = candidates[0]
                            if isinstance(candidate, dict):
                                finish_reason = candidate.get("finishReason")
                                if finish_reason:
                                    self.last_finish_reason = (
                                        str(finish_reason).strip().lower()
                                    )
                            # Gemini's native function calls live in the same
                            # ``parts`` list as the text; they used to be
                            # dropped, so the ReAct loop could never execute a
                            # tool on this provider.
                            tool_calls.extend(self._function_calls(chunk))
                            # Gemini marks a thinking part with ``thought: true``
                            # and carries its answer in the remaining parts. The
                            # shared parser splits the two so a thought summary
                            # can never be concatenated into the answer.
                            parsed = deliver_reasoning(
                                (options or {}).get(REASONING_SINK_OPTION), "gemini", chunk
                            )
                            if parsed.reasoning:
                                emitted_thinking = True
                            text_piece = parsed.content
                            if text_piece:
                                emitted_text = True
                                yield text_piece

                    # Fold Gemini's native ``functionCall`` parts back into the
                    # explicit ``<tool_call>`` wrapper the agent loop parses.
                    for name, arguments in tool_calls:
                        yield "\n" + render_tool_call(name, arguments)
                    if emitted_text or tool_calls:
                        return
                    # A successful HTTP status with no parsed content used to
                    # look like a successful blank assistant response.  Treat
                    # it as a provider failure so the caller can fail over.
                    if emitted_thinking:
                        raise RuntimeError(
                            "Gemini stream completed with reasoning but no text content"
                        )
                    raise RuntimeError("Gemini stream completed without text content")
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                # Retrying after emitting any token duplicates the user-visible
                # response.  Surface the interruption instead.
                if emitted_text:
                    raise
                last_exc = exc
                if attempt < max_retries:
                    wait = 2 ** (attempt - 1)
                    logger.warning(
                        "Gemini stream network error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt,
                        max_retries,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)
        if last_exc:
            raise last_exc
        raise RuntimeError("Gemini stream failed after retries")

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
        resolved = self.resolve_model(model)
        payload: dict[str, Any] = self._convert_messages(messages)
        gen_config = self._generation_config(options)
        if gen_config:
            payload["generationConfig"] = gen_config
        tools, tool_config = self._tool_payload(options)
        if tools:
            payload["tools"] = tools
            if tool_config:
                payload["toolConfig"] = tool_config

        url = self._get_model_url(resolved, "generateContent")
        resp = await self._post_with_retry(url, payload)
        if resp.status_code != 200:
            raise ProviderHTTPStatusError(
                resp.status_code,
                resp.text,
                label="Gemini API",
                headers=getattr(resp, "headers", None),
            )
        data = resp.json()
        self._last_usage = self._extract_usage_from_gemini(data)
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"Gemini returned no candidates. Response: {data}")
        candidate = candidates[0] if isinstance(candidates[0], dict) else {}
        finish_reason = candidate.get("finishReason")
        if finish_reason:
            self.last_finish_reason = str(finish_reason).strip().lower()
        parsed = deliver_reasoning(
            (options or {}).get(REASONING_SINK_OPTION), "gemini", data
        )
        answer = parsed.content
        for name, arguments in self._function_calls(data):
            rendered = render_tool_call(name, arguments)
            answer = f"{answer}\n{rendered}".strip() if answer else rendered
        return answer

    @staticmethod
    def _generation_config(options: dict[str, Any] | None) -> dict[str, Any]:
        """Translate provider-neutral options into Gemini REST field names."""
        if not options:
            return {}

        config: dict[str, Any] = {}
        if "temperature" in options:
            config["temperature"] = options["temperature"]
        if "top_p" in options:
            config["topP"] = options["top_p"]
        if "top_k" in options:
            config["topK"] = options["top_k"]

        for source_key in ("max_output_tokens", "max_tokens", "num_predict"):
            if source_key in options:
                config["maxOutputTokens"] = options[source_key]
                break
        return config

    async def embed(
        self,
        texts: list[str],
        model: str,
        **kwargs: Any,
    ) -> list[list[float]]:
        """Get embeddings for texts via Gemini embedContent API."""
        resolved = self.resolve_model(model)
        results: list[list[float]] = []
        for text in texts:
            payload = {
                "model": f"models/{resolved}",
                "content": {"parts": [{"text": text}]},
            }
            resp = await self._post_with_retry(f"/models/{resolved}:embedContent", payload)
            if resp.status_code != 200:
                raise ProviderHTTPStatusError(
                    resp.status_code,
                    resp.text,
                    label="Gemini API",
                    headers=getattr(resp, "headers", None),
                )
            data = resp.json()
            embedding = data.get("embedding", {}).get("values", [])
            results.append(list(map(float, embedding)))
        return results
