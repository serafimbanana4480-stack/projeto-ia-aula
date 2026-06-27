"""Authentication routes for NEXUS IDE."""

import logging
from datetime import timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.config.settings import get_settings
from backend.middleware.auth import create_access_token, require_auth
from backend.middleware.rate_limit import limiter
from backend.models.auth import (
    TokenResponse,
    UserLogin,
    UserRegister,
    UserResponse,
)
from backend.persistence.db import (
    create_user,
    get_user_by_email,
    get_user_with_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
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

    logger.info(f"New user registered: {user_data.email}")

    return TokenResponse(
        access_token=access_token,
        user=UserResponse(**user),
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("30/minute")
async def login(request: Request, user_data: UserLogin):
    """Login with email and password.

    Rate limited to 10 requests per minute to prevent brute force attacks.
    """
    # Get user with password hash
    try:
        user = get_user_with_password(user_data.email)
    except Exception:
        logger.exception("Database error during login (missing schema?)")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A base de dados não está inicializada. Tente novamente ou contacte o administrador.",
        )
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

    return TokenResponse(
        access_token=access_token,
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
