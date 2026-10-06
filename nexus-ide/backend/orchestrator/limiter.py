"""Backwards-compatible alias for the application rate limiter.

This module used to build a *second* ``slowapi`` :class:`Limiter` with a
hard-coded ``30/minute`` default that nothing ever imported, so
``@limiter.limit(...)`` decorators bound to it could not work.  It now
re-exports the single limiter owned by :mod:`backend.middleware.rate_limit`,
which is the instance the app wires into ``app.state.limiter`` and attaches
:class:`slowapi.middleware.SlowAPIMiddleware` for.
"""
from slowapi import Limiter

from backend.middleware.rate_limit import limiter

__all__ = ["Limiter", "limiter"]
