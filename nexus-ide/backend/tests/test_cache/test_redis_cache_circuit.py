from __future__ import annotations

from backend.redis_cache import _CircuitBreakerMixin


class _Circuit(_CircuitBreakerMixin):
    def __init__(self) -> None:
        self._fallback = False
        self._consecutive_failures = 0


def test_optional_redis_disables_after_first_connection_failure() -> None:
    circuit = _Circuit()

    circuit._cache_error("get", "session::test", TimeoutError("offline"))

    assert circuit._fallback is True
    assert circuit._consecutive_failures == 1
