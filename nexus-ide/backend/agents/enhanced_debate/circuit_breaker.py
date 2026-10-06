"""Circuit Breaker for LLM calls.

Implements the Circuit Breaker pattern to prevent cascading failures
when calling external services (LLMs).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CircuitState(str, Enum):
    """States of the circuit breaker."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Circuit is open, requests fail immediately
    HALF_OPEN = "half_open"  # Testing if service has recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5  # Number of failures before opening
    recovery_timeout: float = 60.0  # Seconds to wait before trying again
    expected_exception: type = Exception  # Exception type that counts as failure
    success_threshold: int = 2  # Successes needed to close circuit in HALF_OPEN state


@dataclass
class CircuitBreakerStats:
    """Statistics for circuit breaker."""
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None
    total_calls: int = 0
    total_failures: int = 0
    total_successes: int = 0


class CircuitBreaker:
    """Circuit Breaker for protecting against service failures.
    
    The circuit breaker has three states:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Circuit is open, requests fail immediately
    - HALF_OPEN: Testing if service has recovered
    
    Transition rules:
    - CLOSED -> OPEN: When failure_count >= failure_threshold
    - OPEN -> HALF_OPEN: When recovery_timeout has elapsed
    - HALF_OPEN -> CLOSED: When success_count >= success_threshold
    - HALF_OPEN -> OPEN: On any failure
    """
    
    def __init__(
        self,
        config: CircuitBreakerConfig | None = None,
        name: str = "default"
    ):
        """Initialize circuit breaker.
        
        Args:
            config: Circuit breaker configuration
            name: Name of the circuit breaker (for logging)
        """
        self.config = config or CircuitBreakerConfig()
        self.name = name
        self.stats = CircuitBreakerStats()
        
        logger.info(
            f"CircuitBreaker '{name}' initialized: "
            f"failure_threshold={self.config.failure_threshold}, "
            f"recovery_timeout={self.config.recovery_timeout}s"
        )
    
    def _should_attempt_call(self) -> bool:
        """Check if call should be attempted based on circuit state."""
        if self.stats.state == CircuitState.CLOSED:
            return True
        
        if self.stats.state == CircuitState.OPEN:
            # Check if recovery timeout has elapsed
            if (
                self.stats.last_failure_time and
                time.time() - self.stats.last_failure_time >= self.config.recovery_timeout
            ):
                logger.info(
                    f"CircuitBreaker '{self.name}' recovery timeout elapsed, "
                    "transitioning to HALF_OPEN"
                )
                self.stats.state = CircuitState.HALF_OPEN
                self.stats.success_count = 0
                return True
            return False
        
        return self.stats.state == CircuitState.HALF_OPEN
    
    def _record_success(self) -> None:
        """Record a successful call."""
        self.stats.total_successes += 1
        self.stats.last_success_time = time.time()
        
        if self.stats.state == CircuitState.HALF_OPEN:
            self.stats.success_count += 1
            logger.info(
                f"CircuitBreaker '{self.name}' success in HALF_OPEN: "
                f"{self.stats.success_count}/{self.config.success_threshold}"
            )
            
            if self.stats.success_count >= self.config.success_threshold:
                logger.info(
                    f"CircuitBreaker '{self.name}' success threshold reached, "
                    "transitioning to CLOSED"
                )
                self.stats.state = CircuitState.CLOSED
                self.stats.failure_count = 0
                self.stats.success_count = 0
    
    def _record_failure(self, error: Exception) -> None:
        """Record a failed call."""
        self.stats.total_failures += 1
        self.stats.last_failure_time = time.time()
        
        # Check if this is an expected exception
        is_expected = isinstance(error, self.config.expected_exception)
        
        if is_expected:
            self.stats.failure_count += 1
            
            if self.stats.state == CircuitState.HALF_OPEN:
                logger.warning(
                    f"CircuitBreaker '{self.name}' failure in HALF_OPEN, "
                    "transitioning back to OPEN"
                )
                self.stats.state = CircuitState.OPEN
                self.stats.success_count = 0
            elif self.stats.failure_count >= self.config.failure_threshold:
                logger.warning(
                    f"CircuitBreaker '{self.name}' failure threshold reached "
                    f"({self.stats.failure_count}/{self.config.failure_threshold}), "
                    "transitioning to OPEN"
                )
                self.stats.state = CircuitState.OPEN
        else:
            logger.error(
                f"CircuitBreaker '{self.name}' unexpected error: {error}. "
                "Not counting as circuit breaker failure."
            )
    
    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute function with circuit breaker protection.
        
        Args:
            func: Function to call
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Result of function call
            
        Raises:
            CircuitOpenError: If circuit is open
            Exception: Original exception from function call
        """
        self.stats.total_calls += 1
        
        if not self._should_attempt_call():
            logger.warning(
                f"CircuitBreaker '{self.name}' is OPEN, call rejected. "
                f"Total calls: {self.stats.total_calls}, "
                f"Total failures: {self.stats.total_failures}"
            )
            raise CircuitOpenError(
                f"Circuit breaker '{self.name}' is OPEN. "
                f"Last failure: {self.stats.last_failure_time}"
            )
        
        try:
            result = await func(*args, **kwargs)
            self._record_success()
            return result
        except Exception as e:
            self._record_failure(e)
            raise
    
    def get_state(self) -> CircuitState:
        """Get current circuit state."""
        return self.stats.state
    
    def get_stats(self) -> CircuitBreakerStats:
        """Get circuit breaker statistics."""
        return self.stats
    
    def reset(self) -> None:
        """Reset circuit breaker to CLOSED state."""
        self.stats = CircuitBreakerStats()
        logger.info(f"CircuitBreaker '{self.name}' reset to CLOSED state")


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass
