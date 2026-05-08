"""Alerts endpoint for Dashboard Agent integration.

Provides SSE streaming of real-time alerts based on system metrics.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.observability.metrics_collector import get_metrics_collector

logger = logging.getLogger(__name__)

router = APIRouter()


@dataclass
class Alert:
    """Alert data structure."""
    id: str
    severity: str  # info, warning, error, critical
    message: str
    timestamp: str
    source: str


class AlertGenerator:
    """Generates alerts based on system metrics."""
    
    def __init__(self):
        self._last_alerts = {}
        self._alert_cooldown = 60  # seconds
    
    def generate_alerts(self, metrics: dict) -> list[Alert]:
        """Generate alerts based on current metrics."""
        alerts = []
        now = datetime.now(timezone.utc)
        
        # CPU alert
        cpu_percent = metrics.get("cpu_percent", 0)
        if cpu_percent > 90:
            alert_id = f"cpu_high_{now.minute}"
            if alert_id not in self._last_alerts or (now - self._last_alerts[alert_id]).total_seconds() > self._alert_cooldown:
                alerts.append(Alert(
                    id=alert_id,
                    severity="critical",
                    message=f"CPU usage critical: {cpu_percent:.1f}%",
                    timestamp=now.isoformat(),
                    source="system",
                ))
                self._last_alerts[alert_id] = now
        elif cpu_percent > 70:
            alert_id = f"cpu_warning_{now.minute}"
            if alert_id not in self._last_alerts or (now - self._last_alerts[alert_id]).total_seconds() > self._alert_cooldown:
                alerts.append(Alert(
                    id=alert_id,
                    severity="warning",
                    message=f"CPU usage elevated: {cpu_percent:.1f}%",
                    timestamp=now.isoformat(),
                    source="system",
                ))
                self._last_alerts[alert_id] = now
        
        # RAM alert
        ram_percent = metrics.get("ram_percent", 0)
        if ram_percent > 90:
            alert_id = f"ram_high_{now.minute}"
            if alert_id not in self._last_alerts or (now - self._last_alerts[alert_id]).total_seconds() > self._alert_cooldown:
                alerts.append(Alert(
                    id=alert_id,
                    severity="critical",
                    message=f"RAM usage critical: {ram_percent:.1f}%",
                    timestamp=now.isoformat(),
                    source="system",
                ))
                self._last_alerts[alert_id] = now
        elif ram_percent > 80:
            alert_id = f"ram_warning_{now.minute}"
            if alert_id not in self._last_alerts or (now - self._last_alerts[alert_id]).total_seconds() > self._alert_cooldown:
                alerts.append(Alert(
                    id=alert_id,
                    severity="warning",
                    message=f"RAM usage elevated: {ram_percent:.1f}%",
                    timestamp=now.isoformat(),
                    source="system",
                ))
                self._last_alerts[alert_id] = now
        
        # Latency alert
        avg_latency = metrics.get("avg_latency_ms", 0)
        if avg_latency > 2000:
            alert_id = f"latency_high_{now.minute}"
            if alert_id not in self._last_alerts or (now - self._last_alerts[alert_id]).total_seconds() > self._alert_cooldown:
                alerts.append(Alert(
                    id=alert_id,
                    severity="critical",
                    message=f"High latency detected: {avg_latency:.0f}ms",
                    timestamp=now.isoformat(),
                    source="system",
                ))
                self._last_alerts[alert_id] = now
        elif avg_latency > 1000:
            alert_id = f"latency_warning_{now.minute}"
            if alert_id not in self._last_alerts or (now - self._last_alerts[alert_id]).total_seconds() > self._alert_cooldown:
                alerts.append(Alert(
                    id=alert_id,
                    severity="warning",
                    message=f"Elevated latency: {avg_latency:.0f}ms",
                    timestamp=now.isoformat(),
                    source="system",
                ))
                self._last_alerts[alert_id] = now
        
        # Error rate alert
        requests_total = metrics.get("requests_total", 0)
        requests_failed = metrics.get("requests_failed", 0)
        if requests_total > 0:
            error_rate = (requests_failed / requests_total) * 100
            if error_rate > 10:
                alert_id = f"error_rate_high_{now.minute}"
                if alert_id not in self._last_alerts or (now - self._last_alerts[alert_id]).total_seconds() > self._alert_cooldown:
                    alerts.append(Alert(
                        id=alert_id,
                        severity="error",
                        message=f"High error rate: {error_rate:.1f}%",
                        timestamp=now.isoformat(),
                        source="system",
                    ))
                    self._last_alerts[alert_id] = now
        
        return alerts


_alert_generator = AlertGenerator()


@router.get("/alerts/stream")
async def alerts_stream() -> StreamingResponse:
    """Stream real-time alerts via SSE.
    
    Returns a Server-Sent Events stream with alert notifications.
    """
    collector = get_metrics_collector()

    async def event_generator() -> AsyncIterator[str]:
        """Generate SSE events with alerts."""
        while True:
            # Get current metrics
            active_sessions = 1  # Placeholder
            snapshot = await collector.get_snapshot(active_sessions=active_sessions, queue_depth=0)
            
            # Generate alerts based on metrics
            metrics_dict = {
                "cpu_percent": snapshot.cpu_percent,
                "ram_percent": snapshot.ram_percent,
                "avg_latency_ms": snapshot.avg_latency_ms,
                "requests_total": snapshot.requests_total,
                "requests_failed": snapshot.requests_failed,
            }
            
            alerts = _alert_generator.generate_alerts(metrics_dict)
            
            # Send alerts as SSE events
            for alert in alerts:
                alert_data = {
                    "id": alert.id,
                    "severity": alert.severity,
                    "message": alert.message,
                    "timestamp": alert.timestamp,
                    "source": alert.source,
                }
                yield f"data: {json.dumps(alert_data)}\n\n"
            
            await asyncio.sleep(5)  # Check for alerts every 5 seconds

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/alerts/current")
async def get_current_alerts() -> list[dict]:
    """Get current active alerts."""
    collector = get_metrics_collector()
    
    active_sessions = 1
    snapshot = await collector.get_snapshot(active_sessions=active_sessions, queue_depth=0)
    
    metrics_dict = {
        "cpu_percent": snapshot.cpu_percent,
        "ram_percent": snapshot.ram_percent,
        "avg_latency_ms": snapshot.avg_latency_ms,
        "requests_total": snapshot.requests_total,
        "requests_failed": snapshot.requests_failed,
    }
    
    alerts = _alert_generator.generate_alerts(metrics_dict)
    
    return [
        {
            "id": alert.id,
            "severity": alert.severity,
            "message": alert.message,
            "timestamp": alert.timestamp,
            "source": alert.source,
        }
        for alert in alerts
    ]
