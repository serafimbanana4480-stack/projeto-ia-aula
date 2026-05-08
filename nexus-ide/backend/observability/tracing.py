"""OpenTelemetry tracing setup. See ARCHITECTURE.md §10.1."""
from __future__ import annotations


def setup_tracing(service_name: str = "nexus-orchestrator") -> None:
    """Initialise OTel SDK + OTLP exporter.

    TODO:
    - Configure TracerProvider with service name + resource attrs.
    - Register OTLPSpanExporter pointing at OTEL_EXPORTER_OTLP_ENDPOINT.
    - Instrument FastAPI, httpx, redis clients.
    """
    raise NotImplementedError
