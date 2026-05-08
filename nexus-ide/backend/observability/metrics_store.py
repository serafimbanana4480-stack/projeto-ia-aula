"""Metrics storage for historical data and timeline visualization.

Stores metrics over time for dashboard charts and analysis.
Uses in-memory storage for now (Redis for production).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Optional

from .metrics_collector import MetricsSnapshot

logger = logging.getLogger(__name__)


@dataclass
class TimelineDataPoint:
    """Single data point for timeline charts."""
    timestamp: float
    tokens_per_second: float
    active_sessions: int
    cpu_percent: float
    ram_percent: float
    avg_latency_ms: float


class MetricsStore:
    """Stores metrics history for timeline visualization."""

    def __init__(self, max_points: int = 3600):
        """Store up to max_points data points (default: 1 hour at 1s interval)."""
        self._timeline: deque[TimelineDataPoint] = deque(maxlen=max_points)
        self._lock = asyncio.Lock()

    async def add_snapshot(self, snapshot: MetricsSnapshot) -> None:
        """Add a metrics snapshot to the timeline."""
        async with self._lock:
            point = TimelineDataPoint(
                timestamp=snapshot.timestamp,
                tokens_per_second=snapshot.tokens_per_second,
                active_sessions=snapshot.active_sessions,
                cpu_percent=snapshot.cpu_percent,
                ram_percent=snapshot.ram_percent,
                avg_latency_ms=snapshot.avg_latency_ms,
            )
            self._timeline.append(point)

    async def get_timeline(
        self,
        seconds: int = 3600,
        metric: str = "tokens_per_second",
    ) -> list[dict]:
        """Get timeline data for the last N seconds."""
        async with self._lock:
            cutoff = time.time() - seconds
            filtered = [p for p in self._timeline if p.timestamp >= cutoff]
            
            # Return only the requested metric
            return [
                {
                    "timestamp": p.timestamp,
                    "value": getattr(p, metric),
                }
                for p in filtered
            ]

    async def get_timeline_multi(
        self,
        seconds: int = 3600,
        metrics: Optional[list[str]] = None,
    ) -> dict[str, list[dict]]:
        """Get timeline data for multiple metrics."""
        if metrics is None:
            metrics = ["tokens_per_second", "active_sessions", "cpu_percent", "ram_percent", "avg_latency_ms"]
        
        async with self._lock:
            cutoff = time.time() - seconds
            filtered = [p for p in self._timeline if p.timestamp >= cutoff]
            
            result = {}
            for metric in metrics:
                result[metric] = [
                    {
                        "timestamp": p.timestamp,
                        "value": getattr(p, metric),
                    }
                    for p in filtered
                ]
            return result

    async def get_latest(self) -> Optional[TimelineDataPoint]:
        """Get the most recent data point."""
        async with self._lock:
            return self._timeline[-1] if self._timeline else None

    async def clear(self) -> None:
        """Clear all stored metrics."""
        async with self._lock:
            self._timeline.clear()


# Global singleton
_store: Optional[MetricsStore] = None


def get_metrics_store() -> MetricsStore:
    """Get or create the global metrics store singleton."""
    global _store
    if _store is None:
        _store = MetricsStore()
    return _store
