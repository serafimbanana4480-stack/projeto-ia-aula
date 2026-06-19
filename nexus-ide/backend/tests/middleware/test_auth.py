"""Tests for authentication middleware."""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, status

from backend.middleware.auth import (
    create_access_token,
    decode_access_token,
    get_current_user,
    require_auth,
)


class TestCreateAccessToken:
    """Test JWT token creation."""

    def test_create_token_default_expiration(self, mock_settings: MagicMock) -> None:
        """Test token creation with default expiration."""
        data = {"sub": "user123", "email": "user@example.com"}
        token = create_access_token(data)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_token_custom_expiration(self, mock_settings: MagicMock) -> None:
        """Test token creation with custom expiration."""
        data = {"sub": "user123", "email": "user@example.com"}
        expires_delta = timedelta(hours=1)
        token = create_access_token(data, expires_delta=expires_delta)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_token_includes_exp_claim(self, mock_settings: MagicMock) -> None:
        """Test that token includes expiration claim."""
        data = {"sub": "user123"}
        token = create_access_token(data)
        payload = decode_access_token(token)
        assert "exp" in payload


class TestDecodeAccessToken:
    """Test JWT token decoding."""

    def test_decode_valid_token(self, mock_settings: MagicMock) -> None:
        """Test decoding a valid token."""
        data = {"sub": "user123", "email": "user@example.com"}
        token = create_access_token(data)
        payload = decode_access_token(token)
        assert payload["sub"] == "user123"
        assert payload["email"] == "user@example.com"

    def test_decode_invalid_token_raises_http_exception(self, mock_settings: MagicMock) -> None:
        """Test that decoding an invalid token raises HTTPException."""
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token("invalid-token")
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Could not validate credentials" in exc_info.value.detail


class TestGetCurrentUser:
    """Test get_current_user dependency."""

    @pytest.mark.asyncio
    async def test_no_credentials_returns_none(self, mock_settings: MagicMock) -> None:
        """Test that missing credentials returns None."""
        user = await get_current_user(credentials=None)
        assert user is None

    @pytest.mark.asyncio
    async def test_valid_token_returns_user(self, mock_settings: MagicMock) -> None:
        """Test that valid token returns user data."""
        data = {"sub": "user123", "email": "user@example.com"}
        token = create_access_token(data)

        from fastapi.security import HTTPAuthorizationCredentials

        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=token,
        )

        user = await get_current_user(credentials)
        assert user is not None
        assert user["user_id"] == "user123"
        assert user["email"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_invalid_token_raises_http_exception(self, mock_settings: MagicMock) -> None:
        """Test that invalid token raises HTTPException."""
        from fastapi.security import HTTPAuthorizationCredentials

        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="invalid-token",
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_token_without_sub_raises_http_exception(self, mock_settings: MagicMock) -> None:
        """Test that token without sub claim raises HTTPException."""
        data = {"email": "user@example.com"}  # Missing sub
        token = create_access_token(data)

        from fastapi.security import HTTPAuthorizationCredentials

        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=token,
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestRequireAuth:
    """Test require_auth dependency."""

    @pytest.mark.asyncio
    async def test_none_user_raises_http_exception(self) -> None:
        """Test that None user raises HTTPException."""
        with pytest.raises(HTTPException) as exc_info:
            await require_auth(current_user=None)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Authentication required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_valid_user_returns_user(self) -> None:
        """Test that valid user is returned."""
        user = {"user_id": "user123", "email": "user@example.com"}
        result = await require_auth(current_user=user)
        assert result == user
