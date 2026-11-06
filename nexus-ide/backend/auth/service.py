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

import hashlib
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from backend.config.settings import get_settings
from backend.persistence.db import is_auth_revoked, save_auth_revocation, user_has_permission

logger = logging.getLogger(__name__)

#: How long a revoked token is remembered when it carries no expiry of its own.
DEFAULT_REVOCATION_TTL_SECONDS = 24 * 60 * 60

#: A session record has to outlive the refresh token it kills (7 days by
#: default), so it is kept for this long whatever the access token's own
#: expiry says.
SESSION_REVOCATION_TTL_SECONDS = 8 * 24 * 60 * 60

#: Upper bound on the number of remembered revocations.
MAX_REVOKED_TOKENS = 10_000


class TokenRevocationStore:
    """Process-local, TTL-bounded cache of revoked tokens and sessions.

    A JWT cannot say "I have been used up" or "the user logged out": both need
    a server-side record. This in-process cache is guarded by a lock because
    FastAPI serves requests from a thread pool. AuthService also persists
    one-way hashes in SQLite so revocations survive process restarts.

    Two kinds of record live here:

    * a *token* record, for a token that was spent (refresh rotation) or
      presented at logout;
    * a *session* record, for a login that was ended -- it kills the access
      token and the refresh token of that login together.

    Tokens are remembered as SHA-256 digests, so a memory dump does not hand
    out usable bearer credentials.
    """

    def __init__(self, ttl_seconds: int = DEFAULT_REVOCATION_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._revoked: dict[str, float] = {}

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _token_key(token: str) -> str:
        return f"token:{TokenRevocationStore._digest(token)}"

    @staticmethod
    def _session_key(session_id: str) -> str:
        return f"session:{session_id}"

    def revoke(self, token: str, expires_at: float | None = None) -> None:
        """Remember ``token`` as revoked.

        The record lives at least until the token would have expired anyway
        (``expires_at``, a unix timestamp), so a revoked token can never be
        replayed into a valid one.
        """
        if not token:
            return
        self._revoke(self._token_key(token), expires_at)

    def revoke_session(self, session_id: str, expires_at: float | None = None) -> None:
        """Remember a login (session) as ended.

        The record outlives the access token of that login on purpose: it
        also has to outlive the refresh token, which lives much longer.
        """
        if not session_id:
            return
        now = time.time()
        expiry = max(
            float(expires_at) if expires_at else 0.0,
            now + SESSION_REVOCATION_TTL_SECONDS,
        )
        self._revoke(self._session_key(session_id), expiry)

    def is_revoked(self, token: str) -> bool:
        """Whether ``token`` was revoked and the record has not expired yet."""
        if not token:
            return False
        return self._is_revoked(self._token_key(token))

    def is_session_revoked(self, session_id: str) -> bool:
        """Whether the login (session) was ended and the record is still live."""
        if not session_id:
            return False
        return self._is_revoked(self._session_key(session_id))

    def clear(self) -> None:
        """Clear this process cache; durable SQLite revocations remain intact."""
        with self._lock:
            self._revoked.clear()

    def _revoke(self, key: str, expires_at: float | None) -> None:
        """Store one revocation record."""
        now = time.time()
        expiry = float(expires_at) if expires_at else now + self._ttl_seconds
        if expiry <= now:
            expiry = now + self._ttl_seconds
        with self._lock:
            self._prune(now)
            self._revoked[key] = expiry
            self._trim()

    def _is_revoked(self, key: str) -> bool:
        """Whether one revocation record is live."""
        now = time.time()
        with self._lock:
            expiry = self._revoked.get(key)
            if expiry is None:
                return False
            if expiry <= now:
                del self._revoked[key]
                return False
            return True

    def _prune(self, now: float) -> None:
        """Drop the records whose token has expired anyway. Caller holds the lock."""
        expired = [digest for digest, expiry in self._revoked.items() if expiry <= now]
        for digest in expired:
            del self._revoked[digest]

    def _trim(self) -> None:
        """Keep the store bounded. Caller holds the lock."""
        while len(self._revoked) > MAX_REVOKED_TOKENS:
            oldest = min(self._revoked, key=lambda digest: self._revoked[digest])
            del self._revoked[oldest]


_revocation_store: TokenRevocationStore | None = None


def get_revocation_store() -> TokenRevocationStore:
    """Return the process-wide token revocation store singleton."""
    global _revocation_store
    if _revocation_store is None:
        _revocation_store = TokenRevocationStore()
    return _revocation_store


def new_token_id() -> str:
    """A unique identifier for one minted token."""
    import secrets as _secrets

    return _secrets.token_urlsafe(16)


def new_session_id() -> str:
    """A unique identifier for one login (access token + refresh token)."""
    import secrets as _secrets

    return _secrets.token_urlsafe(16)


class AuthService:
    """Single entry point for authentication and authorization."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._revocations = get_revocation_store()

    # ------------------------------------------------------------------
    # JWT
    # ------------------------------------------------------------------

    def create_access_token(
        self,
        data: dict[str, Any],
        expires_delta: timedelta | None = None,
        session_id: str | None = None,
    ) -> str:
        """Create a signed JWT access token.

        ``jti`` makes every token unique, so revoking one never takes a
        freshly minted twin with it.  ``session_id`` ties the access token to
        the refresh token of the same login, which is what lets a logout kill
        the whole session.
        """
        to_encode = data.copy()
        expire = datetime.now(UTC) + (
            expires_delta or timedelta(minutes=self._settings.jwt_expiration_minutes)
        )
        to_encode.update({"exp": expire, "type": "access", "jti": new_token_id()})
        if session_id:
            to_encode["sid"] = session_id
        return jwt.encode(
            to_encode, self._settings.jwt_secret, algorithm=self._settings.jwt_algorithm
        )

    def create_refresh_token(
        self,
        data: dict[str, Any],
        expires_delta: timedelta | None = None,
        session_id: str | None = None,
    ) -> str:
        """Create a signed JWT refresh token (7-day default)."""
        to_encode = data.copy()
        expire = datetime.now(UTC) + (
            expires_delta or timedelta(days=7)
        )
        to_encode.update({"exp": expire, "type": "refresh", "jti": new_token_id()})
        if session_id:
            to_encode["sid"] = session_id
        return jwt.encode(
            to_encode, self._settings.jwt_secret, algorithm=self._settings.jwt_algorithm
        )

    def decode_token(
        self, token: str, *, check_token_revocation: bool = True
    ) -> dict[str, Any]:
        """Decode and validate a JWT token (access or refresh).

        Raises ``HTTPException`` on failure.  A token that was revoked
        server-side (logout, refresh rotation) is refused here, so no caller
        can skip the check by decoding the token itself.
        """
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret,
                algorithms=[self._settings.jwt_algorithm],
            )
        except JWTError as exc:
            logger.warning("JWT decode error: %s", exc)
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if check_token_revocation and (
            self._revocations.is_revoked(token)
            or is_auth_revoked("token", token_digest)
        ):
            logger.info("Refused a revoked token")
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )

        session_id = payload.get("sid")
        session_digest = (
            hashlib.sha256(str(session_id).encode("utf-8")).hexdigest()
            if session_id
            else ""
        )
        if session_id and (
            self._revocations.is_session_revoked(str(session_id))
            or is_auth_revoked("session", session_digest)
        ):
            logger.info("Refused a token of an ended session")
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return payload

    # ------------------------------------------------------------------
    # Revocation
    # ------------------------------------------------------------------

    def revoke_token(self, token: str, expires_at: float | None = None) -> None:
        """Revoke ``token`` server-side.

        Used by logout (the presented token stops working) and by refresh
        rotation (the presented refresh token is spent).  ``expires_at`` is
        the token's own ``exp`` claim, so the record cannot outlive the
        token it revokes.
        """
        if not token:
            return
        now = time.time()
        expiry = float(expires_at) if expires_at else now + DEFAULT_REVOCATION_TTL_SECONDS
        if expiry <= now:
            expiry = now + DEFAULT_REVOCATION_TTL_SECONDS
        token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self._revocations.revoke(token, expiry)
        save_auth_revocation("token", token_digest, expiry)

    def revoke_session(self, session_id: str, expires_at: float | None = None) -> None:
        """End a login: its access token and its refresh token both die."""
        if not session_id:
            return
        now = time.time()
        expiry = max(
            float(expires_at) if expires_at else 0.0,
            now + SESSION_REVOCATION_TTL_SECONDS,
        )
        session_digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        self._revocations.revoke_session(session_id, expiry)
        save_auth_revocation("session", session_digest, expiry)

    def is_token_revoked(self, token: str) -> bool:
        """Whether ``token`` was revoked and is still inside its lifetime."""
        if self._revocations.is_revoked(token):
            return True
        token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return is_auth_revoked("token", token_digest)

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
