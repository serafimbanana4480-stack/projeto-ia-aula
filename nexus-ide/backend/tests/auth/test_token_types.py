"""A refresh token is not an access token.

The defect this file pins down
------------------------------
``decode_access_token`` delegated to ``decode_token``, which never looked at
the ``type`` claim.  A refresh token is signed with the same secret and
carries the same payload as an access token, so the 7-day refresh credential
worked as a full-privilege bearer token: ``GET /api/auth/me`` answered 200
for a refresh token.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException, status

from backend.middleware.auth import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)


def test_decode_access_token_rejects_refresh_token() -> None:
    """A refresh token must not authenticate a request."""
    refresh_token = create_refresh_token({"sub": "user123", "email": "user@example.com"})

    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(refresh_token)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Invalid token type"
    assert exc_info.value.headers.get("WWW-Authenticate") == "Bearer"


def test_decode_access_token_accepts_access_token() -> None:
    """An access token still decodes, and still says what it is."""
    access_token = create_access_token({"sub": "user123", "email": "user@example.com"})

    payload = decode_access_token(access_token)

    assert payload["sub"] == "user123"
    assert payload["email"] == "user@example.com"
    assert payload["type"] == "access"


def test_decode_refresh_token_rejects_access_token() -> None:
    """The other direction is refused too: an access token is not a refresh token."""
    access_token = create_access_token({"sub": "user123", "email": "user@example.com"})

    with pytest.raises(HTTPException) as exc_info:
        decode_refresh_token(access_token)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Invalid token type"


def test_decode_refresh_token_accepts_refresh_token() -> None:
    """The refresh path keeps working for the refresh token it is meant for."""
    refresh_token = create_refresh_token({"sub": "user123", "email": "user@example.com"})

    payload = decode_refresh_token(refresh_token)

    assert payload["type"] == "refresh"
    assert payload["sub"] == "user123"


def test_every_minted_token_carries_a_type_and_a_unique_id() -> None:
    """Tokens of one kind are never byte-identical.

    Rotation depends on it: revoking a spent refresh token must not take the
    replacement with it.
    """
    first = create_refresh_token({"sub": "user123", "email": "user@example.com"})
    second = create_refresh_token({"sub": "user123", "email": "user@example.com"})

    assert first != second
    assert decode_refresh_token(first)["jti"] != decode_refresh_token(second)["jti"]
