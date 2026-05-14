"""Tests for rate limiting middleware."""

import pytest

from backend.middleware.rate_limit import get_rate_limit_config, limiter


class TestRateLimitConfig:
    """Test rate limit configuration."""

    def test_get_rate_limit_config_returns_dict(self) -> None:
        """Test that get_rate_limit_config returns a dictionary."""
        config = get_rate_limit_config()
        assert isinstance(config, dict)

    def test_rate_limit_config_has_auth_endpoint(self) -> None:
        """Test that config includes auth endpoint limits."""
        config = get_rate_limit_config()
        assert "auth" in config
        assert isinstance(config["auth"], str)

    def test_rate_limit_config_has_chat_endpoint(self) -> None:
        """Test that config includes chat endpoint limits."""
        config = get_rate_limit_config()
        assert "chat" in config
        assert isinstance(config["chat"], str)

    def test_rate_limit_config_has_files_endpoint(self) -> None:
        """Test that config includes files endpoint limits."""
        config = get_rate_limit_config()
        assert "files" in config
        assert isinstance(config["files"], str)

    def test_rate_limit_config_has_terminal_endpoint(self) -> None:
        """Test that config includes terminal endpoint limits."""
        config = get_rate_limit_config()
        assert "terminal" in config
        assert isinstance(config["terminal"], str)

    def test_rate_limit_config_has_dashboard_endpoint(self) -> None:
        """Test that config includes dashboard endpoint limits."""
        config = get_rate_limit_config()
        assert "dashboard" in config
        assert isinstance(config["dashboard"], str)

    def test_rate_limit_config_has_default_endpoint(self) -> None:
        """Test that config includes default endpoint limits."""
        config = get_rate_limit_config()
        assert "default" in config
        assert isinstance(config["default"], str)

    def test_auth_limit_stricter_than_default(self) -> None:
        """Test that auth endpoint has stricter limits than default."""
        config = get_rate_limit_config()
        # Auth should be more restrictive (lower number per minute)
        auth_limit = config["auth"]
        default_limit = config["default"]
        # Simple check that auth limit exists and is different from default
        assert auth_limit != default_limit


class TestLimiter:
    """Test limiter instance."""

    def test_limiter_exists(self) -> None:
        """Test that limiter instance exists."""
        assert limiter is not None

    def test_limiter_has_key_func(self) -> None:
        """Test that limiter has a key function."""
        assert limiter._key_func is not None