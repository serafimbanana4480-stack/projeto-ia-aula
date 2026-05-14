"""Custom exceptions for NEXUS IDE backend.

Provides a hierarchy of exceptions for better error handling and debugging.
"""

from __future__ import annotations


class NexusError(Exception):
    """Base exception for all NEXUS IDE errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class RoutingError(NexusError):
    """Raised when routing fails."""

    pass


class AgentError(NexusError):
    """Raised when agent execution fails."""

    pass


class DatabaseError(NexusError):
    """Raised when database operations fail."""

    pass


class OllamaConnectionError(NexusError):
    """Raised when Ollama connection fails."""

    pass


class OllamaModelError(NexusError):
    """Raised when Ollama model operations fail."""

    pass


class ValidationError(NexusError):
    """Raised when input validation fails."""

    pass


class PromptInjectionError(NexusError):
    """Raised when prompt injection is detected."""

    pass


class ConfigurationError(NexusError):
    """Raised when configuration is invalid or missing."""

    pass


class RateLimitError(NexusError):
    """Raised when rate limit is exceeded."""

    pass
