"""Rate limiting middleware using slowapi for NEXUS IDE."""

from __future__ import annotations

import logging
import os

from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
)


def get_rate_limit_config() -> dict[str, str]:
    """Get rate limit configuration for different endpoint types.

    The limiter's global defaults remain disabled so deployments can opt in via
    the application settings, but callers (and the route decorators) still
    need a single, explicit policy catalogue.  Values can be overridden with
    environment variables without changing code between development and
    production.
    """
    defaults = {
        "auth": "5/minute",
        "chat": "60/minute",
        "files": "30/minute",
        "terminal": "30/minute",
        "dashboard": "200/minute",
        "default": "200/minute",
    }
    return {
        key: os.getenv(f"NEXUS_RATE_LIMIT_{key.upper()}", value)
        for key, value in defaults.items()
    }
