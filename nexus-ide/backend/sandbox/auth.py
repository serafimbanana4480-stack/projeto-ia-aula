"""Sandbox Auth — JWT identity and token management for agent zero-trust.

Issues short-lived JWT tokens (default 15 min) for agent identities.
Supports revocation, refresh, and role-based permissions.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

try:
    from jose import JWTError, jwt
except ImportError:
    jwt = None  # type: ignore
    JWTError = Exception  # type: ignore

logger = logging.getLogger(__name__)


class Permission(str, Enum):
    """Permissions for agent roles."""

    EXECUTE_CODE = "execute_code"
    INSTALL_PACKAGES = "install_packages"
    ACCESS_NETWORK = "access_network"
    MODIFY_SYSTEM = "modify_system"
    READ_SECRETS = "read_secrets"


class Role(str, Enum):
    """Agent roles with different permission levels."""

    ADMIN = "admin"
    DEVELOPER = "developer"
    READONLY = "readonly"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: {
        Permission.EXECUTE_CODE,
        Permission.INSTALL_PACKAGES,
        Permission.ACCESS_NETWORK,
        Permission.MODIFY_SYSTEM,
        Permission.READ_SECRETS,
    },
    Role.DEVELOPER: {
        Permission.EXECUTE_CODE,
        Permission.INSTALL_PACKAGES,
    },
    Role.READONLY: {
        Permission.EXECUTE_CODE,
    },
}


@dataclass
class AgentIdentity:
    """Identity of an authenticated agent."""

    agent_id: str
    role: Role
    sandbox_id: str
    issued_at: datetime
    expires_at: datetime
    token_jti: str


class TokenManager:
    """Manages JWT issuance, verification, and revocation for agent identities."""

    def __init__(
        self,
        secret_key: str | None = None,
        default_ttl: int = 900,  # 15 minutes
    ) -> None:
        if jwt is None:
            raise ImportError(
                "python-jose is required for JWT support. "
                "Install: pip install python-jose[cryptography]"
            )
        self._secret = secret_key or uuid.uuid4().hex
        self._default_ttl = default_ttl
        # In-memory revocation store (use Redis in production)
        self._revoked_jtis: set[str] = set()
        self._revoked_agents: set[str] = set()

    def issue(
        self,
        agent_id: str,
        role: str,
        sandbox_id: str,
        ttl: int | None = None,
    ) -> str:
        """Issue a new JWT for an agent.

        Args:
            agent_id: Unique agent identifier.
            role: Agent role (admin, developer, readonly).
            sandbox_id: Target sandbox identifier.
            ttl: Token time-to-live in seconds (default: 15 min).

        Returns:
            JWT token string.
        """
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=ttl or self._default_ttl)
        jti = str(uuid.uuid4())

        claims = {
            "sub": agent_id,
            "role": role,
            "sandbox_id": sandbox_id,
            "iat": now,
            "exp": expires,
            "jti": jti,
            "type": "agent",
        }

        token = jwt.encode(claims, self._secret, algorithm="HS256")
        logger.debug("Issued JWT for agent %s (jti=%s)", agent_id, jti)
        return token

    def verify(self, token: str) -> AgentIdentity:
        """Verify a JWT and return the agent identity.

        Args:
            token: JWT token string.

        Returns:
            AgentIdentity if valid.

        Raises:
            JWTError: If token is invalid, expired, or revoked.
        """
        claims = jwt.decode(
            token,
            self._secret,
            algorithms=["HS256"],
            options={"leeway": 60},  # 60s clock skew leeway
        )

        jti = claims.get("jti")
        agent_id = claims.get("sub")

        # Check revocation
        if jti in self._revoked_jtis:
            raise JWTError("Token has been revoked")
        if agent_id in self._revoked_agents:
            raise JWTError("Agent has been revoked")

        return AgentIdentity(
            agent_id=agent_id,
            role=Role(claims.get("role", "readonly")),
            sandbox_id=claims.get("sandbox_id", ""),
            issued_at=claims.get("iat", datetime.now(UTC)),
            expires_at=claims.get("exp", datetime.now(UTC)),
            token_jti=jti,
        )

    def revoke(self, token: str) -> None:
        """Revoke a specific token by its JTI."""
        try:
            claims = jwt.decode(token, self._secret, algorithms=["HS256"])
            jti = claims.get("jti")
            if jti:
                self._revoked_jtis.add(jti)
                logger.info("Revoked token jti=%s", jti)
        except JWTError:
            pass

    def revoke_all_for_agent(self, agent_id: str) -> None:
        """Revoke all tokens for an agent."""
        self._revoked_agents.add(agent_id)
        logger.info("Revoked all tokens for agent %s", agent_id)

    def refresh(self, token: str, ttl: int | None = None) -> str:
        """Refresh a valid token by issuing a new one and revoking the old.

        Args:
            token: Existing valid JWT.
            ttl: New token TTL.

        Returns:
            New JWT token string.
        """
        identity = self.verify(token)
        self.revoke(token)
        return self.issue(
            identity.agent_id,
            identity.role.value,
            identity.sandbox_id,
            ttl=ttl,
        )


def check_permission(role: Role | str, permission: Permission) -> bool:
    """Check if a role has a specific permission.

    Args:
        role: Agent role or role string.
        permission: Permission to check.

    Returns:
        True if the role has the permission.
    """
    if isinstance(role, str):
        role = Role(role)
    return permission in ROLE_PERMISSIONS.get(role, set())
