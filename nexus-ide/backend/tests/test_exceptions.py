"""Tests for backend exceptions."""

from backend.exceptions import (
    AgentError,
    ConfigurationError,
    DatabaseError,
    NexusError,
    OllamaConnectionError,
    OllamaModelError,
    PromptInjectionError,
    RateLimitError,
    RoutingError,
    ValidationError,
)


class TestNexusError:
    """Test the base NexusError exception."""

    def test_basic_instantiation(self) -> None:
        """Test that NexusError can be instantiated with a message."""
        error = NexusError("Test error")
        assert error.message == "Test error"
        assert error.details == {}
        assert str(error) == "Test error"

    def test_instantiation_with_details(self) -> None:
        """Test that NexusError can be instantiated with details."""
        error = NexusError("Test error", details={"key": "value"})
        assert error.message == "Test error"
        assert error.details == {"key": "value"}
        assert str(error) == "Test error"

    def test_instantiation_with_none_details(self) -> None:
        """Test that None details defaults to empty dict."""
        error = NexusError("Test error", details=None)
        assert error.details == {}


class TestRoutingError:
    """Test the RoutingError exception."""

    def test_is_nexus_error(self) -> None:
        """Test that RoutingError is a NexusError."""
        error = RoutingError("Routing failed")
        assert isinstance(error, NexusError)
        assert error.message == "Routing failed"


class TestAgentError:
    """Test the AgentError exception."""

    def test_is_nexus_error(self) -> None:
        """Test that AgentError is a NexusError."""
        error = AgentError("Agent failed")
        assert isinstance(error, NexusError)
        assert error.message == "Agent failed"


class TestDatabaseError:
    """Test the DatabaseError exception."""

    def test_is_nexus_error(self) -> None:
        """Test that DatabaseError is a NexusError."""
        error = DatabaseError("Database failed")
        assert isinstance(error, NexusError)
        assert error.message == "Database failed"


class TestOllamaConnectionError:
    """Test the OllamaConnectionError exception."""

    def test_is_nexus_error(self) -> None:
        """Test that OllamaConnectionError is a NexusError."""
        error = OllamaConnectionError("Connection failed")
        assert isinstance(error, NexusError)
        assert error.message == "Connection failed"


class TestOllamaModelError:
    """Test the OllamaModelError exception."""

    def test_is_nexus_error(self) -> None:
        """Test that OllamaModelError is a NexusError."""
        error = OllamaModelError("Model failed")
        assert isinstance(error, NexusError)
        assert error.message == "Model failed"


class TestValidationError:
    """Test the ValidationError exception."""

    def test_is_nexus_error(self) -> None:
        """Test that ValidationError is a NexusError."""
        error = ValidationError("Validation failed")
        assert isinstance(error, NexusError)
        assert error.message == "Validation failed"


class TestPromptInjectionError:
    """Test the PromptInjectionError exception."""

    def test_is_nexus_error(self) -> None:
        """Test that PromptInjectionError is a NexusError."""
        error = PromptInjectionError("Injection detected")
        assert isinstance(error, NexusError)
        assert error.message == "Injection detected"


class TestConfigurationError:
    """Test the ConfigurationError exception."""

    def test_is_nexus_error(self) -> None:
        """Test that ConfigurationError is a NexusError."""
        error = ConfigurationError("Configuration invalid")
        assert isinstance(error, NexusError)
        assert error.message == "Configuration invalid"


class TestRateLimitError:
    """Test the RateLimitError exception."""

    def test_is_nexus_error(self) -> None:
        """Test that RateLimitError is a NexusError."""
        error = RateLimitError("Rate limit exceeded")
        assert isinstance(error, NexusError)
        assert error.message == "Rate limit exceeded"
