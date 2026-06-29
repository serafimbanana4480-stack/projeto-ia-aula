"""Security Auditor - Comprehensive security monitoring and auditing system.

This system provides:
- Real-time security monitoring
- Threat detection and prevention
- Security event logging
- Compliance auditing
- Vulnerability scanning
- Access control monitoring
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
import uuid
import re
import ipaddress
from collections import defaultdict, deque

from backend.observability.event_system import EventBus, Event, EventType, EventPriority

logger = logging.getLogger(__name__)


class SecurityLevel(str, Enum):
    """Security threat levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class SecurityEventType(str, Enum):
    """Types of security events."""
    AUTHENTICATION_FAILURE = "authentication_failure"
    AUTHENTICATION_SUCCESS = "authentication_success"
    AUTHORIZATION_FAILURE = "authorization_failure"
    SUSPICIOUS_LOGIN = "suspicious_login"
    BRUTE_FORCE_ATTEMPT = "brute_force_attempt"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    DATA_ACCESS_VIOLATION = "data_access_violation"
    API_ABUSE = "api_abuse"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    MALICIOUS_REQUEST = "malicious_request"
    INJECTION_ATTEMPT = "injection_attempt"
    XSS_ATTEMPT = "xss_attempt"
    CSRF_ATTEMPT = "csrf_attempt"
    CONFIGURATION_CHANGE = "configuration_change"
    SECURITY_POLICY_VIOLATION = "security_policy_violation"
    VULNERABILITY_DETECTED = "vulnerability_detected"
    SYSTEM_COMPROMISE = "system_compromise"


class ComplianceStandard(str, Enum):
    """Compliance standards."""
    GDPR = "gdpr"
    SOC2 = "soc2"
    ISO27001 = "iso27001"
    HIPAA = "hipaa"
    PCI_DSS = "pci_dss"


@dataclass
class SecurityEvent:
    """Security event record."""
    event_id: str = field(default_factory=lambda: f"sec-{uuid.uuid4().hex[:12]}")
    event_type: SecurityEventType = SecurityEventType.SUSPICIOUS_ACTIVITY
    security_level: SecurityLevel = SecurityLevel.LOW
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Event details
    source_ip: str = ""
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    endpoint: str = ""
    method: str = ""
    user_agent: str = ""
    request_data: Dict[str, Any] = field(default_factory=dict)
    
    # Detection details
    detection_rule: str = ""
    confidence_score: float = 0.0
    risk_score: float = 0.0
    
    # Context
    description: str = ""
    remediation: str = ""
    compliance_impact: List[ComplianceStandard] = field(default_factory=list)
    
    # Status
    status: str = "active"  # active, investigating, resolved, false_positive
    assigned_to: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolution_notes: str = ""
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "security_level": self.security_level.value,
            "timestamp": self.timestamp.isoformat(),
            "source_ip": self.source_ip,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "endpoint": self.endpoint,
            "method": self.method,
            "user_agent": self.user_agent,
            "request_data": self.request_data,
            "detection_rule": self.detection_rule,
            "confidence_score": self.confidence_score,
            "risk_score": self.risk_score,
            "description": self.description,
            "remediation": self.remediation,
            "compliance_impact": [c.value for c in self.compliance_impact],
            "status": self.status,
            "assigned_to": self.assigned_to,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution_notes": self.resolution_notes,
            "metadata": self.metadata
        }


@dataclass
class SecurityRule:
    """Security detection rule."""
    rule_id: str
    name: str
    description: str
    event_type: SecurityEventType
    security_level: SecurityLevel
    pattern: str
    conditions: Dict[str, Any]
    actions: List[str]
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


