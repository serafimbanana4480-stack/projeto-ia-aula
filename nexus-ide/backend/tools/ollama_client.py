"""Async Ollama HTTP client used by agents, routes, and embeddings."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_LIMITS = httpx.Limits(
    max_keepalive_connections=50,
    max_connections=100,
    keepalive_expiry=30.0,
)
# Local CPU inference can spend tens of seconds before the first useful chunk,
# especially after a larger model/context is loaded.  A 60s read timeout made
# a healthy Ollama server look unavailable for complex prompts.  Keep this
# bounded, but leave enough time for one honest generation; deployments with
# stricter limits can override it explicitly through the constructor.
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=5.0, pool=5.0)

_RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
_RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    httpx.TimeoutException,
)
_BACKOFF_DELAYS = (1, 2, 4, 8)
_MODEL_ALIASES = {
    # Preserve historical aliases that existed in the AirLLM-only phase.
    "q3b-4bit": "qwen2.5:3b",
    "coder3b-4bit": "qwen2.5-coder:3b",
    # Map legacy cloud model IDs to local Ollama fallbacks
    "deepseek/deepseek-v4-flash": "qwen2.5:1.5b",
    "deepseek/deepseek-chat": "qwen2.5:1.5b",
    "deepseek-chat": "qwen2.5:1.5b",
}


@dataclass(frozen=True)
class ChatMessage:
    """A single turn in a chat exchange."""

    role: str
    content: str
    timestamp: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content, "timestamp": self.timestamp}


class OllamaError(RuntimeError):
    """Raised when the Ollama server returns an error."""


class OllamaConnectionError(OllamaError):
    """Raised when the Ollama server cannot be reached."""


class OllamaModelError(OllamaError):
    """Raised when a requested model is not available."""


class OllamaClient:
    provider_name = "ollama"

    """Small async wrapper around the Ollama HTTP API."""

    def __init__(
        self,
        base_url: str = "",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: httpx.Timeout | float | None = None,
        limits: httpx.Limits | None = None,
    ) -> None:
        if not base_url:
            from backend.config.settings import get_settings

            base_url = get_settings().ollama_host

        self.base_url = (base_url or "http://localhost:11434").rstrip("/")
        self._timeout = timeout or DEFAULT_TIMEOUT
        self._limits = limits or DEFAULT_LIMITS
        self._transport = transport
        self._client = self._new_client()
        # Internal — populated after each chat completion / stream
        self._last_usage: dict[str, int] = {}
        self._last_finish_reason: str | None = None

    def _new_client(self) -> httpx.AsyncClient:
        """Create the transport, including after a settings hot-swap."""
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self._timeout,
            limits=self._limits,
            transport=self._transport,
        )

    def _ensure_open(self) -> None:
        """Recreate the HTTP client if a lifecycle hand-over closed it."""
        if self._client.is_closed:
            logger.warning("Re-opening closed Ollama HTTP client for %s", self.base_url)
            self._client = self._new_client()

    @property
    def last_finish_reason(self) -> str | None:
        """Return the terminal reason reported by the latest chat stream."""
        return self._last_finish_reason

    async def aclose(self) -> None:
        await self._client.aclose()

    def _resolve_model(self, model: str) -> str:
        resolved = _MODEL_ALIASES.get(model, model)
        # A resilient cloud -> local fallback keeps the user's selected cloud
        # model for the primary provider. Only the explicitly attached
        # fallback object may remap it to an installed local model.
        fallback_model = str(getattr(self, "fallback_model", "") or "").strip()
        if fallback_model and (resolved == "openrouter/free" or ":free" in resolved):
            return fallback_model
        return resolved

    @staticmethod
    def _normalize_messages(
        messages: list[dict[str, str]] | list[ChatMessage],
    ) -> list[dict[str, str]]:
        normalized = [m.to_dict() if isinstance(m, ChatMessage) else dict(m) for m in messages]
        # Ollama's chat templates require system instructions before every
        # user/tool turn.  The agent pipeline may append a later system
        # directive while recovering a ReAct iteration; keep all system
        # messages together at the front for local model compatibility.
        system_messages = [m for m in normalized if m.get("role") == "system"]
        other_messages = [m for m in normalized if m.get("role") != "system"]
        if not system_messages:
            return other_messages
        # Some Ollama templates accept only one system turn.  Merge recovery
        # directives and the base prompt instead of sending a second system
        # role that the template rejects as "not at the beginning".
        merged_system = dict(system_messages[0])
        merged_system["content"] = "\n\n".join(
            str(message.get("content", ""))
            for message in system_messages
            if str(message.get("content", ""))
        )
        return [merged_system, *other_messages]

    @staticmethod
    def _prepare_direct_answer_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """Turn the local fallback into a visible, tool-free answer lane."""
        # The ReAct system prompt intentionally teaches cloud models how to
        # call tools. A small local fallback may follow those examples even
        # after native tool schemas are removed, producing no visible answer.
        # Keep only textual conversation turns and replace the full system
        # prompt with an unambiguous direct-answer contract.
        direct_system = {
            "role": "system",
            "content": (
                "You are the Nexus IDE assistant. Answer the user's request directly in visible "
                "plain text. Do not call tools, emit JSON/XML tool tags, or reveal private thinking. "
                "Use only facts present in the conversation. Never invent environment variable names, "
                "ports, endpoints, files, tests, or configuration. If a fact is not verified, say "
                "NÃO VALIDADO. SSE is HTTP server-sent events, not WebSocket; do not conflate them. "
                "Follow every explicit output constraint completely. If the user requests a number "
                "of points, steps, or items, write all of them with clear numbering before stopping. "
                "If a word limit is requested, stay within it while still completing the requested list. "
                "If the user asks you to repeat an exact literal marker, output that marker exactly; "
                "repeating user-provided text is not an unverified factual claim."
            ),
        }
        # Preserve only the explicitly inert, bounded project bootstrap.  The
        # direct-answer lane must discard ReAct/tool instructions, but dropping
        # this data made questions such as "what is this project?" claim that
        # no project context had been supplied even when the UI selected one.
        project_contexts = [
            {
                "role": "system",
                "content": str(message.get("content", ""))[:12_000],
            }
            for message in messages
            if message.get("role") == "system"
            and str(message.get("content", "")).startswith(
                "PROJECT BOOTSTRAP CONTEXT (INERT DATA):"
            )
        ][:1]
        text_turns = [
            dict(message) for message in messages if message.get("role") in {"user", "assistant"}
        ]
        latest_user = next(
            (message for message in reversed(text_turns) if message.get("role") == "user"),
            None,
        )
        latest_user_content = str((latest_user or {}).get("content", ""))
        # A structured request must be answered from the current instruction.
        # Feeding a small local model an earlier, already-truncated assistant
        # answer made it copy that partial list and stop again. Keep history
        # for normal follow-ups, but make explicit list/number constraints a
        # single-turn prompt so the local model can finish the requested shape.
        if latest_user is not None and re.search(
            r"(?:(?:exatamente|exactamente)|em\s+(?:exatamente|exactamente))\s+\d+\s+"
            r"(?:pontos?|passos?|itens?)|"
            r"\b(?:lista|enumerad[ao]|numerad[ao])\b",
            latest_user_content,
            flags=re.IGNORECASE,
        ):
            text_turns = [latest_user]
        else:
            # Bound noisy chat history in the CPU fallback while retaining
            # enough recent context for ordinary follow-up questions.
            text_turns = text_turns[-6:]
        return [direct_system, *project_contexts, *text_turns]

    @staticmethod
    def _format_attempt_failure(
        method: str,
        path: str,
        attempt_count: int,
        failures: list[str],
    ) -> str:
        history = " | ".join(failures)
        return f"{method} {path} failed after {attempt_count} attempts: {history}"

    async def _request_with_retries(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        timeout: httpx.Timeout | float | None = None,
    ) -> httpx.Response:
        self._ensure_open()
        failures: list[str] = []
        max_attempts = len(_BACKOFF_DELAYS) + 1

        for attempt in range(1, max_attempts + 1):
            try:
                response = await self._client.request(
                    method,
                    path,
                    json=json_payload,
                    timeout=timeout,
                )
            except _RETRYABLE_EXCEPTIONS as exc:
                error_message = f"{type(exc).__name__}: {exc}"
                failures.append(error_message)
                if attempt == max_attempts:
                    raise OllamaConnectionError(
                        self._format_attempt_failure(method, path, max_attempts, failures)
                    ) from exc
                await asyncio.sleep(_BACKOFF_DELAYS[attempt - 1])
                continue

            if response.status_code < 400:
                return response

            body = response.text.strip()
            error_message = f"HTTP {response.status_code}: {body or response.reason_phrase}"

            if response.status_code == 404:
                raise OllamaModelError(error_message)

            if response.status_code not in _RETRYABLE_STATUS_CODES:
                raise OllamaError(error_message)

            failures.append(error_message)
            if attempt == max_attempts:
                raise OllamaError(
                    self._format_attempt_failure(method, path, max_attempts, failures)
                )

            await asyncio.sleep(_BACKOFF_DELAYS[attempt - 1])

        raise OllamaError(f"{method} {path} failed without a response")

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]] | list[ChatMessage],
        *,
        options: dict[str, Any] | None = None,
        **_: Any,
    ) -> AsyncIterator[str]:
        """Stream a response from Ollama without buffering the whole body.

        ``AsyncClient.request`` reads a response before returning it, which
        made the previous implementation appear to stream while actually
        waiting for the full generation.  Keep the response context open while
        yielding lines and retry only failures that happen before any content
        is emitted, otherwise a retry would duplicate user-visible text.
        """
        self._ensure_open()
        self._last_usage = {}
        self._last_finish_reason = None
        # ``AgentBase`` supplies portable output-budget aliases for cloud
        # providers.  Ollama expects ``num_predict``; forwarding the other
        # names inside its options object is unnecessary and can break strict
        # server versions.
        excluded_options = {"max_tokens", "max_output_tokens"}
        if getattr(self, "disable_tools", False):
            excluded_options.update({"tools", "tool_choice"})
        ollama_options = {
            key: value for key, value in (options or {}).items() if key not in excluded_options
        }
        if getattr(self, "direct_answer", False):
            # The Coder tier can request an 8k output budget.  That is useful
            # for a tool-capable cloud model but makes a CPU local fallback
            # spend minutes generating unnecessary text.  Keep this lane
            # bounded while leaving the normal Ollama client untouched. Give
            # structured/numbered requests enough room to finish their list;
            # short literal replies still use the faster small budget.
            try:
                requested_predict = int(ollama_options.get("num_predict", 512))
            except (TypeError, ValueError):
                requested_predict = 512
            latest_user = next(
                (
                    str(
                        message.get("content", "")
                        if isinstance(message, dict)
                        else getattr(message, "content", "")
                    )
                    for message in reversed(messages)
                    if (
                        message.get("role")
                        if isinstance(message, dict)
                        else getattr(message, "role", None)
                    )
                    == "user"
                ),
                "",
            )
            structured_request = bool(
                re.search(
                    r"(?:(?:exatamente|exactamente)|em\s+(?:exatamente|exactamente))\s+\d+\s+"
                    r"(?:pontos?|passos?|itens?)|"
                    r"\b(?:lista|enumerad[ao]|numerad[ao])\b",
                    latest_user,
                    flags=re.IGNORECASE,
                )
            )
            cap = 512 if structured_request else 256
            ollama_options["num_predict"] = min(max(requested_predict, 128), cap)
        resolved_model = self._resolve_model(model)
        if getattr(self, "direct_answer", False):
            direct_messages = [
                message.to_dict() if isinstance(message, ChatMessage) else dict(message)
                for message in messages
            ]
            normalized_messages = self._normalize_messages(
                self._prepare_direct_answer_messages(direct_messages)
            )
        else:
            normalized_messages = self._normalize_messages(messages)
        payload = {
            "model": resolved_model,
            "messages": normalized_messages,
            "stream": True,
            "options": ollama_options,
        }
        # Qwen-derived local models can spend the entire output budget in the
        # Ollama ``message.thinking`` field, leaving ``message.content`` empty
        # and making the chat appear broken. Keep thinking opt-in for these
        # models; callers can still pass ``options={"think": True}``.
        if "think" in (options or {}):
            payload["think"] = bool(options["think"])
        elif any(marker in resolved_model.lower() for marker in ("qwen", "ornith")):
            payload["think"] = False
        failures: list[str] = []
        max_attempts = len(_BACKOFF_DELAYS) + 1
        emitted_content = False

        for attempt in range(1, max_attempts + 1):
            retryable_failure: str | None = None
            try:
                async with self._client.stream("POST", "/api/chat", json=payload) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", errors="replace").strip()
                        error_message = (
                            f"HTTP {response.status_code}: {body or response.reason_phrase}"
                        )
                        if response.status_code == 404:
                            raise OllamaModelError(error_message)
                        if "System message must be at the beginning" in error_message:
                            # This is a deterministic payload/template error,
                            # not a transient server failure. Retrying the same
                            # invalid message only delays the real diagnosis.
                            raise OllamaError(error_message)
                        if response.status_code not in _RETRYABLE_STATUS_CODES:
                            raise OllamaError(error_message)
                        retryable_failure = error_message
                    else:
                        final_chunk: dict[str, Any] = {}
                        async for line in response.aiter_lines():
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                            except json.JSONDecodeError:
                                logger.debug(
                                    "Skipping malformed Ollama stream line: %s", line[:200]
                                )
                                continue

                            if not isinstance(data, dict):
                                continue
                            if data.get("error"):
                                raise OllamaError(f"Ollama stream error: {data['error']}")
                            chunk = data.get("message", {}).get("content")
                            if chunk:
                                emitted_content = True
                                yield chunk

                            # Some compatible Ollama servers include the
                            # final text delta and ``done`` in one frame.
                            # Consume that delta before ending the stream so
                            # the last word is never silently truncated.
                            if data.get("done") is True:
                                final_chunk = data
                                break

                        if final_chunk:
                            if not emitted_content:
                                retryable_failure = "Ollama stream completed without content"
                            else:
                                self._last_finish_reason = str(
                                    final_chunk.get("done_reason")
                                    or final_chunk.get("finish_reason")
                                    or "stop"
                                )
                                self._last_usage = {
                                    "input_tokens": final_chunk.get("prompt_eval_count", 0) or 0,
                                    "output_tokens": final_chunk.get("eval_count", 0) or 0,
                                    "total_tokens": (
                                        (final_chunk.get("prompt_eval_count", 0) or 0)
                                        + (final_chunk.get("eval_count", 0) or 0)
                                    ),
                                }
                                return
                        else:
                            retryable_failure = "Ollama stream ended before its final done frame"
            except _RETRYABLE_EXCEPTIONS as exc:
                if emitted_content:
                    raise OllamaConnectionError(
                        f"Ollama stream interrupted after output: {type(exc).__name__}: {exc}"
                    ) from exc
                retryable_failure = f"{type(exc).__name__}: {exc}"

            if retryable_failure is None:
                # All non-retryable errors are raised above.  Retain this guard
                # so a future control-flow change cannot silently report success.
                raise OllamaError("Ollama stream ended without a result")

            failures.append(retryable_failure)
            if emitted_content:
                raise OllamaConnectionError(
                    f"Ollama stream interrupted after output: {retryable_failure}"
                )
            if attempt < max_attempts:
                await asyncio.sleep(_BACKOFF_DELAYS[attempt - 1])
                continue
            raise OllamaConnectionError(
                self._format_attempt_failure("POST", "/api/chat", max_attempts, failures)
            )

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]] | list[ChatMessage],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        self._last_usage = {}
        parts: list[str] = []
        async for token in self.chat_stream(model, messages, options=options, **kwargs):
            parts.append(token)
        # Usage is set by chat_stream from the final chunk
        return "".join(parts)

    async def embed(
        self,
        texts: list[str],
        model: str,
        **_: Any,
    ) -> list[list[float]]:
        payload = {"model": self._resolve_model(model), "input": texts}
        response = await self._request_with_retries("POST", "/api/embed", json_payload=payload)
        data = response.json()
        if "embeddings" in data and isinstance(data["embeddings"], list):
            return data["embeddings"]
        if "embedding" in data and isinstance(data["embedding"], list):
            return [data["embedding"]]
        raise OllamaError("Unexpected Ollama embedding response payload")

    async def health_check(self, timeout: float = 5.0) -> bool:
        try:
            self._ensure_open()
            response = await self._client.get("/api/tags", timeout=timeout)
            return response.status_code == 200
        except Exception:
            return False


__all__ = [
    "ChatMessage",
    "OllamaError",
    "OllamaConnectionError",
    "OllamaModelError",
    "OllamaClient",
    "DEFAULT_LIMITS",
    "DEFAULT_TIMEOUT",
]
