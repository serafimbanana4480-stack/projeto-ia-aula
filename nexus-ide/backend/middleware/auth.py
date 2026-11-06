"""JWT Authentication middleware for NEXUS IDE.

Delegates to ``backend.auth.service.AuthService`` for token lifecycle and
authorization checks so that all auth concerns flow through a single point.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.auth.service import get_auth_service, new_session_id

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None,
    session_id: str | None = None,
) -> str:
    """Create a JWT access token."""
    return get_auth_service().create_access_token(data, expires_delta, session_id)


def create_refresh_token(
    data: dict,
    expires_delta: timedelta | None = None,
    session_id: str | None = None,
) -> str:
    """Create a long-lived JWT refresh token."""
    return get_auth_service().create_refresh_token(data, expires_delta, session_id)


def new_login_session() -> str:
    """A session id tying an access token to the refresh token of one login."""
    return new_session_id()


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token.

    The ``type`` claim is what tells the two token kinds apart, and it is
    checked here on purpose: a refresh token is signed with the same secret
    and carries the same payload, so accepting one here would turn the
    7-day refresh credential into a full-privilege bearer token.
    """
    payload = get_auth_service().decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def decode_refresh_token(token: str, *, allow_spent: bool = False) -> dict:
    """Decode a refresh JWT, optionally deferring spent-token checks to its route.

    The refresh endpoint permits a spent token only long enough to look up its
    persisted idempotency result. Other callers keep the default single-use
    revocation check.
    """
    payload = get_auth_service().decode_token(
        token, check_token_revocation=not allow_spent
    )
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def revoke_token(token: str, expires_at: float | None = None) -> None:
    """Revoke ``token`` server-side so it is refused from now on."""
    get_auth_service().revoke_token(token, expires_at)


def revoke_session(session_id: str, expires_at: float | None = None) -> None:
    """End a login: its access token and its refresh token both stop working."""
    get_auth_service().revoke_session(session_id, expires_at)


def is_token_revoked(token: str) -> bool:
    """Whether ``token`` was revoked server-side."""
    return get_auth_service().is_token_revoked(token)


async def get_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str | None:
    """The raw bearer token of the request, if one was presented.

    Logout needs the token itself -- not the identity it carries -- to be
    able to revoke it.
    """
    if credentials is None:
        return None
    return credentials.credentials


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
