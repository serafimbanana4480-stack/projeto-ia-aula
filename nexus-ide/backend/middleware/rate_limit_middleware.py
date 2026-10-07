"""FastAPI-version-compatible global rate-limit middleware.

Why this exists instead of ``slowapi.middleware.SlowAPIMiddleware``
-------------------------------------------------------------------
slowapi's middleware resolves the request's endpoint by iterating
``app.routes`` and keeping the last object that both FULL-matches the scope and
has an ``.endpoint`` attribute::

    for route in routes:
        match, _ = route.matches(scope)
        if match == Match.FULL and hasattr(route, "endpoint"):
            handler = route.endpoint

FastAPI 0.140 (the version pinned here) does **not** put included routers'
routes in ``app.routes`` directly: each ``include_router`` call becomes an
``_IncludedRouter`` node whose children are only reachable through
``effective_candidates()``.  ``_IncludedRouter`` has no ``.endpoint``, so the
lookup returns ``None``; ``_should_exempt(None, handler)`` is ``True``; and
every single request silently skips the global limit.  The middleware therefore
had to be installed but did nothing — exactly the class of failure the audit
flagged (a limiter that exists and does not limit).

This middleware does the same job using an endpoint index built once from
:func:`backend.middleware.rate_limit.build_endpoint_index`, which understands
both the old flat route list and the new nested one.

Behaviour kept identical to slowapi's own middleware:
* routes carrying their own ``@limiter.limit(...)`` are skipped here and
  handled by the decorator (no double counting);
* a breach raises ``RateLimitExceeded`` which the app-level exception handler
  (installed by :func:`backend.middleware.rate_limit.attach_to_app`) turns into
  **HTTP 429** with ``Retry-After``;
* remaining-quota headers are injected on success.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.middleware.rate_limit import endpoint_index_for, resolve_endpoint

logger = logging.getLogger(__name__)


class NexusRateLimitMiddleware(BaseHTTPMiddleware):
    """Apply the limiter's ``default_limits`` to every non-decorated route."""

    def __init__(self, app: Any, *, limiter: Limiter | None = None) -> None:
        super().__init__(app)
        self._limiter = limiter

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        limiter = self._limiter or getattr(request.app.state, "limiter", None)
        if limiter is None or not limiter.enabled:
            return await call_next(request)

        index = endpoint_index_for(request.app)
        endpoint = resolve_endpoint(index, request.url.path)
        route_name = (
            f"{endpoint.__module__}.{endpoint.__name__}"
            if endpoint is not None
            else ""
        )
        # A route with its own @limiter.limit is the decorator's business.
        if route_name and route_name in getattr(limiter, "_route_limits", {}):
            return await call_next(request)

        try:
            limiter._check_request_limit(request, endpoint, True)
        except RateLimitExceeded as exc:
            handler = request.app.exception_handlers.get(
                RateLimitExceeded, _rate_limit_exceeded_handler
            )
            if inspect.iscoroutinefunction(handler):
                return await handler(request, exc)
            return handler(request, exc)
        except Exception as exc:  # pragma: no cover - storage failure
            logger.warning("Rate limit check failed: %s", exc)
            return await call_next(request)

        response = await call_next(request)
        view_limit = getattr(request.state, "view_rate_limit", None)
        if view_limit is not None:
            try:
                response = limiter._inject_headers(response, view_limit)
            except Exception:  # pragma: no cover - header injection is best effort
                logger.debug("Could not inject rate limit headers", exc_info=True)
        return response
