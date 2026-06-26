"""JWT Authentication middleware for NEXUS IDE."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from backend.config.settings import get_settings

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=30)
    to_encode.update({"exp": expire})

    settings = get_settings()
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError as e:
        logger.warning(f"JWT decode error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """Get the current authenticated user from JWT token.

    This dependency can be used to protect endpoints that require authentication.
    If no token is provided, it returns None (for optional auth).
    If an invalid token is provided, it raises an HTTP 401 exception.
    """
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
    """Require authentication for an endpoint.

    Use this dependency for endpoints that MUST have authentication.
    Raises HTTP 401 if no valid token is provided.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


async def require_admin(current_user: dict = Depends(require_auth)) -> dict:
    """Require admin privileges for an endpoint.

    Checks that the authenticated user has an admin-like email or the
    ``admin`` role assigned.  Falls back to checking the user's email
    against the configured admin email or a hard-coded default so that
    the local default admin (``admin@nexus-ide.com``) always has access.
    """
    user_id = current_user.get("user_id", "")
    email = current_user.get("email", "")

    # Allow the configured default admin email and development fallback
    admin_email = "admin@nexus-ide.com"
    if email and email == admin_email:
        return current_user

    # Check via RBAC permission
    try:
        from backend.persistence.db import user_has_permission

        if user_has_permission(user_id, resource="admin", action="*"):
            return current_user
    except Exception:
        pass

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin privileges required",
    )
