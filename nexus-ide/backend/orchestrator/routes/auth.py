"""Authentication routes for NEXUS IDE."""

import asyncio
import hashlib
import hmac
import logging
import secrets
import sqlite3
from datetime import timedelta
from typing import Any

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.config.settings import get_settings
from backend.core.secure_settings_store import decrypt_value, encrypt_value
from backend.middleware.auth import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    get_bearer_token,
    is_token_revoked,
    new_login_session,
    require_auth,
    revoke_session,
    revoke_token,
)
from backend.models.auth import (
    RefreshRequest,
    TokenResponse,
    UserLogin,
    UserRegister,
    UserResponse,
)
from backend.persistence.db import (
    create_user,
    ensure_dev_default_user,
    get_auth_refresh_exchange,
    get_user_by_email,
    get_user_with_password,
    save_auth_refresh_exchange,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _claim_expires_at(payload: dict[str, Any]) -> float | None:
    """The ``exp`` claim of a decoded token as a unix timestamp.

    Used to keep a revocation record alive exactly as long as the token it
    revokes, and not a second longer.
    """
    expires_at = payload.get("exp")
    if expires_at is None:
        return None
    try:
        return float(expires_at)
    except (TypeError, ValueError):
        return None


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(request: Request, user_data: UserRegister):
    """Register a new user.

    Self-registration is a development convenience and is disabled outside
    development (``ALLOW_SELF_REGISTRATION`` opts a deployment back in): an
    open registration endpoint hands an account -- and with it the
    tool-execution endpoints -- to anyone who can reach the API.

    Rate limited to 5 requests per minute to prevent abuse.
    """
    settings = get_settings()
    if not settings.allow_self_registration:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Self-registration is disabled on this deployment. "
                "Ask an administrator to create the account for you."
            ),
        )

    # Check if user already exists
    existing_user = get_user_by_email(user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists",
        )

    # Hash password using bcrypt directly (avoids passlib/bcrypt version issues)
    password_bytes = user_data.password.encode("utf-8")
    password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")

    # Create user
    user = create_user(
        username=user_data.email.split("@")[0],
        email=user_data.email,
        password_hash=password_hash,
        full_name=user_data.full_name,
    )

    # Create access token
    access_token_expires = timedelta(minutes=settings.jwt_expiration_minutes)
    session_id = new_login_session()
    access_token = create_access_token(
        data={"sub": user["id"], "email": user["email"]},
        expires_delta=access_token_expires,
        session_id=session_id,
    )
    refresh_token = create_refresh_token(
        data={"sub": user["id"], "email": user["email"]},
        session_id=session_id,
    )

    logger.info(f"New user registered: {user_data.email}")

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse(**user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(request: Request, user_data: UserLogin):
    """Login with email and password.

    Rate limited to 10 requests per minute to prevent brute force attacks.
    """
    # Get user with password hash. If the database is empty (common in dev/test
    # setups), create the default development user before validating credentials.
    user = await asyncio.to_thread(get_user_with_password, user_data.email)
    if not user:
        await asyncio.to_thread(ensure_dev_default_user)
        user = await asyncio.to_thread(get_user_with_password, user_data.email)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify password using bcrypt directly
    password_bytes = user_data.password.encode("utf-8")
    hash_bytes = user["password_hash"].encode("utf-8")
    if not await asyncio.to_thread(bcrypt.checkpw, password_bytes, hash_bytes):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if user is active
    if not user.get("is_active", 1):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    # Create access token
    settings = get_settings()
    access_token_expires = timedelta(minutes=settings.jwt_expiration_minutes)
    session_id = new_login_session()
    access_token = create_access_token(
        data={"sub": user["id"], "email": user["email"]},
        expires_delta=access_token_expires,
        session_id=session_id,
    )

    logger.info(f"User logged in: {user_data.email}")

    # Remove password hash before returning
    user_dict = dict(user)
    user_dict.pop("password_hash", None)

    refresh_token = create_refresh_token(
        data={"sub": user["id"], "email": user["email"]},
        session_id=session_id,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse(**user_dict),
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user(current_user: dict = Depends(require_auth)):
    """Get the current authenticated user profile.

    Requires valid JWT token.
    """
    current_user["user_id"]
    user = get_user_by_email(current_user["email"])

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserResponse(**user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, body: RefreshRequest):
    """Exchange a valid refresh token for a new access token (and refresh token).

    This keeps the user authenticated without forcing a new login when the
    short-lived access token expires.

    The refresh token is rotated and spent. A retry with the same
    ``Idempotency-Key`` recovers the exact encrypted response for that token;
    a replay with a different key is refused.
    """
    presented_token = body.refresh_token
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if not idempotency_key:
        # Keep compatibility with older clients while new clients provide a
        # stable key across retries.
        idempotency_key = secrets.token_urlsafe(32)
    if len(idempotency_key) > 255 or any(ord(char) < 0x20 for char in idempotency_key):
        raise HTTPException(status_code=400, detail="Invalid Idempotency-Key")

    # Signature and expiry are always checked. Token-revocation checking is
    # deferred so the route can distinguish a same-key retry from a replay.
    payload = decode_refresh_token(presented_token, allow_spent=True)
    refresh_jti = str(payload.get("jti") or "")
    expires_at = _claim_expires_at(payload)
    if not refresh_jti or expires_at is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_by_email(payload.get("email", ""))
    if not user or not user.get("is_active", 1):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )

    key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    exchange = get_auth_refresh_exchange(refresh_jti)
    if exchange:
        if hmac.compare_digest(str(exchange["idempotency_key_hash"]), key_hash):
            try:
                response_json = decrypt_value(
                    str(exchange["response_ciphertext"]),
                    key_name=f"auth_refresh_exchange:{refresh_jti}",
                )
                return TokenResponse.model_validate_json(response_json)
            except Exception as exc:
                logger.exception("Could not recover an idempotent refresh response")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="The refresh response could not be recovered securely",
                ) from exc
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Older spent tokens may predate the durable exchange table. Keep the
    # process-local revocation check as an additional guard for those tokens.
    if is_token_revoked(presented_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_settings()
    access_token_expires = timedelta(minutes=settings.jwt_expiration_minutes)
    # The new pair belongs to the same login as the presented one, so a
    # logout that ended that login still ends this one.
    session_id = payload.get("sid") or new_login_session()
    access_token = create_access_token(
        data={"sub": user["id"], "email": user["email"]},
        expires_delta=access_token_expires,
        session_id=session_id,
    )
    refresh_token = create_refresh_token(
        data={"sub": user["id"], "email": user["email"]},
        session_id=session_id,
    )

    user_dict = dict(user)
    user_dict.pop("password_hash", None)

    token_response = TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse(**user_dict),
    )
    ciphertext = encrypt_value(
        token_response.model_dump_json(),
        key_name=f"auth_refresh_exchange:{refresh_jti}",
    )

    try:
        save_auth_refresh_exchange(
            refresh_jti,
            key_hash,
            ciphertext,
            expires_at,
        )
    except sqlite3.IntegrityError as exc:
        # Another concurrent request won the unique-JTI claim. Only the same
        # idempotency key may recover its exact result.
        exchange = get_auth_refresh_exchange(refresh_jti)
        if exchange and hmac.compare_digest(str(exchange["idempotency_key_hash"]), key_hash):
            try:
                response_json = decrypt_value(
                    str(exchange["response_ciphertext"]),
                    key_name=f"auth_refresh_exchange:{refresh_jti}",
                )
                return TokenResponse.model_validate_json(response_json)
            except Exception as exc:
                logger.exception("Could not recover a concurrent refresh response")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="The refresh response could not be recovered securely",
                ) from exc
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # Persist first so a process restart or a lost response can recover the
    # same pair. The durable row now prevents any different-key replay.
    revoke_token(presented_token, expires_at=expires_at)
    return token_response


@router.post("/logout")
async def logout(
    current_user: dict[str, Any] = Depends(require_auth),
    token: str | None = Depends(get_bearer_token),
):
    """Log the current user out.

    Stateless JWTs need a server-side record for a logout to mean anything:
    the presented token is revoked, and every later attempt to use it is
    refused with 401.  The login the token belongs to is ended as well, so
    the refresh token of that login cannot be traded for a new one.
    """
    if token:
        payload = decode_access_token(token)
        revoke_token(token, expires_at=_claim_expires_at(payload))
        session_id = payload.get("sid")
        if session_id:
            revoke_session(str(session_id), expires_at=_claim_expires_at(payload))
    logger.info(f"User logged out: {current_user.get('email')}")
    return {"message": "Successfully logged out"}
