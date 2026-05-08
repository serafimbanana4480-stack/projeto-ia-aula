"""Tests for backend.observability.tracing — setup function existence."""
from __future__ import annotations

import pytest

from backend.observability.tracing import setup_tracing


class TestSetupTracing:
    def test_function_exists(self) -> None:
        assert callable(setup_tracing)

    def test_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            setup_tracing()
