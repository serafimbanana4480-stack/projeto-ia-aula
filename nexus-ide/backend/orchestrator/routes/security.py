from __future__ import annotations

"""Security Routes - API endpoints for security monitoring and auditing."""


import logging
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse

from backend.orchestrator.limiter import limiter

from backend.observability.event_system import get_event_bus
from backend.security.security_auditor import get_security_auditor, SecurityLevel, SecurityEventType

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/security/events")
async def get_security_events(
    level: Optional[str] = None,
    event_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100
) -> Dict[str, List[Dict]]:
    """Get security events with optional filtering."""
    try:
        event_bus = await get_event_bus()
        security_auditor = await get_security_auditor(event_bus)
        
        # Convert string parameters to enums
        level_enum = None
        if level:
            try:
                level_enum = SecurityLevel(level)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid security level: {level}")
        
        event_type_enum = None
        if event_type:
            try:
                event_type_enum = SecurityEventType(event_type)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid event type: {event_type}")
        
        # Get events
        events = await security_auditor.get_security_events(
            level=level_enum,
            event_type=event_type_enum,
            status=status,
            limit=limit
        )
        
        return {
            "events": [event.to_dict() for event in events],
            "count": len(events)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get security events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/security/events/recent")
async def get_recent_security_events(hours: int = 24) -> Dict[str, List[Dict]]:
    """Get recent security events."""
    try:
        event_bus = await get_event_bus()
        security_auditor = await get_security_auditor(event_bus)
        
        # Get all events and filter by time
        all_events = await security_auditor.get_security_events(limit=1000)
        
        from datetime import datetime, timedelta
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        recent_events = [
            event for event in all_events
            if event.timestamp > cutoff_time
        ]
        
        return {
            "events": [event.to_dict() for event in recent_events],
            "count": len(recent_events),
            "timeframe_hours": hours
        }
        
    except Exception as e:
        logger.error(f"Failed to get recent security events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/security/events/high-risk")
async def get_high_risk_events() -> Dict[str, List[Dict]]:
    """Get high-risk security events."""
    try:
        event_bus = await get_event_bus()
        security_auditor = await get_security_auditor(event_bus)
        
        # Get high and critical level events
        high_risk_events = await security_auditor.get_security_events(
            level=SecurityLevel.HIGH,
            limit=50
        )
        
        critical_events = await security_auditor.get_security_events(
            level=SecurityLevel.CRITICAL,
            limit=50
        )
        
        emergency_events = await security_auditor.get_security_events(
            level=SecurityLevel.EMERGENCY,
            limit=50
        )
        
        all_high_risk = high_risk_events + critical_events + emergency_events
        all_high_risk.sort(key=lambda e: e.timestamp, reverse=True)
        
        return {
            "events": [event.to_dict() for event in all_high_risk],
            "count": len(all_high_risk),
            "risk_distribution": {
                "high": len(high_risk_events),
                "critical": len(critical_events),
                "emergency": len(emergency_events)
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get high-risk events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/security/stats")
async def get_security_stats() -> Dict[str, Any]:
    """Get security statistics."""
    try:
        event_bus = await get_event_bus()
        security_auditor = await get_security_auditor(event_bus)
        
        return await security_auditor.get_security_stats()
        
    except Exception as e:
        logger.error(f"Failed to get security stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/security/blocked-ips")
async def get_blocked_ips() -> Dict[str, List[str]]:
    """Get list of blocked IPs."""
    try:
        event_bus = await get_event_bus()
        security_auditor = await get_security_auditor(event_bus)
        
        return {
            "blocked_ips": list(security_auditor.blocked_ips),
            "count": len(security_auditor.blocked_ips)
        }
        
    except Exception as e:
        logger.error(f"Failed to get blocked IPs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/security/blocked-ips/{ip_address}/remove")
@limiter.limit("60/minute")
async def unblock_ip(ip_address: str, request: Request) -> Dict[str, str]:
    """Remove an IP from blocked list."""
    try:
        event_bus = await get_event_bus()
        security_auditor = await get_security_auditor(event_bus)
        
        if ip_address not in security_auditor.blocked_ips:
            raise HTTPException(status_code=404, detail="IP not found in blocked list")
        
        security_auditor.blocked_ips.remove(ip_address)
        
        return {"ip_address": ip_address, "status": "unblocked"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to unblock IP {ip_address}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/security/suspicious-users")
async def get_suspicious_users() -> Dict[str, List[str]]:
    """Get list of suspicious users."""
    try:
        event_bus = await get_event_bus()
        security_auditor = await get_security_auditor(event_bus)
        
        return {
            "suspicious_users": list(security_auditor.suspicious_users),
            "count": len(security_auditor.suspicious_users)
        }
        
    except Exception as e:
        logger.error(f"Failed to get suspicious users: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/security/suspicious-users/{user_id}/remove")
@limiter.limit("60/minute")
async def unflag_user(user_id: str, request: Request) -> Dict[str, str]:
    """Remove a user from suspicious list."""
    try:
        event_bus = await get_event_bus()
        security_auditor = await get_security_auditor(event_bus)
        
        if user_id not in security_auditor.suspicious_users:
            raise HTTPException(status_code=404, detail="User not found in suspicious list")
        
        security_auditor.suspicious_users.remove(user_id)
        
        return {"user_id": user_id, "status": "unflagged"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to unflag user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/security/event-types")
async def get_security_event_types() -> Dict[str, List[str]]:
    """Get available security event types."""
    return {
        "event_types": [t.value for t in SecurityEventType],
        "descriptions": {
            "authentication_failure": "Failed authentication attempts",
            "authentication_success": "Successful authentication events",
            "authorization_failure": "Failed authorization attempts",
            "suspicious_login": "Suspicious login patterns",
            "brute_force_attempt": "Brute force attack attempts",
            "privilege_escalation": "Privilege escalation attempts",
            "data_access_violation": "Unauthorized data access",
            "api_abuse": "API abuse and rate limiting violations",
            "suspicious_activity": "General suspicious activity",
            "malicious_request": "Malicious request patterns",
            "injection_attempt": "SQL injection attempts",
            "xss_attempt": "Cross-site scripting attempts",
            "csrf_attempt": "Cross-site request forgery attempts",
            "configuration_change": "Security configuration changes",
            "security_policy_violation": "Security policy violations",
            "vulnerability_detected": "Vulnerability detections",
            "system_compromise": "System compromise events"
        }
    }


@router.get("/security/levels")
async def get_security_levels() -> Dict[str, List[str]]:
    """Get available security levels."""
    return {
        "levels": [l.value for l in SecurityLevel],
        "descriptions": {
            "low": "Low risk - informational events",
            "medium": "Medium risk - requires attention",
            "high": "High risk - requires immediate attention",
            "critical": "Critical risk - system at risk",
            "emergency": "Emergency - system compromised"
        },
        "risk_scores": {
            "low": 1.0,
            "medium": 3.0,
            "high": 6.0,
            "critical": 8.0,
            "emergency": 10.0
        }
    }


@router.post("/security/audit-request")
@limiter.limit("60/minute")
async def audit_request(request_data: Dict[str, Any], request: Request) -> Dict[str, Any]:
    """Manually audit a request for security threats."""
    try:
        event_bus = await get_event_bus()
        security_auditor = await get_security_auditor(event_bus)
        
        # Audit the request
        security_event = await security_auditor.audit_request(request_data)
        
        if security_event:
            return {
                "security_event": security_event.to_dict(),
                "threat_detected": True,
                "message": "Security threat detected"
            }
        else:
            return {
                "threat_detected": False,
                "message": "No security threats detected"
            }
        
    except Exception as e:
        logger.error(f"Failed to audit request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/security/audit-authentication")
@limiter.limit("60/minute")
async def audit_authentication(auth_data: Dict[str, Any], request: Request) -> Dict[str, Any]:
    """Manually audit an authentication event."""
    try:
        event_bus = await get_event_bus()
        security_auditor = await get_security_auditor(event_bus)
        
        # Audit the authentication
        security_event = await security_auditor.audit_authentication(auth_data)
        
        if security_event:
            return {
                "security_event": security_event.to_dict(),
                "threat_detected": True,
                "message": "Security threat detected in authentication"
            }
        else:
            return {
                "threat_detected": False,
                "message": "No security threats detected in authentication"
            }
        
    except Exception as e:
        logger.error(f"Failed to audit authentication: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/security/dashboard")
async def get_security_dashboard() -> Dict[str, Any]:
    """Get security dashboard data."""
    try:
        event_bus = await get_event_bus()
        security_auditor = await get_security_auditor(event_bus)
        
        # Get statistics
        stats = await security_auditor.get_security_stats()
        
        # Get recent events
        recent_events = await security_auditor.get_security_events(limit=10)
        
        # Get high-risk events
        high_risk_events = await security_auditor.get_security_events(
            level=SecurityLevel.HIGH,
            limit=5
        )
        
        # Calculate risk metrics
        total_events = len(recent_events)
        high_risk_count = len([e for e in recent_events if e.security_level in [SecurityLevel.HIGH, SecurityLevel.CRITICAL, SecurityLevel.EMERGENCY]])
        
        risk_percentage = (high_risk_count / total_events * 100) if total_events > 0 else 0
        
        return {
            "overview": {
                "total_events": stats["total_events"],
                "recent_events": len(recent_events),
                "high_risk_events": len(high_risk_events),
                "risk_percentage": round(risk_percentage, 2),
                "blocked_ips": stats["blocked_ips"],
                "suspicious_users": stats["suspicious_users"]
            },
            "recent_events": [event.to_dict() for event in recent_events],
            "high_risk_events": [event.to_dict() for event in high_risk_events],
            "events_by_level": stats["events_by_level"],
            "events_by_type": stats["events_by_type"]
        }
        
    except Exception as e:
        logger.error(f"Failed to get security dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))