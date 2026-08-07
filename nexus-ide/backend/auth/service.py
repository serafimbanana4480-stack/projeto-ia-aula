"""Unified authentication, authorization and audit service.

Consolidates the previously scattered auth logic:
  - JWT token creation / validation      (was ``backend.middleware.auth``)
  - RBAC permission checks via DB roles  (was ``backend.persistence.db``)
  - Rate-limit awareness                 (was ``backend.middleware.rate_limit``)
  - Audit-log emission                   (was ``backend.observability.advanced_logging``)

All other modules should import from here rather than reaching directly
into ``middleware.auth`` or ``persistence.db`` for auth concerns.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from backend.config.settings import get_settings
from backend.persistence.db import user_has_permission

logger = logging.getLogger(__name__)


class AuthService:
    """Single entry point for authentication and authorization."""

    def __init__(self) -> None:
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # JWT
    # ------------------------------------------------------------------

    def create_access_token(
        self,
        data: dict[str, Any],
        expires_delta: timedelta | None = None,
    ) -> str:
        """Create a signed JWT access token."""
        to_encode = data.copy()
        expire = datetime.now(UTC) + (
            expires_delta or timedelta(minutes=self._settings.jwt_expiration_minutes)
        )
        to_encode.update({"exp": expire, "type": "access"})
        return jwt.encode(
            to_encode, self._settings.jwt_secret, algorithm=self._settings.jwt_algorithm
        )

    def create_refresh_token(
        self,
        data: dict[str, Any],
        expires_delta: timedelta | None = None,
    ) -> str:
        """Create a signed JWT refresh token (7-day default)."""
        to_encode = data.copy()
        expire = datetime.now(UTC) + (
            expires_delta or timedelta(days=7)
        )
        to_encode.update({"exp": expire, "type": "refresh"})
        return jwt.encode(
            to_encode, self._settings.jwt_secret, algorithm=self._settings.jwt_algorithm
        )

    def decode_token(self, token: str) -> dict[str, Any]:
        """Decode and validate a JWT token (access or refresh).

        Raises ``HTTPException`` on failure.
        """
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret,
                algorithms=[self._settings.jwt_algorithm],
            )
            return payload
        except JWTError as exc:
            logger.warning("JWT decode error: %s", exc)
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    # ------------------------------------------------------------------
    # RBAC
    # ------------------------------------------------------------------

    def has_permission(self, user_id: str, resource: str, action: str) -> bool:
        """Return True if the user has the given permission via DB roles."""
        try:
            return user_has_permission(user_id, resource, action)
        except Exception:
            logger.debug("RBAC check failed for user %s", user_id, exc_info=True)
            return False

    def is_admin(self, user_id: str) -> bool:
        """Return True if the user holds the admin role."""
        return self.has_permission(user_id, "admin", "*")

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def log_auth_event(
        self,
        event: str,
        user_id: str = "",
        **extra: Any,
    ) -> None:
        """Emit an authentication / authorization audit event."""
        try:
            from backend.observability.advanced_logging import get_structured_logger
            slog = get_structured_logger()
            slog.info(
                "auth_event",
                extra={
                    "event": event,
                    "user_id": user_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                    **extra,
                },
            )
        except Exception:
            logger.debug("Audit log failed for event %s", event, exc_info=True)


_auth_service: AuthService | None = None


def get_auth_service() -> AuthService:
    """Return the cached AuthService singleton."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
