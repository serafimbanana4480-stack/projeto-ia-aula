"""Fallback and retry policies.

Matrix defined in ARCHITECTURE.md §4.3 and `config/models.yaml` under `fallback:`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from backend.config.settings import load_models_config
from backend.tools.ollama_client import OllamaError

logger = logging.getLogger(__name__)

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

    Returns both the outcome record and the stream that succeeded. If every
    agent in the chain fails, the last ``OllamaError`` is re-raised.
    """
    chain = [primary_agent, *_load_chain(primary_agent)]
    last_error: Exception | None = None

    for attempt, candidate in enumerate(chain, start=1):
        try:
            stream = await invoke(candidate)
            outcome = FallbackOutcome(
                used_agent=candidate,
                attempts=attempt,
                notified_dashboard=attempt > 1,
                reason="" if attempt == 1 else f"fell-back-from-{primary_agent}",
            )
            return outcome, stream
        except (OllamaError, KeyError, FileNotFoundError) as exc:
            logger.warning("Agent %r failed (attempt %d): %s", candidate, attempt, exc)
            last_error = exc

    # Entire chain exhausted.
    raise last_error if last_error else OllamaError(f"fallback chain exhausted for {primary_agent}")
