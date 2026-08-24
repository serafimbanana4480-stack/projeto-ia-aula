"""Base middleware class for the Nexus IDE backend.

All custom middleware should inherit from this class and implement the
``process_request`` and ``process_response`` hooks.
"""

from typing import Callable, Any, Awaitable
from starlette.middleware.base import BaseHTTPMiddleware


class BaseHTTPMiddleware(BaseHTTPMiddleware):
    """Base HTTP middleware that can be extended with request/response hooks."""

    async def dispatch(self, request: Any, call_next: Callable[[Any], Awaitable[Any]]) -> Any:
        """Hook called for each request.

        Override ``process_request`` and ``process_response`` in subclasses.
        """
        # Example placeholder hook
        response = await call_next(request)
        return response