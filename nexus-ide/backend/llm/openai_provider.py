"""OpenAI-compatible provider for DeepSeek, Groq, OpenAI, etc.

Exposes usage data from the response via the internal ``_last_usage``
attribute (does not change the public API).
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
from collections.abc import AsyncIterator
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.llm.tool_calls import render_tool_call
from backend.runtime.reasoning import REASONING_SINK_OPTION, deliver_reasoning

logger = logging.getLogger(__name__)

#: Upper bound for a provider-supplied ``Retry-After``. A provider asking for
#: an hour must not park an interactive chat for an hour.
MAX_RETRY_AFTER_SECONDS = 60.0
CHAT_REQUEST_MAX_ATTEMPTS = 10
CHAT_REQUEST_RETRY_DELAY_SECONDS = 15.0
# A local server (LM Studio/llama.cpp on loopback) that refuses the TCP
# connection is not running. Ten 15 s retries left the chat on "A pensar…"
# for minutes before any error reached the user; fail fast instead.
LOCAL_CONNECT_MAX_ATTEMPTS = 2
LOCAL_CONNECT_RETRY_DELAY_SECONDS = 2.0


def parse_retry_after(headers: Any) -> float | None:
    """Read the ``Retry-After`` header and return a bounded number of seconds.

    Both wire formats are supported: delta-seconds (``Retry-After: 30``) and an
    HTTP date (``Retry-After: Wed, 21 Oct 2026 07:28:00 GMT``).  ``None`` means
    the header was absent or unparseable, so the caller keeps its own backoff.
    """
    if headers is None:
        return None
    raw = ""
    getter = getattr(headers, "get", None)
    if callable(getter):
        raw = str(getter("Retry-After") or getter("retry-after") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, min(MAX_RETRY_AFTER_SECONDS, float(raw)))
    except (TypeError, ValueError):
        pass
    try:
        target = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if target is None:
        return None
    try:
        import datetime as _datetime

        now = _datetime.datetime.now(_datetime.UTC)
        if target.tzinfo is None:
            target = target.replace(tzinfo=_datetime.UTC)
        delta = (target - now).total_seconds()
    except Exception:  # pragma: no cover - defensive, header is optional
        return None
    return max(0.0, min(MAX_RETRY_AFTER_SECONDS, delta))


def retry_delay(response: Any, attempt: int, *, base: float = 2.0) -> float:
    """Seconds to wait before the next attempt against *response*.

    A provider that answers with ``Retry-After`` knows when it will be back;
    honouring it replaces the fixed exponential backoff that used to hammer
    an endpoint that had explicitly asked for a pause.  Without the header the
    classic ``base ** (attempt - 1)`` backoff is used.
    """
    retry_after = parse_retry_after(getattr(response, "headers", None))
    if retry_after is not None:
        return retry_after
    return float(base ** max(0, int(attempt) - 1))


class ProviderHTTPStatusError(RuntimeError):
    """HTTP error from a provider API carrying the status code.

    The multi-provider manager uses ``status_code`` to distinguish terminal
    errors (401 invalid key, 402 out of credit) — which must open the
    provider's circuit breaker for a long period instead of failing over and
    silently spending on the next paid provider (audit 2026-08-24, B5).

    The response *headers* travel with the error because two provider
    behaviours can only be read there: ``Retry-After`` (how long to wait) and
    OpenRouter's ``X-RateLimit-Reset`` (when the account quota is restored).
    Neither is part of the response body, so a message-only error made both
    impossible to honour.
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        label: str = "OpenAI-compatible API",
        headers: Any = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(f"{label} error {status_code}: {message}")
        self.status_code = int(status_code)
        self.label = label
        self.headers = headers
        self.retry_after = (
            float(retry_after) if retry_after is not None else parse_retry_after(headers)
        )

    @property
    def body(self) -> str:
        """The provider's response body, as passed to the constructor."""
        message = str(self)
        _, _, tail = message.partition(": ")
        return tail


