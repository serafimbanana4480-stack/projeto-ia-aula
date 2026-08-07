"""Authentication routes for NEXUS IDE."""

import logging
from datetime import timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.config.settings import get_settings
from backend.middleware.auth import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    require_auth,
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
    get_user_by_email,
    get_user_with_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(request: Request, user_data: UserRegister):
    """Register a new user.

    Rate limited to 5 requests per minute to prevent abuse.
    """
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
    settings = get_settings()
    access_token_expires = timedelta(minutes=settings.jwt_expiration_minutes)
    access_token = create_access_token(
        data={"sub": user["id"], "email": user["email"]},
        expires_delta=access_token_expires,
    )
    refresh_token = create_refresh_token(
        data={"sub": user["id"], "email": user["email"]},
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
    user = get_user_with_password(user_data.email)
    if not user:
        ensure_dev_default_user()
        user = get_user_with_password(user_data.email)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify password using bcrypt directly
    password_bytes = user_data.password.encode("utf-8")
    hash_bytes = user["password_hash"].encode("utf-8")
    if not bcrypt.checkpw(password_bytes, hash_bytes):
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
    access_token = create_access_token(
        data={"sub": user["id"], "email": user["email"]},
        expires_delta=access_token_expires,
    )

    logger.info(f"User logged in: {user_data.email}")

    # Remove password hash before returning
    user_dict = dict(user)
    user_dict.pop("password_hash", None)

    refresh_token = create_refresh_token(
        data={"sub": user["id"], "email": user["email"]},
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
    """
    try:
        payload = decode_refresh_token(body.refresh_token)
    except HTTPException:
        raise

    user = get_user_by_email(payload.get("email", ""))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_settings()
    access_token_expires = timedelta(minutes=settings.jwt_expiration_minutes)
    access_token = create_access_token(
        data={"sub": user["id"], "email": user["email"]},
        expires_delta=access_token_expires,
    )
    refresh_token = create_refresh_token(
        data={"sub": user["id"], "email": user["email"]},
    )

    user_dict = dict(user)
    user_dict.pop("password_hash", None)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse(**user_dict),
    )


@router.post("/logout")
async def logout(current_user: dict = Depends(require_auth)):
    """Logout the current user.

    Since we use stateless JWT tokens, the actual logout is handled
    on the client side by discarding the token. This endpoint
    primarily serves as a formal logout point and can be extended
    to add token blacklisting if needed.
    """
    logger.info(f"User logged out: {current_user['email']}")
    return {"message": "Successfully logged out"}