class SecurityAuditor:
    """Main security auditor system."""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.security_events: List[SecurityEvent] = []
        self.active_rules: Dict[str, SecurityRule] = {}
        self.blocked_ips: Set[str] = set()
        self.suspicious_users: Set[str] = set()
        
        # Monitoring
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        # Statistics
        self.stats = {
            "total_events": 0,
            "events_by_level": defaultdict(int),
            "events_by_type": defaultdict(int),
            "blocked_ips": 0,
            "suspicious_users": 0,
            "false_positives": 0,
            "true_positives": 0
        }
        
        # Rate limiting
        self.request_tracker: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.failed_logins: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        
        # Initialize default rules
        self._initialize_default_rules()
    
    async def start(self) -> None:
        """Start security auditor."""
        if self._running:
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitoring_loop())
        logger.info("SecurityAuditor started")
    
    async def stop(self) -> None:
        """Stop security auditor."""
        self._running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        
        logger.info("SecurityAuditor stopped")
    
    async def audit_request(self, request_data: Dict[str, Any]) -> Optional[SecurityEvent]:
        """Audit a request for security threats."""
        try:
            # Extract request information
            source_ip = request_data.get("source_ip", "")
            user_id = request_data.get("user_id")
            endpoint = request_data.get("endpoint", "")
            method = request_data.get("method", "")
            user_agent = request_data.get("user_agent", "")
            
            # Check against security rules
            for rule in self.active_rules.values():
                if not rule.enabled:
                    continue
                
                if await self._evaluate_rule(rule, request_data):
                    # Create security event
                    event = SecurityEvent(
                        event_type=rule.event_type,
                        security_level=rule.security_level,
                        source_ip=source_ip,
                        user_id=user_id,
                        endpoint=endpoint,
                        method=method,
                        user_agent=user_agent,
                        request_data=request_data,
                        detection_rule=rule.rule_id,
                        description=rule.description,
                        confidence_score=0.8,
                        risk_score=self._calculate_risk_score(rule.security_level)
                    )
                    
                    # Add event
                    await self._add_security_event(event)
                    
                    # Execute actions
                    await self._execute_rule_actions(rule, event, request_data)
                    
                    return event
            
            # Check rate limiting
            await self._check_rate_limits(request_data)
            
            # Check for suspicious patterns
            await self._check_suspicious_patterns(request_data)
            
            return None
            
        except Exception as e:
            logger.error(f"Error auditing request: {e}")
            return None
    
    async def audit_authentication(self, auth_data: Dict[str, Any]) -> Optional[SecurityEvent]:
        """Audit authentication events."""
        try:
            success = auth_data.get("success", False)
            user_id = auth_data.get("user_id")
            source_ip = auth_data.get("source_ip", "")
            user_agent = auth_data.get("user_agent", "")
            
            if not success:
                # Track failed login attempts
                self.failed_logins[source_ip].append(datetime.now())
                
                # Check for brute force
                recent_failures = [
                    ts for ts in self.failed_logins[source_ip]
                    if datetime.now() - ts < timedelta(minutes=15)
                ]
                
                if len(recent_failures) >= 5:
                    event = SecurityEvent(
                        event_type=SecurityEventType.BRUTE_FORCE_ATTEMPT,
                        security_level=SecurityLevel.HIGH,
                        source_ip=source_ip,
                        user_id=user_id,
                        user_agent=user_agent,
                        request_data=auth_data,
                        detection_rule="brute_force_detection",
                        description=f"Brute force attack detected from {source_ip}",
                        confidence_score=0.9,
                        risk_score=8.0
                    )
                    
                    await self._add_security_event(event)
                    
                    # Block IP temporarily
                    self.blocked_ips.add(source_ip)
                    
                    return event
                
                # Create authentication failure event
                event = SecurityEvent(
                    event_type=SecurityEventType.AUTHENTICATION_FAILURE,
                    security_level=SecurityLevel.MEDIUM,
                    source_ip=source_ip,
                    user_id=user_id,
                    user_agent=user_agent,
                    request_data=auth_data,
                    detection_rule="auth_failure_detection",
                    description=f"Authentication failure for user {user_id}",
                    confidence_score=0.7,
                    risk_score=3.0
                )
                
                await self._add_security_event(event)
                return event
            
            else:
                # Successful authentication
                event = SecurityEvent(
                    event_type=SecurityEventType.AUTHENTICATION_SUCCESS,
                    security_level=SecurityLevel.LOW,
                    source_ip=source_ip,
                    user_id=user_id,
                    user_agent=user_agent,
                    request_data=auth_data,
                    detection_rule="auth_success_detection",
                    description=f"Successful authentication for user {user_id}",
                    confidence_score=0.9,
                    risk_score=0.5
                )
                
                await self._add_security_event(event)
                return None
                
        except Exception as e:
            logger.error(f"Error auditing authentication: {e}")
            return None
    
    async def get_security_events(self, 
                                 level: Optional[SecurityLevel] = None,
                                 event_type: Optional[SecurityEventType] = None,
                                 status: Optional[str] = None,
                                 limit: int = 100) -> List[SecurityEvent]:
        """Get security events with filtering."""
        events = self.security_events
        
        # Apply filters
        if level:
            events = [e for e in events if e.security_level == level]
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if status:
            events = [e for e in events if e.status == status]
        
        # Sort by timestamp (newest first) and limit
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]
    
    async def get_security_stats(self) -> Dict[str, Any]:
        """Get security statistics."""
        # Update statistics
        self.stats["blocked_ips"] = len(self.blocked_ips)
        self.stats["suspicious_users"] = len(self.suspicious_users)
        
        # Calculate event statistics
        for event in self.security_events:
            self.stats["events_by_level"][event.security_level.value] += 1
            self.stats["events_by_type"][event.event_type.value] += 1
        
        return {
            "running": self._running,
            "total_events": len(self.security_events),
            "active_rules": len([r for r in self.active_rules.values() if r.enabled]),
            "blocked_ips": self.stats["blocked_ips"],
            "suspicious_users": self.stats["suspicious_users"],
            "events_by_level": dict(self.stats["events_by_level"]),
            "events_by_type": dict(self.stats["events_by_type"]),
            "recent_events": len([e for e in self.security_events 
                                if datetime.now() - e.timestamp < timedelta(hours=24)])
        }
    
    async def _add_security_event(self, event: SecurityEvent) -> None:
        """Add a security event."""
        self.security_events.append(event)
        self.stats["total_events"] += 1
        
        # Emit security event
        if self.event_bus:
            try:
                bus_event = Event(
                    event_type=EventType.SECURITY_ALERT,
                    source="security_auditor",
                    priority=EventPriority.HIGH if event.security_level in [SecurityLevel.HIGH, SecurityLevel.CRITICAL, SecurityLevel.EMERGENCY] else EventPriority.NORMAL,
                    payload={
                        "security_event": event.to_dict()
                    },
                    metadata={
                        "component": "security_auditor",
                        "timestamp": datetime.now().isoformat()
                    }
                )
                
                await self.event_bus.publish(bus_event)
                
            except Exception as e:
                logger.error(f"Failed to emit security event: {e}")
        
        logger.warning(f"Security event: {event.event_type.value} - {event.description}")
    
    async def _evaluate_rule(self, rule: SecurityRule, request_data: Dict[str, Any]) -> bool:
        """Evaluate a security rule against request data."""
        try:
            # Check pattern match
            if rule.pattern:
                # Simple pattern matching (can be extended with regex)
                if "endpoint" in request_data:
                    if not re.search(rule.pattern, request_data["endpoint"]):
                        return False
            
            # Check conditions
            for key, expected_value in rule.conditions.items():
                if key not in request_data:
                    return False
                
                actual_value = request_data[key]
                
                # Handle different condition types
                if isinstance(expected_value, dict):
                    # Range condition
                    if "min" in expected_value and actual_value < expected_value["min"]:
                        return False
                    if "max" in expected_value and actual_value > expected_value["max"]:
                        return False
                    if "contains" in expected_value and expected_value["contains"] not in str(actual_value):
                        return False
                    if "equals" in expected_value and actual_value != expected_value["equals"]:
                        return False
                else:
                    # Direct comparison
                    if actual_value != expected_value:
                        return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error evaluating rule {rule.rule_id}: {e}")
            return False
    
    async def _execute_rule_actions(self, rule: SecurityRule, event: SecurityEvent, request_data: Dict[str, Any]) -> None:
        """Execute actions for a security rule."""
        for action in rule.actions:
            try:
                if action == "block_ip":
                    source_ip = request_data.get("source_ip", "")
                    if source_ip:
                        self.blocked_ips.add(source_ip)
                        logger.warning(f"Blocked IP: {source_ip}")
                
                elif action == "flag_user":
                    user_id = request_data.get("user_id")
                    if user_id:
                        self.suspicious_users.add(user_id)
                        logger.warning(f"Flagged suspicious user: {user_id}")
                
                elif action == "require_mfa":
                    # This would integrate with authentication system
                    logger.info(f"Requiring MFA for user: {event.user_id}")
                
                elif action == "log_event":
                    # Event is already logged
                    pass
                
                elif action == "notify_admin":
                    # This would integrate with notification system
                    logger.critical(f"Security alert requiring admin attention: {event.description}")
                
            except Exception as e:
                logger.error(f"Error executing action {action}: {e}")
    
    async def _check_rate_limits(self, request_data: Dict[str, Any]) -> None:
        """Check for rate limit violations."""
        source_ip = request_data.get("source_ip", "")
        endpoint = request_data.get("endpoint", "")
        
        if not source_ip or not endpoint:
            return
        
        # Track requests
        key = f"{source_ip}:{endpoint}"
        self.request_tracker[key].append(datetime.now())
        
        # Check rate limits (100 requests per minute)
        recent_requests = [
            ts for ts in self.request_tracker[key]
            if datetime.now() - ts < timedelta(minutes=1)
        ]
        
        if len(recent_requests) > 100:
            event = SecurityEvent(
                event_type=SecurityEventType.API_ABUSE,
                security_level=SecurityLevel.MEDIUM,
                source_ip=source_ip,
                endpoint=endpoint,
                method=request_data.get("method", ""),
                request_data=request_data,
                detection_rule="rate_limit_detection",
                description=f"Rate limit exceeded: {len(recent_requests)} requests/minute",
                confidence_score=0.9,
                risk_score=4.0
            )
            
            await self._add_security_event(event)
    
    async def _check_suspicious_patterns(self, request_data: Dict[str, Any]) -> None:
        """Check for suspicious request patterns."""
        source_ip = request_data.get("source_ip", "")
        endpoint = request_data.get("endpoint", "")
        method = request_data.get("method", "")
        user_agent = request_data.get("user_agent", "")
        
        # Check for SQL injection patterns
        sql_patterns = [
            r"union\s+select",
            r"or\s+1\s*=\s*1",
            r"drop\s+table",
            r"insert\s+into",
            r"delete\s+from"
        ]
        
        for pattern in sql_patterns:
            if re.search(pattern, endpoint, re.IGNORECASE):
                event = SecurityEvent(
                    event_type=SecurityEventType.INJECTION_ATTEMPT,
                    security_level=SecurityLevel.HIGH,
                    source_ip=source_ip,
                    endpoint=endpoint,
                    method=method,
                    user_agent=user_agent,
                    request_data=request_data,
                    detection_rule="sql_injection_detection",
                    description=f"SQL injection attempt detected: {pattern}",
                    confidence_score=0.8,
                    risk_score=7.0
                )
                
                await self._add_security_event(event)
                break
        
        # Check for XSS patterns
        xss_patterns = [
            r"<script",
            r"javascript:",
            r"onload\s*=",
            r"onerror\s*="
        ]
        
        for pattern in xss_patterns:
            if re.search(pattern, endpoint, re.IGNORECASE):
                event = SecurityEvent(
                    event_type=SecurityEventType.XSS_ATTEMPT,
                    security_level=SecurityLevel.HIGH,
                    source_ip=source_ip,
                    endpoint=endpoint,
                    method=method,
                    user_agent=user_agent,
                    request_data=request_data,
                    detection_rule="xss_detection",
                    description=f"XSS attempt detected: {pattern}",
                    confidence_score=0.7,
                    risk_score=6.0
                )
                
                await self._add_security_event(event)
                break
    
    async def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                # Clean old data
                await self._cleanup_old_data()
                
                # Check for new threats
                await self._analyze_threats()
                
                # Sleep for monitoring interval
                await asyncio.sleep(60)  # Check every minute
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(30)
    
    async def _cleanup_old_data(self) -> None:
        """Clean up old security data."""
        cutoff_time = datetime.now() - timedelta(days=30)
        
        # Clean old events
        self.security_events = [
            e for e in self.security_events 
            if e.timestamp > cutoff_time
        ]
        
        # Clean old rate limit data
        for key in list(self.request_tracker.keys()):
            recent_requests = [
                ts for ts in self.request_tracker[key]
                if datetime.now() - ts < timedelta(hours=1)
            ]
            if not recent_requests:
                del self.request_tracker[key]
        
        # Clean old failed login data
        for ip in list(self.failed_logins.keys()):
            recent_failures = [
                ts for ts in self.failed_logins[ip]
                if datetime.now() - ts < timedelta(hours=24)
            ]
            if not recent_failures:
                del self.failed_logins[ip]
    
    async def _analyze_threats(self) -> None:
        """Analyze security threats and patterns."""
        # Check for attack patterns
        recent_events = [
            e for e in self.security_events
            if datetime.now() - e.timestamp < timedelta(hours=1)
        ]
        
        # Group by source IP
        ip_events = defaultdict(list)
        for event in recent_events:
            ip_events[event.source_ip].append(event)
        
        # Check for coordinated attacks
        for ip, events in ip_events.items():
            if len(events) >= 10:
                # Potential coordinated attack
                event = SecurityEvent(
                    event_type=SecurityEventType.SYSTEM_COMPROMISE,
                    security_level=SecurityLevel.CRITICAL,
                    source_ip=ip,
                    detection_rule="coordinated_attack_detection",
                    description=f"Coordinated attack detected from {ip}: {len(events)} events",
                    confidence_score=0.8,
                    risk_score=9.0
                )
                
                await self._add_security_event(event)
                
                # Block IP
                self.blocked_ips.add(ip)
    
    def _calculate_risk_score(self, security_level: SecurityLevel) -> float:
        """Calculate risk score based on security level."""
        risk_scores = {
            SecurityLevel.LOW: 1.0,
            SecurityLevel.MEDIUM: 3.0,
            SecurityLevel.HIGH: 6.0,
            SecurityLevel.CRITICAL: 8.0,
            SecurityLevel.EMERGENCY: 10.0
        }
        return risk_scores.get(security_level, 1.0)
    
    def _initialize_default_rules(self) -> None:
        """Initialize default security rules."""
        default_rules = [
            SecurityRule(
                rule_id="sql_injection_basic",
                name="SQL Injection Detection",
                description="Detect basic SQL injection attempts",
                event_type=SecurityEventType.INJECTION_ATTEMPT,
                security_level=SecurityLevel.HIGH,
                pattern=r"(union|select|drop|insert|delete)",
                conditions={},
                actions=["block_ip", "notify_admin"]
            ),
            SecurityRule(
                rule_id="xss_basic",
                name="XSS Detection",
                description="Detect basic XSS attempts",
                event_type=SecurityEventType.XSS_ATTEMPT,
                security_level=SecurityLevel.HIGH,
                pattern=r"(<script|javascript:)",
                conditions={},
                actions=["block_ip", "log_event"]
            ),
            SecurityRule(
                rule_id="admin_access",
                name="Admin Access Monitoring",
                description="Monitor access to admin endpoints",
                event_type=SecurityEventType.PRIVILEGE_ESCALATION,
                security_level=SecurityLevel.MEDIUM,
                pattern=r"/admin/",
                conditions={},
                actions=["log_event", "require_mfa"]
            ),
            SecurityRule(
                rule_id="suspicious_user_agent",
                name="Suspicious User Agent",
                description="Detect suspicious user agents",
                event_type=SecurityEventType.SUSPICIOUS_ACTIVITY,
                security_level=SecurityLevel.LOW,
                pattern="",
                conditions={
                    "user_agent": {
                        "contains": ["bot", "crawler", "scanner", "exploit"]
                    }
                },
                actions=["log_event"]
            )
        ]
        
        for rule in default_rules:
            self.active_rules[rule.rule_id] = rule


# Global security auditor instance
_security_auditor: Optional[SecurityAuditor] = None


async def get_security_auditor(event_bus: EventBus) -> SecurityAuditor:
    """Get the global security auditor instance."""
    global _security_auditor
    if _security_auditor is None:
        _security_auditor = SecurityAuditor(event_bus)
    return _security_auditor


async def shutdown_security_auditor() -> None:
    """Shutdown the security auditor."""
    global _security_auditor
    if _security_auditor:
        await _security_auditor.stop()
        _security_auditor = None