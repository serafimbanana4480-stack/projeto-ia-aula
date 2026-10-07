"""Tests for TokenManager JWT identity and permissions."""
from __future__ import annotations

from datetime import UTC

import pytest
from jose.exceptions import ExpiredSignatureError, JWTError

from backend.sandbox.auth import (
    Permission,
    Role,
    TokenManager,
    check_permission,
)


class TestTokenManager:
    @pytest.fixture
    def manager(self) -> TokenManager:
        return TokenManager(secret_key="test-secret-key-12345", default_ttl=300)

    def test_issue_token(self, manager: TokenManager) -> None:
        token = manager.issue("agent-1", "developer", "sandbox-1")
        assert isinstance(token, str)
        assert len(token) > 10

    def test_verify_valid_token(self, manager: TokenManager) -> None:
        token = manager.issue("agent-1", "developer", "sandbox-1")
        identity = manager.verify(token)
        assert identity.agent_id == "agent-1"
        assert identity.role == Role.DEVELOPER
        assert identity.sandbox_id == "sandbox-1"
        assert identity.token_jti is not None

    def test_revoke_token(self, manager: TokenManager) -> None:
        token = manager.issue("agent-1", "developer", "sandbox-1")
        manager.revoke(token)
        # Was `pytest.raises(Exception)`, which asserted nothing: any error at
        # all passed, including a TypeError from a broken verify(). The guard
        # raises JWTError("Token has been revoked") -- see auth.py:150.
        with pytest.raises(JWTError, match="revoked"):
            manager.verify(token)

    def test_revoke_all_for_agent(self, manager: TokenManager) -> None:
        token = manager.issue("agent-1", "developer", "sandbox-1")
        manager.revoke_all_for_agent("agent-1")
        with pytest.raises(JWTError, match="revoked"):
            manager.verify(token)

    def test_refresh_token(self, manager: TokenManager) -> None:
        old_token = manager.issue("agent-1", "developer", "sandbox-1")
        new_token = manager.refresh(old_token)
        assert new_token != old_token
        # Old token should be revoked
        with pytest.raises(JWTError, match="revoked"):
            manager.verify(old_token)
        # New token should be valid
        identity = manager.verify(new_token)
        assert identity.agent_id == "agent-1"

    def test_verify_expired_token(self, manager: TokenManager) -> None:
        # The TokenManager uses a 60s leeway for clock skew.
        # To test expiration we issue a token with a past exp claim directly.
        from datetime import datetime, timedelta

        from jose import jwt
        now = datetime.now(UTC)
        claims = {
            "sub": "agent-1",
            "role": "developer",
            "sandbox_id": "sandbox-1",
            "iat": now.timestamp(),
            "exp": (now - timedelta(seconds=65)).timestamp(),
            "jti": "test-jti-001",
            "type": "agent",
        }
        expired_token = jwt.encode(claims, manager._secret, algorithm="HS256")
        # Was `pytest.raises(Exception)`. Expiry raises ExpiredSignatureError,
        # a JWTError subclass; naming it keeps the test from silently accepting
        # an unrelated failure such as a signature mismatch.
        with pytest.raises(ExpiredSignatureError):
            manager.verify(expired_token)


class TestPermissions:
    def test_admin_has_all_permissions(self) -> None:
        assert check_permission(Role.ADMIN, Permission.EXECUTE_CODE) is True
        assert check_permission(Role.ADMIN, Permission.INSTALL_PACKAGES) is True
        assert check_permission(Role.ADMIN, Permission.ACCESS_NETWORK) is True
        assert check_permission(Role.ADMIN, Permission.READ_SECRETS) is True

    def test_developper_cannot_access_network(self) -> None:
        assert check_permission(Role.DEVELOPER, Permission.EXECUTE_CODE) is True
        assert check_permission(Role.DEVELOPER, Permission.INSTALL_PACKAGES) is True
        assert check_permission(Role.DEVELOPER, Permission.ACCESS_NETWORK) is False
        assert check_permission(Role.DEVELOPER, Permission.READ_SECRETS) is False

    def test_readonly_limited(self) -> None:
        assert check_permission(Role.READONLY, Permission.EXECUTE_CODE) is True
        assert check_permission(Role.READONLY, Permission.INSTALL_PACKAGES) is False
        assert check_permission(Role.READONLY, Permission.ACCESS_NETWORK) is False

    def test_check_by_string(self) -> None:
        assert check_permission("admin", Permission.MODIFY_SYSTEM) is True
        assert check_permission("readonly", Permission.INSTALL_PACKAGES) is False
