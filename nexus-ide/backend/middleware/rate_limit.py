"""Rate limiting for NEXUS IDE (slowapi).

Three things used to exist and none of them were connected to the running
application (audit P0-2):

* this module created a ``Limiter`` with ``default_limits=[]`` and never added
  ``SlowAPIMiddleware`` nor set ``app.state.limiter``;
* ``backend/orchestrator/limiter.py`` created a second, unrelated ``Limiter``
  that nothing imported;
* ``TenantManager`` (per-tenant budgets) was never instantiated.

This module is now the single source of truth: it builds the one ``Limiter``
the app uses, derives the limits from the environment variables that already
exist (``RATE_LIMIT_ENABLED`` / ``RATE_LIMIT_REQUESTS_PER_MINUTE`` /
``NEXUS_RATE_LIMIT_*``), and picks the storage backend from ``REDIS_URL`` when
one is configured — which is what ``.env`` already claimed happened.

The limiter is *always* constructed (route decorators need it at import time);
``enabled`` only decides whether a default global limit is applied.  Disabling
it therefore turns off the implicit per-IP limit without breaking the explicit
``@limiter.limit(...)`` decorators on individual routes.

:meth:`attach_to_app` must be used instead of ``app.add_middleware(
SlowAPIMiddleware)``: slowapi's own middleware discovers the endpoint by
iterating ``app.routes`` looking for an object with ``.endpoint``, and FastAPI
0.140 keeps included routers behind an ``_IncludedRouter`` node, so the lookup
returns ``None`` and every request is treated as exempt.  See
:func:`attach_to_app` for the compatible replacement.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

#: Policy catalogue used by :func:`get_rate_limit_config`.  Values are
#: overridable with ``NEXUS_RATE_LIMIT_<KEY>`` without a code change.
_DEFAULTS: dict[str, str] = {
    "auth": "5/minute",
    "chat": "60/minute",
    "llm": "30/minute",
    "files": "30/minute",
    "terminal": "30/minute",
    "tests": "5/minute",
    "dashboard": "200/minute",
    "default": "200/minute",
}

#: Tenant id used when a request carries no explicit tenant label.
DEFAULT_TENANT_ID = "default"


def _as_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    value = raw.strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _as_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    value = raw.strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid integer %r — using %d", raw, default)
        return default


def get_rate_limit_config() -> dict[str, str]:
    """Get rate limit configuration for different endpoint types.

    The limiter's global default is applied separately (see :func:`is_enabled`
    and :func:`default_limit`); this catalogue is the explicit policy that the
    route decorators and the tenant manager read.
    """
    return {
        key: os.getenv(f"NEXUS_RATE_LIMIT_{key.upper()}", value)
        for key, value in _DEFAULTS.items()
    }


def _settings_value(name: str) -> Any:
    try:
        from backend.config.settings import get_settings

        return getattr(get_settings(), name, None)
    except Exception:  # pragma: no cover - settings must never break the limiter
        logger.debug("Could not read %s from settings", name, exc_info=True)
        return None


def is_enabled() -> bool:
    """Whether the implicit global limit should be applied.

    ``RATE_LIMIT_ENABLED`` in the environment always wins (it is what an
    operator edits in ``.env``); otherwise the Pydantic setting is used.  An
    unset value defaults to *on* because the previous behaviour — silently
    unlimited — was the defect.
    """
    env_raw = os.environ.get("RATE_LIMIT_ENABLED")
    if env_raw is not None and env_raw.strip():
        return _as_bool(env_raw, True)
    configured = _settings_value("rate_limit_enabled")
    if isinstance(configured, bool):
        return configured
    if isinstance(configured, str) and configured.strip():
        return _as_bool(configured, True)
    return True


def requests_per_minute() -> int:
    """The global per-minute budget from ``RATE_LIMIT_REQUESTS_PER_MINUTE``."""
    env_raw = os.environ.get("RATE_LIMIT_REQUESTS_PER_MINUTE")
    if env_raw is not None and env_raw.strip():
        return max(1, _as_int(env_raw, 60))
    configured = _settings_value("rate_limit_requests_per_minute")
    if isinstance(configured, int) and configured > 0:
        return configured
    if isinstance(configured, str) and configured.strip():
        return max(1, _as_int(configured, 60))
    return 60


def default_limit() -> str | None:
    """``"<n>/minute"`` when limiting is on, ``None`` when it is off."""
    if not is_enabled():
        return None
    return f"{max(1, requests_per_minute())}/minute"


def storage_uri() -> str:
    """Honour ``REDIS_URL``; fall back to in-process memory.

    This is the behaviour ``.env`` already documented ("when REDIS_URL is set,
    rate limiting automatically uses Redis").  A Redis URL that cannot be used
    is reported and downgraded to memory rather than crashing the app.
    """
    redis_url = os.environ.get("REDIS_URL", "").strip()
    if not redis_url:
        return "memory://"
    if not redis_url.startswith(("redis://", "rediss://", "unix://")):
        logger.warning(
            "REDIS_URL=%r is not a Redis/socket URL — rate limiting stays in memory",
            redis_url[:40],
        )
        return "memory://"
    return redis_url


class NexusLimiter(Limiter):
    """A :class:`slowapi.Limiter` that tolerates plain-dict endpoints.

    slowapi's ``@limiter.limit`` wrapper calls
    ``self._inject_headers(kwargs.get("response"), ...)`` whenever the endpoint
    returns something that is not a ``Response``.  Every route in
    ``backend/core/routes/improvement.py`` — the six that carry
    ``@limiter.limit(...)`` — returns a plain ``dict`` and declares no
    ``response: Response`` parameter, so the stock behaviour raises
    ``Exception("parameter 'response' must be an instance of
    starlette.responses.Response")`` and the request ends as a **500**.

    That bug was invisible while the limiter was never wired into the app
    (P0-2): the decorators were dead code.  The moment the limiter is connected
    properly, every decorated route starts failing — so the injection must
    degrade to a no-op when there is no response object to attach headers to.
    That is also the semantically correct outcome: nothing to annotate.
    """

    def _inject_headers(self, response: Any, current_limit: Any) -> Any:
        from starlette.responses import Response

        if not isinstance(response, Response):
            return response
        return super()._inject_headers(response, current_limit)


def storage_is_reachable(uri: str) -> bool:
    """Whether *uri* can actually be used right now.

    A configured-but-dead ``REDIS_URL`` must not disable rate limiting: the
    limiter's storage would raise on every request and a naive
    "log and continue" turns the whole protection into a no-op — the exact
    "silently unlimited" failure the audit flagged.  So the backend is probed
    once at construction and the limiter falls back to in-process memory (with
    a loud warning) when Redis is not answering.
    """
    if uri == "memory://":
        return True
    try:
        from limits.storage import storage_from_string

        # ``check()`` is the library's own liveness probe; it returns False for
        # an unreachable server and raises only on a malformed URI.
        if not storage_from_string(uri).check():
            logger.warning(
                "Rate limit storage %s did not answer its liveness probe — "
                "falling back to in-process memory storage. Limits still apply, "
                "but they are not shared between workers.",
                uri.split("@")[-1],
            )
            return False
    except Exception as exc:
        logger.warning(
            "Rate limit storage %s is unusable (%s) — falling back to "
            "in-process memory storage. Limits still apply, but they are not "
            "shared between workers.",
            uri.split("@")[-1],
            exc,
        )
        return False
    return True


def build_limiter(
    *,
    key_func: Any = get_remote_address,
    default_limits: list[str] | None = None,
    storage_uri_override: str | None = None,
) -> Limiter:
    """Construct the application :class:`slowapi.Limiter`.

    Args:
        key_func: identity used for accounting (default: client IP).
        default_limits: the implicit global limits; derived from
            :func:`default_limit` when omitted.
        storage_uri_override: bypass :func:`storage_uri` entirely.  Used by
            tests that must not depend on a reachable Redis.
    """
    limits = list(default_limits) if default_limits is not None else []
    if not limits:
        limit = default_limit()
        if limit:
            limits = [limit]
    uri = storage_uri_override or storage_uri()
    if not storage_is_reachable(uri):
        uri = "memory://"
    limiter = NexusLimiter(
        key_func=key_func,
        default_limits=limits,
        storage_uri=uri,
        headers_enabled=True,
        # If Redis dies *after* startup, keep limiting from memory instead of
        # failing open on every request.  Must be a *list* (never ``None``):
        # slowapi iterates it in ``__init__`` and ``None`` raises TypeError at
        # import time, which would take the whole app down whenever
        # RATE_LIMIT_ENABLED=false produced an empty limit list.
        in_memory_fallback=list(limits),
        in_memory_fallback_enabled=bool(limits),
    )
    logger.info(
        "Rate limiter configured (default_limits=%s, storage=%s)",
        limits or ["<none>"],
        "redis" if uri != "memory://" else "memory",
    )
    return limiter


#: The single limiter instance used by the app and by every ``@limiter.limit``.
#: Route modules import this object at import time, so it must exist eagerly.
limiter: Limiter = build_limiter()


# ---------------------------------------------------------------------------
# Application wiring
# ---------------------------------------------------------------------------
def _iter_routes(routes: Any) -> Any:
    """Yield ``(path, endpoint)`` for every route, descending into routers.

    FastAPI >= 0.140 nests included routers in an ``_IncludedRouter`` node whose
    children are exposed through ``effective_candidates()``; older versions put
    :class:`starlette.routing.Route` objects directly in ``app.routes``.  Both
    shapes are handled so the limiter does not silently stop working on an
    upgrade.
    """
    for route in routes or []:
        candidates = getattr(route, "effective_candidates", None)
        if callable(candidates):
            for candidate in candidates():
                child_candidates = getattr(candidate, "effective_candidates", None)
                if callable(child_candidates):
                    yield from _iter_routes([candidate])
                    continue
                path = getattr(candidate, "path", "") or ""
                endpoint = getattr(candidate, "endpoint", None)
                if path and endpoint is not None:
                    yield path, endpoint
            continue
        path = getattr(route, "path", "") or ""
        endpoint = getattr(route, "endpoint", None)
        if path and endpoint is not None:
            yield path, endpoint
        nested = getattr(route, "routes", None)
        if nested:
            yield from _iter_routes(nested)


def build_endpoint_index(app: Any) -> dict[str, Any]:
    """``{concrete path: endpoint}`` for the app's routes."""
    index: dict[str, Any] = {}
    for path, endpoint in _iter_routes(getattr(app, "routes", [])):
        index.setdefault(path, endpoint)
    return index


def resolve_endpoint(index: dict[str, Any], path: str) -> Any:
    """Best-effort endpoint for *path* (exact match, then the unique pattern).

    Falls back to the first pattern match when several templates share a shape
    (``/api/x/{id}`` vs ``/api/x/{name}``): the only thing the limiter does with
    the endpoint is decide whether the route carries its own ``@limiter.limit``,
    so a wrong-but-close match only risks double counting, never a bypass.
    """
    if path in index:
        return index[path]
    parts = path.rstrip("/").split("/")
    candidates: list[Any] = []
    for template, endpoint in index.items():
        if template.count("/") != path.count("/"):
            continue
        template_parts = template.rstrip("/").split("/")
        if all(t.startswith("{") or t == p for t, p in zip(template_parts, parts, strict=False)):
            candidates.append(endpoint)
    if len(candidates) == 1:
        return candidates[0]
    return None


def attach_to_app(app: Any, *, limiter_instance: Limiter | None = None) -> Limiter:
    """Install the limiter on *app* (state, handler and middleware).

    ``app.state.limiter`` is what slowapi reads; the exception handler is what
    turns a breach into a **429** instead of a 500.
    """
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    from backend.middleware.rate_limit_middleware import NexusRateLimitMiddleware

    active = limiter_instance if limiter_instance is not None else limiter
    app.state.limiter = active
    # Built lazily by the middleware: at the time this function runs the app has
    # not mounted its routers yet, so an eager index would be empty.
    app.state.rate_limit_endpoint_index = {}
    app.state.rate_limit_routes_seen = -1
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(NexusRateLimitMiddleware, limiter=active)
    logger.info(
        "Rate limiting wired (default_limits=%s, storage=%s)",
        [str(limit) for limit in getattr(active, "_default_limits", []) or []],
        "redis" if getattr(active, "_storage_uri", "memory://") != "memory://" else "memory",
    )
    return active


def endpoint_index_for(app: Any) -> dict[str, Any]:
    """Return (and refresh when needed) the app's ``{path: endpoint}`` index.

    Lazily built because :func:`attach_to_app` runs before the routers are
    mounted, and refreshed whenever the top-level route count changes so a
    router included after startup is still limited.
    """
    routes = getattr(app, "routes", [])
    seen = len(routes)
    index = getattr(app.state, "rate_limit_endpoint_index", None)
    if index and getattr(app.state, "rate_limit_routes_seen", -1) == seen:
        return index
    index = build_endpoint_index(app)
    app.state.rate_limit_endpoint_index = index
    app.state.rate_limit_routes_seen = seen
    return index


# ---------------------------------------------------------------------------
# Per-tenant limiting
# ---------------------------------------------------------------------------
_tenant_manager_lock = threading.Lock()
_tenant_manager: Any = None


def get_tenant_manager() -> Any:
    """Return the process-wide :class:`TenantManager` singleton.

    Previously the class was never instantiated, so per-tenant limits were
    dead code.  The default tenant is always registered so a single-user
    local-first IDE is rate limited exactly like ``RATE_LIMIT_REQUESTS_PER_MINUTE``
    instead of being rejected for "unknown tenant".
    """
    global _tenant_manager
    if _tenant_manager is None:
        with _tenant_manager_lock:
            if _tenant_manager is None:
                from backend.pipeline.scalability import TenantConfig, TenantManager

                manager = TenantManager()
                manager.register(
                    TenantConfig(
                        tenant_id=DEFAULT_TENANT_ID,
                        name="default",
                        rate_limit_per_minute=max(1, requests_per_minute()),
                    )
                )
                _tenant_manager = manager
    return _tenant_manager


def reset_tenant_manager() -> None:
    """Test helper: drop the tenant manager singleton."""
    global _tenant_manager
    with _tenant_manager_lock:
        _tenant_manager = None


def check_tenant_rate_limit(tenant_id: str | None = None) -> bool:
    """Consume one token for *tenant_id*; ``False`` means over the limit.

    ``None``/empty is treated as :data:`DEFAULT_TENANT_ID` so an unlabelled
    request is still bounded.
    """
    if not is_enabled():
        return True
    return get_tenant_manager().check_rate_limit(tenant_id or DEFAULT_TENANT_ID)


def tenant_usage(tenant_id: str | None = None) -> dict[str, Any]:
    """Introspection helper for /api endpoints and tests."""
    return get_tenant_manager().get_usage_stats(tenant_id or DEFAULT_TENANT_ID)
