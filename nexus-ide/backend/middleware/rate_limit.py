"""Rate limiting middleware using slowapi for NEXUS IDE."""

from __future__ import annotations

import logging
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

logger = logging.getLogger(__name__)

# Create limiter instance
# Uses IP address as the key for rate limiting
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute", "1000/hour"],  # Default limits for all endpoints
    storage_uri="memory://",  # In-memory storage (for production, use Redis)
)


def get_rate_limit_config() -> dict[str, str]:
    """Get rate limit configuration for different endpoint types.
    
    Returns a dictionary with rate limit configurations for different
    types of endpoints (auth, chat, etc.).
    """
    return {
        # Authentication endpoints - stricter limits
        "auth": "5/minute",
        # Chat endpoints - moderate limits
        "chat": "60/minute",
        # File operations - moderate limits
        "files": "30/minute",
        # Terminal operations - moderate limits
        "terminal": "30/minute",
        # Dashboard - higher limits
        "dashboard": "200/minute",
        # Default limits
        "default": "200/minute",
    }