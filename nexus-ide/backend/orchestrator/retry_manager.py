"""Generic retry helper for the multi-agent orchestrator.

Extracted from :mod:`backend.orchestrator.engine` so that retry behavior
(``2 ** attempt + uniform(0, 1)`` exponential backoff with jitter) can
be unit-tested in isolation and reused outside the engine.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class RetryManager:
    """Exponential-backoff retry with jitter, suitable for any async coroutine factory."""

    def __init__(self, *, base_delay: float = 1.0, max_retries: int = 2) -> None:
        self._base_delay = base_delay
        self._max_retries = max_retries

    async def execute_with_retry(
        self,
        coro_factory: Callable[[], Any],
        *,
        max_attempts: int,
        on_retry: Callable[[int, BaseException], Any] | None = None,
    ) -> Any:
        """Run ``coro_factory`` with exponential backoff between attempts.

        ``coro_factory`` is invoked once per attempt and must return either
        an awaitable or a value. If the awaitable raises (or the factory
        raises) a non-``BaseException``-derived exception, ``on_retry`` is
        called with the 0-based attempt index and the exception, and the
        helper sleeps ``base_delay * (2 ** attempt) + uniform(0, 1)``
        before retrying.

        Returns the first successful result. Raises the last exception
        if all attempts fail.
        """
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        last_exc: BaseException | None = None
        for attempt in range(max_attempts):
            try:
                result = coro_factory()
                if asyncio.iscoroutine(result):
                    return await result
                return result
            except asyncio.CancelledError:
                # Never swallow cancellation
                raise
            except BaseException as exc:  # noqa: BLE001 - intentional, see docstring
                last_exc = exc
                if attempt >= max_attempts - 1:
                    # Final attempt failed; surface the exception below.
                    break
                if on_retry is not None:
                    try:
                        on_retry_result = on_retry(attempt, exc)
                        if asyncio.iscoroutine(on_retry_result):
                            await on_retry_result
                    except Exception as callback_exc:  # noqa: BLE001
                        logger.warning("on_retry callback raised: %s", callback_exc)
                jitter = random.uniform(0, 1)
                await asyncio.sleep((2**attempt) + jitter)

        assert last_exc is not None
        raise last_exc