class EmptyChatStreamError(RuntimeError):
    """A successful HTTP response ended before returning text or a tool call.

    This is safe to retry because :meth:`OpenAIProvider.chat_stream` only
    raises it after a complete stream that yielded no user-visible output.
    """


def _is_retryable_chat_error(error: BaseException) -> bool:
    """Whether an OpenAI-compatible chat request can safely be retried.

    Connection failures, transient HTTP statuses and a completed stream with
    no usable output qualify. Auth, billing, invalid-request and model-not-found
    errors go straight to provider fallback. A partial stream is separately
    protected by the caller because replaying it would duplicate visible text
    or a tool call. Rate limits also go straight to the fallback/scheduler:
    this adapter has no durable delayed-retry queue, so sleeping through a long
    fixed retry loop would stall the run and miss the provider's reset window.
    """
    if isinstance(error, ProviderHTTPStatusError):
        status = error.status_code
        if status == 429:
            return False
        if status not in {408, 425} and not 500 <= status <= 599:
            return False
        retry_after = error.retry_after
        if retry_after is not None and retry_after > CHAT_REQUEST_RETRY_DELAY_SECONDS:
            return False
        headers = error.headers
        getter = getattr(headers, "get", None)
        if callable(getter):
            raw_reset = getter("X-RateLimit-Reset") or getter("x-ratelimit-reset")
            if raw_reset:
                try:
                    reset_at = float(raw_reset)
                    if reset_at > 10_000_000_000:
                        reset_at /= 1000.0
                    if reset_at - time.time() > CHAT_REQUEST_RETRY_DELAY_SECONDS:
                        return False
                except (TypeError, ValueError):
                    pass
        return True
    return isinstance(error, (httpx.TransportError, TimeoutError, EmptyChatStreamError))


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
        read_timeout: float = 120.0,
        send_stream_options: bool = True,
    ) -> None:
        self._base_url = _normalize_api_root(base_url)
        self._api_key = api_key
        self._api_prefix = "/" + api_prefix.strip("/") if api_prefix.strip("/") else ""
        self._read_timeout = float(read_timeout)
        self._send_stream_options = bool(send_stream_options)
        self._client = self._new_client()
        # Internal — set after each successful chat_complete / chat_stream
        self._last_usage: dict[str, int] = {}
        # The concrete model this provider was actually asked for. The tier
        # name the user selected ("coder") is not an answer to "which model
        # is working?".
        self.last_model: str = ""
        # Kept separately from the content stream so orchestration can tell a
        # normal stop from a provider-side output-token truncation.
        self.last_finish_reason = ""

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
            # broken network in the UI. Local servers (LM Studio) may need a
            # much longer window: the model is cold-loaded from disk on the
            # first prompt after startup.
            timeout=httpx.Timeout(
                connect=15.0, read=self._read_timeout, write=20.0, pool=20.0
            ),
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
        """Extract token counts from an OpenAI-compatible response body.

        ``completion_tokens_details.reasoning_tokens`` is read too: it is the
        only honest source for how much of the budget a reasoning model spent
        thinking, and it is what makes the session panel stop reporting 0.
        """
        usage = data.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        details = usage.get("completion_tokens_details")
        reasoning = 0
        if isinstance(details, dict):
            for key in ("reasoning_tokens", "reasoning", "thoughts_tokens"):
                value = details.get(key)
                if isinstance(value, int | float) and value > 0:
                    reasoning = int(value)
                    break
        if not reasoning:
            for key in ("reasoning_tokens", "thinking_tokens"):
                value = usage.get(key)
                if isinstance(value, int | float) and value > 0:
                    reasoning = int(value)
                    break
        extracted = {
            "input_tokens": usage.get("prompt_tokens", 0) or 0,
            "output_tokens": usage.get("completion_tokens", 0) or 0,
            "total_tokens": usage.get("total_tokens", 0) or 0,
        }
        if reasoning:
            # Only present when the provider actually reported it, so a
            # non-reasoning run keeps the historical dictionary shape.
            extracted["reasoning_tokens"] = reasoning
        return extracted

    async def aclose(self) -> None:
        await self._client.aclose()

    def _retry_budget(self, error: BaseException) -> tuple[int, float]:
        """Attempts and delay for ``error``; refused loopback connects fail fast."""
        if isinstance(error, httpx.ConnectError):
            host = (urlparse(self._base_url).hostname or "").lower()
            if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
                return LOCAL_CONNECT_MAX_ATTEMPTS, LOCAL_CONNECT_RETRY_DELAY_SECONDS
        return CHAT_REQUEST_MAX_ATTEMPTS, CHAT_REQUEST_RETRY_DELAY_SECONDS

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
        """Retry transient chat API failures without changing the request.

        The same model, conversation messages, options and tool schemas are
        sent on every attempt. Retries stop as soon as any content is emitted;
        replaying a partial answer or tool call would corrupt the conversation.
        """
        for attempt in range(1, CHAT_REQUEST_MAX_ATTEMPTS + 1):
            emitted_output = False
            try:
                async for token in self._chat_stream_once(
                    model, messages, options=options, **kwargs
                ):
                    if token:
                        emitted_output = True
                    yield token
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                max_attempts, delay = self._retry_budget(exc)
                if (
                    emitted_output
                    or not _is_retryable_chat_error(exc)
                    or attempt >= max_attempts
                ):
                    raise
                logger.warning(
                    "OpenAI-compatible chat stream failed (attempt %d/%d); retrying in %.0fs: %s",
                    attempt,
                    max_attempts,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

    async def _chat_stream_once(
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
            # Some stricter OpenAI-compatible servers reject the parameter, so
            # subclasses may opt out and retry without it.
        }
        if self._send_stream_options:
            payload["stream_options"] = {"include_usage": True}
        if options:
            for key in (
                "temperature",
                "max_tokens",
                "top_p",
                "frequency_penalty",
                "presence_penalty",
                "reasoning",
                "reasoning_effort",
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
        self.last_finish_reason = ""
        self.last_model = str(model or "")
        emitted_text = False
        # Accumulate streamed native tool-call fragments keyed by their index.
        # OpenAI streams ``function.name`` once and ``function.arguments`` in
        # arbitrary-sized chunks, so both are concatenated as they arrive.
        tool_calls_acc: dict[int, dict[str, Any]] = {}
        async with self._client.stream("POST", self._api_path("chat/completions"), json=payload) as resp:
            if resp.status_code != 200:
                text = await resp.aread()
                raise ProviderHTTPStatusError(
                    resp.status_code, text.decode(), headers=getattr(resp, "headers", None)
                )

            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or line in ("data: [DONE]", "data:[DONE]"):
                    continue
                # The SSE spec allows ``data:`` with or without the space
                # after the colon. Requiring the exact ``"data: "`` prefix
                # made a perfectly legal frame look like an empty response.
                if line.startswith("data:"):
                    try:
                        data = json.loads(line[5:].lstrip())
                        if not isinstance(data, dict):
                            continue
                        if data.get("error"):
                            raise RuntimeError(f"OpenAI stream error: {data['error']}")
                        choices = data.get("choices", [])
                        if not choices or not isinstance(choices[0], dict):
                            usage = data.get("usage")
                            if usage:
                                self._last_usage.update(self._extract_usage(data))
                            continue
                        finish_reason = choices[0].get("finish_reason")
                        if finish_reason:
                            self.last_finish_reason = str(finish_reason).strip().lower()
                        # ``delta.reasoning_content`` (DeepSeek R1, o-series) and
                        # ``delta.reasoning`` are the model's own approach text.
                        # It is routed to the caller's reasoning sink and NEVER
                        # yielded: mixing it into the answer stream is how a
                        # private transcript ends up in a user-visible reply.
                        # The OpenAI Responses API streams summaries as their own
                        # frame, which the shared parser also understands.
                        parsed = deliver_reasoning(
                            (options or {}).get(REASONING_SINK_OPTION), "openai", data
                        )
                        if parsed.usage:
                            self._last_usage.update(parsed.usage)
                        content = parsed.content
                        if content:
                            emitted_text = True
                            yield content
                        for frag in parsed.tool_calls:
                            if not isinstance(frag, dict):
                                continue
                            idx = frag.get("index", 0) or 0
                            slot = tool_calls_acc.setdefault(idx, {"name": "", "arguments": ""})
                            fn = frag.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                            arguments = fn.get("arguments")
                            if isinstance(arguments, dict):
                                # Some OpenAI-compatible local servers return
                                # parsed arguments as an object instead of the
                                # canonical JSON string. Preserve that object;
                                # concatenating it with the string accumulator
                                # raises TypeError and turns a valid tool call
                                # into an empty-stream retry.
                                slot["arguments"] = arguments
                            elif isinstance(arguments, str) and arguments:
                                existing_arguments = slot.get("arguments", "")
                                if isinstance(existing_arguments, dict):
                                    existing_arguments = json.dumps(
                                        existing_arguments, ensure_ascii=False
                                    )
                                slot["arguments"] = f"{existing_arguments}{arguments}"
                        # Try to extract usage from stream — some providers
                        # include it on the final chunk.
                        usage = data.get("usage")
                        if usage:
                            self._last_usage.update(self._extract_usage(data))
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
            emitted_tool_call = True
            yield "\n" + render_tool_call(name, slot.get("arguments", ""))

        if not emitted_text and not emitted_tool_call:
            # A 200 response with no usable text used to look like a successful
            # empty reply. Raising lets chat_stream retry this exact request
            # while no user-visible output exists; after its bounded attempts,
            # orchestration can select a healthy fallback.
            raise EmptyChatStreamError("OpenAI stream completed without text content")

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Retry transient non-streaming API failures with the same context."""
        for attempt in range(1, CHAT_REQUEST_MAX_ATTEMPTS + 1):
            try:
                return await self._chat_complete_once(
                    model, messages, options=options, **kwargs
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                max_attempts, delay = self._retry_budget(exc)
                if (
                    not _is_retryable_chat_error(exc)
                    or attempt >= max_attempts
                ):
                    raise
                logger.warning(
                    "OpenAI-compatible chat completion failed (attempt %d/%d); retrying in %.0fs: %s",
                    attempt,
                    max_attempts,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

        raise RuntimeError("OpenAI-compatible chat completion retry loop exited unexpectedly")

    async def _chat_complete_once(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Non-streaming chat completion."""
        self._ensure_open()
        self.last_finish_reason = ""
        self.last_model = str(model or "")
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if options:
            for key in ("temperature", "max_tokens", "top_p"):
                if key in options:
                    payload[key] = options[key]
            for key in ("reasoning", "reasoning_effort"):
                if key in options:
                    payload[key] = options[key]
            for key in ("tools", "tool_choice", "parallel_tool_calls"):
                if options.get(key):
                    payload[key] = options[key]

        resp = await self._client.post(self._api_path("chat/completions"), json=payload)
        if resp.status_code != 200:
            raise ProviderHTTPStatusError(resp.status_code, resp.text, headers=getattr(resp, "headers", None))

        data = resp.json()
        self._last_usage = self._extract_usage(data)
        finish_reason = data["choices"][0].get("finish_reason")
        if finish_reason:
            self.last_finish_reason = str(finish_reason).strip().lower()
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
        self._ensure_open()
        resp = await self._client.post(
            self._api_path("embeddings"),
            json={"model": model, "input": texts},
        )
        if resp.status_code != 200:
            raise ProviderHTTPStatusError(resp.status_code, resp.text, headers=getattr(resp, "headers", None))

        data = resp.json()
        return [item["embedding"] for item in data["data"]]
