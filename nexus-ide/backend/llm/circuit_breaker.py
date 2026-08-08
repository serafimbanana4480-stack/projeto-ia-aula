"""Circuit Breaker for LLM providers.

States:
- CLOSED: normal operation, requests pass through
- OPEN: provider is failing, requests fail-fast without trying
- HALF_OPEN: cooldown ended, one request is allowed to test recovery
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Thread-safe circuit breaker usable from independently-created loops."""

    name: str
    failure_threshold: int = 3
    cooldown_seconds: float = 30.0
    half_open_max_calls: int = 1

    _state: CircuitState = field(default=CircuitState.CLOSED)
    _failures: int = 0
    _last_failure_time: float = 0.0
    _half_open_calls: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def state(self) -> CircuitState:
        return self._state

    async def is_call_permitted(self) -> bool:
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self.cooldown_seconds:
                    logger.info("Circuit breaker [%s]: OPEN → HALF_OPEN (cooldown elapsed)", self.name)
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    return True
                return False
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False
            return False

    async def record_success(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                logger.info("Circuit breaker [%s]: HALF_OPEN → CLOSED (recovery successful)", self.name)
            self._state = CircuitState.CLOSED
            self._failures = 0
            self._half_open_calls = 0

    async def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._last_failure_time = time.monotonic()
            if self._state == CircuitState.HALF_OPEN:
                logger.warning("Circuit breaker [%s]: HALF_OPEN → OPEN (recovery failed)", self.name)
                self._state = CircuitState.OPEN
            elif self._failures >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    logger.warning(
                        "Circuit breaker [%s]: CLOSED → OPEN (%d failures)",
                        self.name,
                        self._failures,
                    )
                self._state = CircuitState.OPEN

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failures": self._failures,
                "last_failure_time": self._last_failure_time,
            }


_breakers: dict[str, CircuitBreaker] = {}
_registry_lock = threading.RLock()


def get_breaker(name: str, **kwargs: Any) -> CircuitBreaker:
    with _registry_lock:
        if name not in _breakers:
            _breakers[name] = CircuitBreaker(name=name, **kwargs)
        return _breakers[name]


def all_breakers() -> dict[str, dict[str, Any]]:
    with _registry_lock:
        return {name: cb.snapshot() for name, cb in _breakers.items()}


def reset_breaker(name: str) -> None:
    """Manually reset a circuit breaker (admin action)."""
    with _registry_lock:
        breaker = _breakers.get(name)
    if breaker is not None:
        with breaker._lock:
            breaker._state = CircuitState.CLOSED
            breaker._failures = 0
            breaker._half_open_calls = 0
        logger.info("Circuit breaker [%s] manually reset", name)


def reset_all_breakers() -> None:
    """Clear all global breaker state for lifespan/test teardown."""
    with _registry_lock:
        _breakers.clear()
