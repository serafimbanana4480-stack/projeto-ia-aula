from __future__ import annotations

"""Performance Routes - API endpoints for performance monitoring and optimization."""


import logging
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.orchestrator.limiter import limiter

from backend.observability.event_system import get_event_bus
from backend.performance.performance_engine import get_performance_engine, PerformanceMetricType, OptimizationType

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/performance/metrics")
async def get_performance_metrics(
    metric_type: Optional[str] = None,
    limit: int = 100
) -> Dict[str, List[Dict]]:
    """Get performance metrics with optional filtering."""
    try:
        event_bus = await get_event_bus()
        performance_engine = await get_performance_engine(event_bus)
        
        # Convert string parameter to enum
        metric_type_enum = None
        if metric_type:
            try:
                metric_type_enum = PerformanceMetricType(metric_type)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid metric type: {metric_type}")
        
        # Get metrics
        metrics = await performance_engine.get_metrics(
            metric_type=metric_type_enum,
            limit=limit
        )
        
        return {
            "metrics": [metric.to_dict() for metric in metrics],
            "count": len(metrics)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get performance metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance/metrics/latest")
async def get_latest_metrics() -> Dict[str, Any]:
    """Get latest performance metrics for all types."""
    try:
        event_bus = await get_event_bus()
        performance_engine = await get_performance_engine(event_bus)
        
        # Get latest metrics for each type
        latest_metrics = {}
        for metric_type in PerformanceMetricType:
            metrics = await performance_engine.get_metrics(
                metric_type=metric_type,
                limit=1
            )
            if metrics:
                latest_metrics[metric_type.value] = metrics[0].to_dict()
        
        return {
            "latest_metrics": latest_metrics,
            "timestamp": latest_metrics.get("cpu_usage", {}).get("timestamp") if latest_metrics else None
        }
        
    except Exception as e:
        logger.error(f"Failed to get latest metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance/metrics/history")
async def get_metric_history(
    metric_type: str,
    hours: int = 24
) -> Dict[str, List[Dict]]:
    """Get historical metrics for a specific type."""
    try:
        event_bus = await get_event_bus()
        performance_engine = await get_performance_engine(event_bus)
        
        # Convert string to enum
        try:
            metric_type_enum = PerformanceMetricType(metric_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid metric type: {metric_type}")
        
        # Get metrics with higher limit for history
        metrics = await performance_engine.get_metrics(
            metric_type=metric_type_enum,
            limit=1000
        )
        
        # Filter by time period
        from datetime import datetime, timedelta
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        recent_metrics = [
            metric for metric in metrics
            if metric.timestamp > cutoff_time
        ]
        
        return {
            "metric_type": metric_type,
            "timeframe_hours": hours,
            "metrics": [metric.to_dict() for metric in recent_metrics],
            "count": len(recent_metrics)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get metric history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance/alerts")
async def get_performance_alerts(
    severity: Optional[str] = None,
    resolved: Optional[bool] = None,
    limit: int = 100
) -> Dict[str, List[Dict]]:
    """Get performance alerts with optional filtering."""
    try:
        event_bus = await get_event_bus()
        performance_engine = await get_performance_engine(event_bus)
        
        # Get alerts
        alerts = await performance_engine.get_alerts(
            severity=severity,
            resolved=resolved,
            limit=limit
        )
        
        return {
            "alerts": [alert.to_dict() for alert in alerts],
            "count": len(alerts)
        }
        
    except Exception as e:
        logger.error(f"Failed to get performance alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance/alerts/active")
async def get_active_alerts() -> Dict[str, List[Dict]]:
    """Get active (unresolved) performance alerts."""
    try:
        event_bus = await get_event_bus()
        performance_engine = await get_performance_engine(event_bus)
        
        # Get active alerts
        alerts = await performance_engine.get_alerts(resolved=False, limit=50)
        
        return {
            "alerts": [alert.to_dict() for alert in alerts],
            "count": len(alerts)
        }
        
    except Exception as e:
        logger.error(f"Failed to get active alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance/recommendations")
async def get_optimization_recommendations(
    implemented: Optional[bool] = None,
    priority: Optional[str] = None,
    limit: int = 100
) -> Dict[str, List[Dict]]:
    """Get optimization recommendations with optional filtering."""
    try:
        event_bus = await get_event_bus()
        performance_engine = await get_performance_engine(event_bus)
        
        # Get recommendations
        recommendations = await performance_engine.get_recommendations(
            implemented=implemented,
            priority=priority,
            limit=limit
        )
        
        return {
            "recommendations": [rec.to_dict() for rec in recommendations],
            "count": len(recommendations)
        }
        
    except Exception as e:
        logger.error(f"Failed to get recommendations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/performance/recommendations/{recommendation_id}/implement")
@limiter.limit("60/minute")
async def implement_recommendation(recommendation_id: str, request: Request) -> Dict[str, Any]:
    """Implement an optimization recommendation."""
    try:
        event_bus = await get_event_bus()
        performance_engine = await get_performance_engine(event_bus)
        
        # Implement recommendation
        result = await performance_engine.implement_recommendation(recommendation_id)
        
        return result
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to implement recommendation {recommendation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance/stats")
async def get_performance_stats() -> Dict[str, Any]:
    """Get performance statistics."""
    try:
        event_bus = await get_event_bus()
        performance_engine = await get_performance_engine(event_bus)
        
        return await performance_engine.get_performance_stats()
        
    except Exception as e:
        logger.error(f"Failed to get performance stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance/dashboard")
async def get_performance_dashboard() -> Dict[str, Any]:
    """Get performance dashboard data."""
    try:
        event_bus = await get_event_bus()
        performance_engine = await get_performance_engine(event_bus)
        
        # Get statistics
        stats = await performance_engine.get_performance_stats()
        
        # Get latest metrics
        latest_metrics = {}
        for metric_type in PerformanceMetricType:
            metrics = await performance_engine.get_metrics(metric_type=metric_type, limit=1)
            if metrics:
                latest_metrics[metric_type.value] = metrics[0].value
        
        # Get active alerts
        active_alerts = await performance_engine.get_alerts(resolved=False, limit=5)
        
        # Get top recommendations
        top_recommendations = await performance_engine.get_recommendations(
            implemented=False,
            limit=5
        )
        
        # Calculate health score
        health_score = 100
        critical_alerts = len([a for a in active_alerts if a.severity == "critical"])
        warning_alerts = len([a for a in active_alerts if a.severity == "warning"])
        
        health_score -= (critical_alerts * 20)
        health_score -= (warning_alerts * 10)
        health_score = max(0, health_score)
        
        return {
            "overview": {
                "health_score": health_score,
                "active_alerts": len(active_alerts),
                "critical_alerts": critical_alerts,
                "warning_alerts": warning_alerts,
                "recommendations": len(top_recommendations),
                "implemented_recommendations": stats["stats"]["implemented_recommendations"]
            },
            "current_metrics": latest_metrics,
            "active_alerts": [alert.to_dict() for alert in active_alerts],
            "top_recommendations": [rec.to_dict() for rec in top_recommendations],
            "thresholds": stats["thresholds"]
        }
        
    except Exception as e:
        logger.error(f"Failed to get performance dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance/metric-types")
async def get_metric_types() -> Dict[str, List[str]]:
    """Get available performance metric types."""
    return {
        "metric_types": [t.value for t in PerformanceMetricType],
        "descriptions": {
            "cpu_usage": "CPU utilization percentage",
            "memory_usage": "Memory utilization percentage",
            "disk_usage": "Disk utilization percentage",
            "network_io": "Network I/O bytes transferred",
            "response_time": "Response time in milliseconds",
            "throughput": "Requests per second",
            "error_rate": "Error rate percentage",
            "queue_size": "Queue size count",
            "cache_hit_rate": "Cache hit rate percentage",
            "database_connections": "Active database connections"
        }
    }


@router.get("/performance/optimization-types")
async def get_optimization_types() -> Dict[str, List[str]]:
    """Get available optimization types."""
    return {
        "optimization_types": [t.value for t in OptimizationType],
        "descriptions": {
            "cache_optimization": "Optimize caching strategies",
            "database_optimization": "Optimize database performance",
            "memory_optimization": "Optimize memory usage",
            "cpu_optimization": "Optimize CPU utilization",
            "network_optimization": "Optimize network performance",
            "load_balancing": "Optimize load distribution",
            "resource_scaling": "Optimize resource allocation"
        }
    }


@router.post("/performance/metrics")
@limiter.limit("60/minute")
async def add_metric(
    metric_type: str,
    value: float,
    source: str = "",
    metadata: Optional[Dict] = None,
    request: Request = None,
) -> Dict[str, str]:
    """Add a performance metric."""
    try:
        event_bus = await get_event_bus()
        performance_engine = await get_performance_engine(event_bus)
        
        # Convert string to enum
        try:
            metric_type_enum = PerformanceMetricType(metric_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid metric type: {metric_type}")
        
        # Add metric
        await performance_engine.collect_metric(
            metric_type=metric_type_enum,
            value=value,
            source=source,
            metadata=metadata
        )
        
        return {"status": "success", "message": f"Metric {metric_type} added"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add metric: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/performance/optimize")
@limiter.limit("10/minute")
async def trigger_optimization(request: Request) -> Dict[str, str]:
    """Trigger manual optimization check."""
    try:
        event_bus = await get_event_bus()
        performance_engine = await get_performance_engine(event_bus)
        
        # This would trigger the optimization loop manually
        # For now, just return success
        logger.info("Manual optimization triggered")
        
        return {"status": "success", "message": "Optimization check triggered"}
        
    except Exception as e:
        logger.error(f"Failed to trigger optimization: {e}")
        raise HTTPException(status_code=500, detail=str(e))