"""Fallback and retry policies.

Matrix defined in ARCHITECTURE.md §4.3 and `config/models.yaml` under `fallback:`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from backend.config.settings import load_models_config
from backend.tools.ollama_client import OllamaError

logger = logging.getLogger(__name__)

# Do not impose a product timeout while a local/cloud model is loading or
# reasoning. Deployments that need a watchdog can opt in explicitly.
_stream_start_timeout_raw = os.environ.get("NEXUS_STREAM_START_TIMEOUT", "").strip()
try:
    _STREAM_START_TIMEOUT_SECONDS: float | None = (
        float(_stream_start_timeout_raw)
        if float(_stream_start_timeout_raw) > 0
        else None
    ) if _stream_start_timeout_raw else 180.0
except ValueError:
    _STREAM_START_TIMEOUT_SECONDS = 180.0

AgentStream = Callable[[str], AsyncIterator[str]]
"""Callable that takes a primary agent name and returns an async token stream."""


@dataclass(frozen=True)
class FallbackOutcome:
    """Record of which agent ultimately served the request.

    ``reason`` is non-empty only when the primary failed.
    """

    used_agent: str
    attempts: int
    notified_dashboard: bool
    reason: str


def _load_chain(primary: str) -> list[str]:
    """Return the ordered fallback chain for ``primary`` from models.yaml.

    Unknown agents fall through to a conservative chain pointing to MICRO so
    the system always makes forward progress.
    """
    cfg = load_models_config().get("fallback", {}) or {}
    chain = cfg.get(primary)
    if isinstance(chain, list) and chain:
        return [str(x) for x in chain]
    return ["MICRO"]


async def invoke_with_fallback(
    primary_agent: str,
    invoke: Callable[[str], Awaitable[AsyncIterator[str]]],
) -> tuple[FallbackOutcome, AsyncIterator[str]]:
    """Invoke ``primary_agent`` via ``invoke`` and fall back on failure.

    ``invoke`` is an async callable that, given an agent name, returns an
    async iterator of tokens. This indirection keeps the fallback module
    decoupled from the registry and trivial to test.

    Returns both the outcome record and the stream that succeeded.  Async
    generators are lazy: an LLM failure normally happens on the first
    ``anext()``, not when the generator is created.  We therefore prime each
    candidate before selecting it.  This makes agent failover work for real
    streaming provider failures instead of only registry/setup errors.

    If an agent has already emitted a substantive token, this function never
    switches agents mid-response.  Retrying after visible output produces
    duplicate or contradictory answers and can repeat side-effecting tool
    calls; the caller receives the original stream error instead.
    """
    chain = list(dict.fromkeys([primary_agent, *_load_chain(primary_agent)]))
    last_error: Exception | None = None

    for attempt, candidate in enumerate(chain, start=1):
        try:
            stream = await invoke(candidate)
            stream = await _prime_stream(stream)
            outcome = FallbackOutcome(
                used_agent=candidate,
                attempts=attempt,
                notified_dashboard=attempt > 1,
                reason="" if attempt == 1 else f"fell-back-from-{primary_agent}",
            )
            return outcome, stream
        except asyncio.CancelledError:
            # Cancellation must not be silently swallowed — it is intentionally
            # re-raised so the caller (_run_pipeline / event_stream wrapper) can
            # emit a terminal ``done`` SSE event before the stream terminates.
            raise
        except Exception as exc:  # Provider errors occur while priming lazy streams.
            logger.warning("Agent %r failed (attempt %d): %s", candidate, attempt, exc)
            last_error = exc

    # Entire chain exhausted.
    raise last_error if last_error else OllamaError(f"fallback chain exhausted for {primary_agent}")


def _is_setup_event(token: str) -> bool:
    """Return whether *token* is an internal event emitted before LLM output.

    ReAct agents can yield an iteration/thinking marker before opening the
    provider stream.  It is not evidence that the provider is healthy, so do
    not let it prevent the fallback chain from trying the next agent.
    """
    return token.startswith("<event>thinking|") or token == "<event>thinking_end</event>"


def _inline_failure_message(token: str) -> str | None:
    """Extract an early ReAct failure marker, if one was emitted."""
    if token.startswith("<event>error|") and token.endswith("</event>"):
        return token[len("<event>error|") : -len("</event>")].strip() or "Agent stream failed"
    return None


async def _prepend_tokens(prefix: list[str], stream: AsyncIterator[str]) -> AsyncIterator[str]:
    """Yield already-primed tokens followed by the remainder of *stream*."""
    for token in prefix:
        yield token
    async for token in stream:
        yield token


async def _prime_stream(stream: AsyncIterator[str], max_retries: int = 2) -> AsyncIterator[str]:
    """Wait for the first substantive stream token and preserve all tokens.

    An empty stream is considered a failed attempt: returning a blank answer
    makes the UI look as though the AI stopped, and it prevents a healthy
    fallback from being used.

    Retries transient empty-stream / inline-failure cases up to ``max_retries``
    times before giving up. ``asyncio.CancelledError`` is intentionally not
    caught here.
    """
    prefix: list[str] = []
    attempt = 0
    while True:
        try:
            next_token = anext(stream)
            token = (
                await asyncio.wait_for(next_token, timeout=_STREAM_START_TIMEOUT_SECONDS)
                if _STREAM_START_TIMEOUT_SECONDS is not None
                else await next_token
            )
        except StopAsyncIteration as exc:
            if attempt < max_retries:
                attempt += 1
                logger.warning(
                    "Stream produced no tokens on attempt %d/%d; retrying",
                    attempt,
                    max_retries,
                )
                continue
            raise RuntimeError("Agent produced an empty stream") from exc

        failure = _inline_failure_message(token)
        if failure is not None:
            if attempt < max_retries and "rate limit" in failure.lower():
                attempt += 1
                logger.warning(
                    "Stream hit rate limit on attempt %d/%d; retrying after backoff",
                    attempt,
                    max_retries,
                )
                await asyncio.sleep(min(2 ** attempt, 30))
                continue
            raise RuntimeError(failure)
        if not token or _is_setup_event(token):
            prefix.append(token)
            continue
        return _prepend_tokens(prefix + [token], stream)
