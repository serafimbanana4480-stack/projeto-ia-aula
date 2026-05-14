"""Tests for backend.observability.tracing — setup function and in-memory spans."""

from __future__ import annotations

import pytest

from backend.observability.tracing import setup_tracing, trace_span, get_recent_spans, get_active_spans


class TestSetupTracing:
    def test_function_exists(self) -> None:
        assert callable(setup_tracing)

    def test_does_not_raise(self) -> None:
        """setup_tracing should not raise even without OTel SDK."""
        setup_tracing()  # should complete without error


class TestTraceSpan:
    def test_basic_span(self) -> None:
        """Test that trace_span records a completed span."""
        with trace_span("test.basic_span_check", key="value") as span:
            assert span.name == "test.basic_span_check"
            assert span.attributes["key"] == "value"
            assert span.end_time is None  # not finished yet

        # After context manager exits, span should be recorded
        recent = get_recent_spans(limit=5)
        found = [s for s in recent if s["name"] == "test.basic_span_check"]
        assert len(found) >= 1
        assert found[-1]["status"] == "ok"
        assert found[-1]["duration_ms"] >= 0  # can be 0 on very fast execution

    def test_error_span(self) -> None:
        """Test that errors are captured in span status."""
        try:
            with trace_span("test.error_span_check") as span:
                raise ValueError("test error")
        except ValueError:
            pass

        recent = get_recent_spans(limit=10)
        found = [s for s in recent if s["name"] == "test.error_span_check"]
        assert len(found) >= 1
        assert found[-1]["status"] == "error"

    def test_active_spans(self) -> None:
        """Test that active spans are tracked while running."""
        with trace_span("test.active_span_check") as span:
            active = get_active_spans()
            assert "test.active_span_check" in active
            assert active["test.active_span_check"]["name"] == "test.active_span_check"

        # After exit, should not be active
        active = get_active_spans()
        assert "test.active_span_check" not in active
