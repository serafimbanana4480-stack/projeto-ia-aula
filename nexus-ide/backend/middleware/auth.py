"""JWT Authentication middleware for NEXUS IDE.

Delegates to ``backend.auth.service.AuthService`` for token lifecycle and
authorization checks so that all auth concerns flow through a single point.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.auth.service import get_auth_service

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    return get_auth_service().create_access_token(data, expires_delta)


def create_refresh_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a long-lived JWT refresh token."""
    return get_auth_service().create_refresh_token(data, expires_delta)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token."""
    return get_auth_service().decode_token(token)


def decode_refresh_token(token: str) -> dict:
    """Decode and validate a JWT refresh token (must have type=refresh)."""
    payload = get_auth_service().decode_token(token)
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """Get the current authenticated user from JWT token."""
    if credentials is None:
        return None

    token = credentials.credentials
    payload = decode_access_token(token)

    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "user_id": user_id,
        "email": payload.get("email"),
        "exp": payload.get("exp"),
    }


async def require_auth(current_user: dict = Depends(get_current_user)) -> dict:
    """Require authentication for an endpoint."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


async def require_admin(current_user: dict = Depends(require_auth)) -> dict:
    """Require admin privileges for an endpoint.

    Authorization is delegated to the DB-backed RBAC system via AuthService.
    There is no hard-coded email fallback.
    """
    user_id = current_user.get("user_id", "")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )

    if get_auth_service().is_admin(user_id):
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin privileges required",
    )
