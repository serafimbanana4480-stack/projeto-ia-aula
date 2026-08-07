"""Cancellation wiring for long-running chat SSE responses.

The chat route deliberately stays focused on turning the agent pipeline into
SSE.  This middleware owns the HTTP concern: it assigns each stream a request
ID, tracks the task that is serving its body, and releases that registration
when the response ends or is cancelled.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from starlette.responses import Response

from backend.orchestrator.cancellation import get_cancellation_registry

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Nexus-Request-Id"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

CallNext = Callable[[Request], Awaitable[Response]]


def is_valid_request_id(request_id: str) -> bool:
    """Return whether a client supplied request ID is safe to store/use in a URL."""
    return bool(REQUEST_ID_PATTERN.fullmatch(request_id))


def _request_id_from_header(request: Request) -> str:
    """Use a valid client ID or generate a collision-resistant server ID."""
    supplied_id = request.headers.get(REQUEST_ID_HEADER, "")
    return supplied_id if is_valid_request_id(supplied_id) else str(uuid.uuid4())


async def chat_cancellation_middleware(request: Request, call_next: CallNext) -> Response:
    """Track ``POST /api/chat`` streaming responses for explicit cancellation.

    A cancellation endpoint needs more than an event flag: an upstream model
    may be awaiting a network read and never observe that flag.  The wrapper
    therefore binds the task consuming the SSE body to the registry.  Calling
    ``POST /api/chat/cancel/{request_id}`` then interrupts that exact task.
    """
    if request.method != "POST" or request.url.path != "/api/chat":
        return await call_next(request)

    registry = get_cancellation_registry()
    request_id = _request_id_from_header(request)
    # Do not let a duplicate client header replace another active stream.
    if registry.get(request_id) is not None:
        request_id = str(uuid.uuid4())
    await registry.register(request_id)
    # Make the same registry entry visible to the inner orchestration loop.
    # Cancelling only the outer ASGI body is insufficient under BaseHTTP
    # middleware because the source iterator may be running in another task.
    request.state.nexus_request_id = request_id

    try:
        response = await call_next(request)
    except BaseException:
        await registry.unregister(request_id)
        raise

    content_type = response.headers.get("content-type", "")
    if "text/event-stream" not in content_type.lower():
        # Authentication, validation, rate-limit, and other non-streaming
        # responses must not leave a stale cancellable entry behind.
        await registry.unregister(request_id)
        return response

    source = response.body_iterator

    async def cancellation_aware_body() -> Any:
        current_task = asyncio.current_task()
        if current_task is not None:
            await registry.bind_stream_task(request_id, current_task)
        try:
            async for chunk in source:
                if registry.is_cancelled(request_id):
                    yield 'data: {"type":"done"}\n\n'
                    break
                yield chunk
        except asyncio.CancelledError:
            # An explicit user cancellation is an expected terminal state,
            # not an ASGI application failure.  Swallow only cancellations
            # that are backed by this registry entry; unrelated task
            # cancellation must still propagate.
            if not registry.is_cancelled(request_id):
                raise
            logger.debug("Chat stream %s stopped by explicit cancellation", request_id)
        finally:
            # Stopping midway through an async generator does not always close
            # the upstream iterator immediately.  Close it explicitly so its
            # LLM/event subscriptions can run their cleanup paths.
            close = getattr(source, "aclose", None)
            if callable(close):
                with contextlib.suppress(asyncio.CancelledError, RuntimeError):
                    await close()
            await registry.unregister(request_id)

    response.body_iterator = cancellation_aware_body()
    response.headers[REQUEST_ID_HEADER] = request_id
    return response
