"""Server-side revocation: a token that was spent or logged out stays dead.

The defect this file pins down
------------------------------
``POST /api/auth/refresh`` minted a new refresh token and left the old one
valid for its full 7 days, and ``POST /api/auth/logout`` was an explicit
no-op -- the token kept working afterwards.  Both needed a server-side record,
which is what the revocation store is.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi import HTTPException, status

from backend.auth.service import TokenRevocationStore, get_revocation_store
from backend.middleware.auth import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    revoke_session,
    revoke_token,
)


def test_a_revoked_access_token_is_refused() -> None:
    """Revoking is what makes a logout mean something."""
    token = create_access_token({"sub": "user123", "email": "user@example.com"})
    assert decode_access_token(token)["sub"] == "user123"

    revoke_token(token)

    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(token)
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Token has been revoked"


def test_a_revoked_refresh_token_is_refused() -> None:
    """A spent refresh token cannot be replayed."""
    token = create_refresh_token({"sub": "user123", "email": "user@example.com"})

    revoke_token(token)

    with pytest.raises(HTTPException) as exc_info:
        decode_refresh_token(token)
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Token has been revoked"


def test_revoking_a_session_kills_both_of_its_tokens() -> None:
    """Ending a login takes its access token and its refresh token with it."""
    from backend.middleware.auth import new_login_session

    session_id = new_login_session()
    access_token = create_access_token(
        {"sub": "user123", "email": "user@example.com"}, session_id=session_id
    )
    refresh_token = create_refresh_token(
        {"sub": "user123", "email": "user@example.com"}, session_id=session_id
    )

    revoke_session(session_id)

    for token, decode in (
        (access_token, decode_access_token),
        (refresh_token, decode_refresh_token),
    ):
        with pytest.raises(HTTPException) as exc_info:
            decode(token)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Session has been revoked"


def test_the_store_keeps_no_usable_credential() -> None:
    """A memory dump must not hand out bearer credentials."""
    store = TokenRevocationStore()
    token = "a-very-secret-token-value"

    store.revoke(token)

    assert store.is_revoked(token) is True
    assert token not in repr(store.__dict__)


def test_the_store_forgets_a_record_once_it_expired() -> None:
    """A revocation record does not outlive the token it revokes."""
    store = TokenRevocationStore(ttl_seconds=0)
    token = "a-very-secret-token-value"

    store.revoke(token, expires_at=time.time() - 1)
    time.sleep(0.01)

    assert store.is_revoked(token) is False


def test_the_store_is_safe_to_use_from_several_threads() -> None:
    """FastAPI serves requests from a thread pool, so the store has a lock."""
    store = TokenRevocationStore()
    tokens = [f"token-{index}" for index in range(200)]
    errors: list[Exception] = []

    def worker(chunk: list[str]) -> None:
        try:
            for token in chunk:
                store.revoke(token)
                store.is_revoked(token)
        except Exception as exc:  # pragma: no cover - only on a real race
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(tokens[i::4],)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert all(store.is_revoked(token) for token in tokens)


def test_the_store_is_a_process_wide_singleton() -> None:
    """The route and the middleware have to see the same records."""
    assert get_revocation_store() is get_revocation_store()
