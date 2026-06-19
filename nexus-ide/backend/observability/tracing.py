"""OpenTelemetry tracing setup. See ARCHITECTURE.md §10.1.

Provides basic in-memory span tracing when OTel SDK is not available.
When the ``opentelemetry-sdk`` package is installed, configures a real
OTLP exporter pointing at ``OTEL_EXPORTER_OTLP_ENDPOINT``.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Span:
    """A simple tracing span with start/end times and attributes."""

    name: str
    start_time: float = field(default_factory=time.perf_counter)
    end_time: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time) * 1000

    def finish(self, status: str | None = None) -> None:
        self.end_time = time.perf_counter()
        if status is not None:
            self.status = status


# In-memory span store (limited to last N spans)
_MAX_SPANS = 1000
_spans: list[Span] = []
_active_spans: dict[str, Span] = {}


def _record_span(span: Span) -> None:
    """Record a completed span."""
    if len(_spans) >= _MAX_SPANS:
        _spans.pop(0)
    _spans.append(span)


@contextmanager
def trace_span(name: str, **attributes: Any) -> Iterator[Span]:
    """Context manager for tracing a span.

    Usage::

        with trace_span("chat.pipeline", session_id="abc") as span:
            ...  # do work
            span.attributes["tokens"] = 42
    """
    span = Span(name=name, attributes=dict(attributes))
    _active_spans[name] = span
    try:
        yield span
    except Exception as exc:
        span.status = "error"
        span.attributes["error"] = str(exc)
        raise
    finally:
        span.finish()
        _active_spans.pop(name, None)
        _record_span(span)
        if span.status == "ok":
            logger.debug("Span %s completed in %.1fms", name, span.duration_ms)
        else:
            logger.warning("Span %s failed after %.1fms: %s", name, span.duration_ms, span.status)


def get_recent_spans(limit: int = 100) -> list[dict[str, Any]]:
    """Return recent completed spans as serializable dicts."""
    return [
        {
            "name": s.name,
            "duration_ms": round(s.duration_ms, 2),
            "status": s.status,
            "attributes": s.attributes,
            "start_time": s.start_time,
        }
        for s in _spans[-limit:]
    ]


def get_active_spans() -> dict[str, dict[str, Any]]:
    """Return currently active spans."""
    return {
        name: {
            "name": span.name,
            "attributes": span.attributes,
            "elapsed_ms": round((time.perf_counter() - span.start_time) * 1000, 2),
        }
        for name, span in _active_spans.items()
    }


def setup_tracing(service_name: str = "nexus-orchestrator") -> None:
    """Initialise tracing.

    If ``opentelemetry-sdk`` is installed, configures a real OTLP exporter.
    Otherwise, uses the in-memory span store above.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            resource = Resource.create({"service.name": service_name})
            provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            logger.info("OTel tracing configured with endpoint %s", endpoint)
        else:
            logger.info(
                "OTel SDK available but no OTEL_EXPORTER_OTLP_ENDPOINT set — using in-memory tracing"
            )

    except ImportError:
        logger.info("opentelemetry-sdk not installed — using in-memory tracing")
