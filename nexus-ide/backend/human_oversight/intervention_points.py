"""Intervention Points — Human intervention system for critical AI decisions.

This module provides:
- Definition of intervention points in AI workflows
- Automatic detection of intervention triggers
- Context-aware intervention routing
- Intervention escalation procedures
- Human-AI collaboration workflows
"""

from __future__ import annotations

import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
import uuid

from backend.observability.event_bus import EventBus
from backend.observability.events import Event

logger = logging.getLogger(__name__)


class InterventionTrigger(Enum):
    """Types of intervention triggers."""
    UNCERTAINTY_HIGH = "uncertainty_high"           # AI uncertainty above threshold
    RISK_HIGH = "risk_high"                       # Risk assessment above threshold
    ETHICAL_CONCERN = "ethical_concern"           # Ethical considerations detected
    SECURITY_VIOLATION = "security_violation"     # Security policy violation
    COMPLIANCE_ISSUE = "compliance_issue"         # Compliance requirement violation
    PERFORMANCE_DEGRADATION = "performance_degradation"  # Performance issues
    RESOURCE_EXHAUSTION = "resource_exhaustion"    # Resource limits exceeded
    DECISION_COMPLEXITY = "decision_complexity"    # Decision too complex for AI
    HUMAN_REQUEST = "human_request"                # Explicit human request
    SYSTEM_ANOMALY = "system_anomaly"              # System behavior anomaly


class InterventionLevel(Enum):
    """Levels of intervention required."""
    ADVISORY = "advisory"          # Human advice requested
    APPROVAL = "approval"          # Human approval required
    CORRECTION = "correction"      # Human correction needed
    OVERRIDE = "override"          # Human override required
    EMERGENCY = "emergency"        # Emergency intervention needed


class InterventionStatus(Enum):
    """Status of intervention requests."""
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"


@dataclass
class InterventionPoint:
    """Defines a point where human intervention may be required."""
    point_id: str
    name: str
    description: str
    workflow_stage: str
    trigger_conditions: List[Dict[str, Any]]
    intervention_level: InterventionLevel
    required_human_role: str
    timeout_minutes: int
    escalation_policy: Dict[str, Any]
    context_requirements: List[str]
    decision_criteria: List[str]
    fallback_procedure: Dict[str, Any]


@dataclass
class InterventionRequest:
    """Represents an intervention request."""
    request_id: str
    point_id: str
    trigger: InterventionTrigger
    level: InterventionLevel
    context: Dict[str, Any]
    ai_decision: Dict[str, Any]
    human_input_required: str
    urgency_score: float
    risk_assessment: Dict[str, Any]
    created_at: datetime
    deadline: datetime
    status: InterventionStatus = InterventionStatus.PENDING
    assigned_human: Optional[str] = None
    human_response: Optional[str] = None
    resolution_action: Optional[str] = None
    escalation_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InterventionResponse:
    """Represents a human intervention response."""
    request_id: str
    responder_id: str
    response_type: str
    decision: str
    reasoning: str
    confidence: float
    conditions: List[str] = field(default_factory=list)
    follow_up_actions: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)


class InterventionDetector:
    """Detects when human intervention is needed."""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.trigger_handlers = {
            InterventionTrigger.UNCERTAINTY_HIGH: self._check_uncertainty,
            InterventionTrigger.RISK_HIGH: self._check_risk,
            InterventionTrigger.ETHICAL_CONCERN: self._check_ethical,
            InterventionTrigger.SECURITY_VIOLATION: self._check_security,
            InterventionTrigger.COMPLIANCE_ISSUE: self._check_compliance,
            InterventionTrigger.PERFORMANCE_DEGRADATION: self._check_performance,
            InterventionTrigger.RESOURCE_EXHAUSTION: self._check_resources,
            InterventionTrigger.DECISION_COMPLEXITY: self._check_complexity,
            InterventionTrigger.SYSTEM_ANOMALY: self._check_anomaly
        }
    
    async def detect_intervention_needed(self, context: Dict[str, Any]) -> List[Tuple[InterventionTrigger, float]]:
        """Detect if intervention is needed based on context."""
        
        interventions = []
        
        for trigger, handler in self.trigger_handlers.items():
            try:
                urgency_score = await handler(context)
                if urgency_score > 0.5:  # Threshold for intervention
                    interventions.append((trigger, urgency_score))
            except Exception as e:
                logger.error(f"Error checking trigger {trigger}: {e}")
        
        # Sort by urgency score
        interventions.sort(key=lambda x: x[1], reverse=True)
        
        return interventions
    
    async def _check_uncertainty(self, context: Dict[str, Any]) -> float:
        """Check for high uncertainty."""
        uncertainty_score = context.get("uncertainty_score", 0.0)
        confidence_score = context.get("confidence_score", 1.0)
        
        # High uncertainty when uncertainty > 0.7 or confidence < 0.3
        if uncertainty_score > 0.7 or confidence_score < 0.3:
            return max(uncertainty_score, 1.0 - confidence_score)
        
        return 0.0
    
    async def _check_risk(self, context: Dict[str, Any]) -> float:
        """Check for high risk."""
        risk_assessment = context.get("risk_assessment", {})
        overall_risk = risk_assessment.get("overall_risk", 0.0)
        
        # High risk when overall risk > 0.8
        if overall_risk > 0.8:
            return overall_risk
        
        return 0.0
    
    async def _check_ethical(self, context: Dict[str, Any]) -> float:
        """Check for ethical concerns."""
        ethical_flags = context.get("ethical_flags", [])
        ethical_score = context.get("ethical_score", 1.0)
        
        # Ethical concern when flags present or score < 0.5
        if ethical_flags or ethical_score < 0.5:
            return 0.9 if ethical_flags else (1.0 - ethical_score)
        
        return 0.0
    
    async def _check_security(self, context: Dict[str, Any]) -> float:
        """Check for security violations."""
        security_flags = context.get("security_flags", [])
        security_score = context.get("security_score", 1.0)
        
        # Security violation when flags present or score < 0.3
        if security_flags or security_score < 0.3:
            return 1.0 if security_flags else (1.0 - security_score)
        
        return 0.0
    
    async def _check_compliance(self, context: Dict[str, Any]) -> float:
        """Check for compliance issues."""
        compliance_flags = context.get("compliance_flags", [])
        compliance_score = context.get("compliance_score", 1.0)
        
        # Compliance issue when flags present or score < 0.4
        if compliance_flags or compliance_score < 0.4:
            return 0.8 if compliance_flags else (1.0 - compliance_score)
        
        return 0.0
    
    async def _check_performance(self, context: Dict[str, Any]) -> float:
        """Check for performance degradation."""
        performance_metrics = context.get("performance_metrics", {})
        response_time = performance_metrics.get("response_time", 0.0)
        error_rate = performance_metrics.get("error_rate", 0.0)
        
        # Performance issue when response time > 10s or error rate > 5%
        if response_time > 10.0 or error_rate > 0.05:
            return min(1.0, max(response_time / 10.0, error_rate * 20))
        
        return 0.0
    
    async def _check_resources(self, context: Dict[str, Any]) -> float:
        """Check for resource exhaustion."""
        resource_usage = context.get("resource_usage", {})
        cpu_usage = resource_usage.get("cpu", 0.0)
        memory_usage = resource_usage.get("memory", 0.0)
        
        # Resource issue when CPU > 90% or memory > 90%
        if cpu_usage > 0.9 or memory_usage > 0.9:
            return max(cpu_usage, memory_usage)
        
        return 0.0
    
    async def _check_complexity(self, context: Dict[str, Any]) -> float:
        """Check for decision complexity."""
        complexity_score = context.get("complexity_score", 0.0)
        decision_factors = context.get("decision_factors", [])
        
        # Complex decision when complexity > 0.8 or many factors
        if complexity_score > 0.8 or len(decision_factors) > 10:
            return max(complexity_score, min(1.0, len(decision_factors) / 15))
        
        return 0.0
    
    async def _check_anomaly(self, context: Dict[str, Any]) -> float:
        """Check for system anomalies."""
        anomaly_score = context.get("anomaly_score", 0.0)
        anomaly_flags = context.get("anomaly_flags", [])
        
        # Anomaly when score > 0.7 or flags present
        if anomaly_score > 0.7 or anomaly_flags:
            return max(anomaly_score, 0.8 if anomaly_flags else 0.0)
        
        return 0.0


class InterventionManager:
    """Manages intervention requests and responses."""
    
    def __init__(self, event_bus: EventBus, approval_queue):
        self.event_bus = event_bus
        self.approval_queue = approval_queue
        self.intervention_points: Dict[str, InterventionPoint] = {}
        self.active_requests: Dict[str, InterventionRequest] = {}
        self.request_history: List[InterventionRequest] = []
        self.escalation_policies: Dict[str, Dict[str, Any]] = {}
        self.human_experts: Dict[str, Dict[str, Any]] = {}
        
        # Initialize default intervention points
        self._initialize_default_points()
        
        # Start background tasks
        self._monitoring_task = asyncio.create_task(self._monitor_active_requests())
    
    def _initialize_default_points(self) -> None:
        """Initialize default intervention points."""
        
        # High-risk decisions
        self.intervention_points["high_risk_decision"] = InterventionPoint(
            point_id="high_risk_decision",
            name="High-Risk Decision Review",
            description="Review decisions with high risk assessment",
            workflow_stage="decision_making",
            trigger_conditions=[
                {"trigger": "risk_high", "threshold": 0.8}
            ],
            intervention_level=InterventionLevel.APPROVAL,
            required_human_role="risk_manager",
            timeout_minutes=60,
            escalation_policy={
                "escalate_after": 30,
                "escalate_to": "senior_manager",
                "max_escalations": 2
            },
            context_requirements=["risk_assessment", "decision_data", "alternatives"],
            decision_criteria=["risk_acceptable", "compliant", "feasible"],
            fallback_procedure={
                "auto_approve": False,
                "escalate_immediately": True,
                "notify_stakeholders": True
            }
        )
        
        # Security violations
        self.intervention_points["security_violation"] = InterventionPoint(
            point_id="security_violation",
            name="Security Violation Response",
            description="Handle security policy violations",
            workflow_stage="security_check",
            trigger_conditions=[
                {"trigger": "security_violation", "threshold": 0.5}
            ],
            intervention_level=InterventionLevel.EMERGENCY,
            required_human_role="security_officer",
            timeout_minutes=15,
            escalation_policy={
                "escalate_after": 5,
                "escalate_to": "security_director",
                "max_escalations": 3
            },
            context_requirements=["security_flags", "violation_details", "impact_assessment"],
            decision_criteria=["security_compliant", "risk_mitigated", "proper_authorization"],
            fallback_procedure={
                "auto_approve": False,
                "escalate_immediately": True,
                "block_action": True
            }
        )
        
        # Ethical concerns
        self.intervention_points["ethical_concern"] = InterventionPoint(
            point_id="ethical_concern",
            name="Ethical Concern Review",
            description="Review ethical implications of decisions",
            workflow_stage="ethical_review",
            trigger_conditions=[
                {"trigger": "ethical_concern", "threshold": 0.5}
            ],
            intervention_level=InterventionLevel.APPROVAL,
            required_human_role="ethics_officer",
            timeout_minutes=120,
            escalation_policy={
                "escalate_after": 60,
                "escalate_to": "ethics_committee",
                "max_escalations": 2
            },
            context_requirements=["ethical_flags", "ethical_analysis", "stakeholder_impact"],
            decision_criteria=["ethical_acceptable", "stakeholder_considered", "transparent"],
            fallback_procedure={
                "auto_approve": False,
                "escalate_immediately": False,
                "require_documentation": True
            }
        )
    
    async def request_intervention(self, context: Dict[str, Any]) -> List[str]:
        """Request human intervention based on context."""
        
        detector = InterventionDetector(self.event_bus)
        interventions = await detector.detect_intervention_needed(context)
        
        request_ids = []
        
        for trigger, urgency_score in interventions:
            # Find matching intervention point
            point = self._find_matching_point(trigger, context)
            
            if point:
                request_id = await self._create_intervention_request(point, trigger, urgency_score, context)
                request_ids.append(request_id)
        
        return request_ids
    
    async def _create_intervention_request(self, point: InterventionPoint, 
                                         trigger: InterventionTrigger, 
                                         urgency_score: float, 
                                         context: Dict[str, Any]) -> str:
        """Create an intervention request."""
        
        request_id = str(uuid.uuid4())
        
        # Calculate deadline
        deadline = datetime.now() + timedelta(minutes=point.timeout_minutes)
        
        # Determine intervention level
        level = point.intervention_level
        if urgency_score > 0.9:
            level = InterventionLevel.EMERGENCY
        elif urgency_score > 0.7:
            level = InterventionLevel.OVERRIDE
        
        request = InterventionRequest(
            request_id=request_id,
            point_id=point.point_id,
            trigger=trigger,
            level=level,
            context=context,
            ai_decision=context.get("ai_decision", {}),
            human_input_required=point.description,
            urgency_score=urgency_score,
            risk_assessment=context.get("risk_assessment", {}),
            created_at=datetime.now(),
            deadline=deadline
        )
        
        # Store request
        self.active_requests[request_id] = request
        
        # Create approval request if needed
        if level in [InterventionLevel.APPROVAL, InterventionLevel.OVERRIDE]:
            await self._create_approval_request(request, point)
        
        # Emit intervention request event
        await self.event_bus.emit(Event(
            type="intervention_requested",
            data={
                "request_id": request_id,
                "point_id": point.point_id,
                "trigger": trigger.value,
                "level": level.value,
                "urgency_score": urgency_score
            }
        ))
        
        logger.info(f"Intervention requested: {request_id} ({trigger.value})")
        
        return request_id
    
    async def respond_to_intervention(self, request_id: str, response: InterventionResponse) -> bool:
        """Respond to an intervention request."""
        
        if request_id not in self.active_requests:
            return False
        
        request = self.active_requests[request_id]
        
        # Update request
        request.status = InterventionStatus.RESOLVED
        request.assigned_human = response.responder_id
        request.human_response = response.decision
        request.resolution_action = response.decision
        
        # Move to history
        self.request_history.append(request)
        del self.active_requests[request_id]
        
        # Emit response event
        await self.event_bus.emit(Event(
            type="intervention_responded",
            data={
                "request_id": request_id,
                "responder_id": response.responder_id,
                "decision": response.decision,
                "response_time": (datetime.now() - request.created_at).total_seconds()
            }
        ))
        
        logger.info(f"Intervention responded: {request_id} by {response.responder_id}")
        
        return True
    
    async def escalate_intervention(self, request_id: str, reason: str) -> bool:
        """Escalate an intervention request."""
        
        if request_id not in self.active_requests:
            return False
        
        request = self.active_requests[request_id]
        point = self.intervention_points[request.point_id]
        
        # Check escalation limit
        if request.escalation_count >= point.escalation_policy.get("max_escalations", 2):
            return False
        
        # Update request
        request.status = InterventionStatus.ESCALATED
        request.escalation_count += 1
        
        # Get escalation target
        escalation_target = point.escalation_policy.get("escalate_to", "senior_manager")
        
        # Create escalation notification
        await self.event_bus.emit(Event(
            type="intervention_escalated",
            data={
                "request_id": request_id,
                "escalation_count": request.escalation_count,
                "escalation_target": escalation_target,
                "reason": reason
            }
        ))
        
        logger.info(f"Intervention escalated: {request_id} to {escalation_target}")
        
        return True
    
    async def get_active_interventions(self, human_id: str = None) -> List[InterventionRequest]:
        """Get active intervention requests."""
        
        requests = list(self.active_requests.values())
        
        # Filter by human if specified
        if human_id:
            requests = [r for r in requests if r.assigned_human == human_id or not r.assigned_human]
        
        # Sort by urgency and deadline
        requests.sort(key=lambda r: (r.urgency_score, r.deadline), reverse=True)
        
        return requests
    
    async def get_intervention_stats(self) -> Dict[str, Any]:
        """Get intervention statistics."""
        
        stats = {
            "active_requests": len(self.active_requests),
            "total_requests": len(self.request_history) + len(self.active_requests),
            "requests_by_trigger": {},
            "requests_by_level": {},
            "average_response_time": self._calculate_average_response_time(),
            "escalation_rate": self._calculate_escalation_rate(),
            "resolution_rate": self._calculate_resolution_rate()
        }
        
        # Calculate by trigger
        for request in self.active_requests.values():
            trigger = request.trigger.value
            stats["requests_by_trigger"][trigger] = stats["requests_by_trigger"].get(trigger, 0) + 1
        
        # Calculate by level
        for request in self.active_requests.values():
            level = request.level.value
            stats["requests_by_level"][level] = stats["requests_by_level"].get(level, 0) + 1
        
        return stats
    
    def _find_matching_point(self, trigger: InterventionTrigger, context: Dict[str, Any]) -> Optional[InterventionPoint]:
        """Find matching intervention point for trigger."""
        
        for point in self.intervention_points.values():
            for condition in point.trigger_conditions:
                if condition["trigger"] == trigger.value:
                    # Check if context meets threshold
                    threshold = condition.get("threshold", 0.5)
                    context_value = context.get(trigger.value.replace("_", "_"), 0.0)
                    
                    if context_value >= threshold:
                        return point
        
        return None
    
    async def _create_approval_request(self, request: InterventionRequest, point: InterventionPoint) -> None:
        """Create approval request for intervention."""
        
        approval_data = {
            "request_type": "decision",
            "title": f"Intervention Required: {point.name}",
            "description": request.human_input_required,
            "requester_id": "ai_system",
            "requester_name": "AI System",
            "context": request.context,
            "decision_data": request.ai_decision,
            "consequences": [f"Urgency: {request.urgency_score:.2f}"],
            "alternatives": [],
            "risk_assessment": request.risk_assessment,
            "compliance_requirements": point.context_requirements,
            "priority": request.level.value,
            "expires_at": request.deadline.isoformat()
        }
        
        await self.approval_queue.submit_approval_request(approval_data)
    
    def _calculate_average_response_time(self) -> float:
        """Calculate average response time in minutes."""
        
        if not self.request_history:
            return 0.0
        
        total_time = timedelta()
        count = 0
        
        for request in self.request_history:
            if request.assigned_human and request.deadline:
                response_time = request.deadline - request.created_at
                total_time += response_time
                count += 1
        
        if count == 0:
            return 0.0
        
        return total_time.total_seconds() / (count * 60)  # Convert to minutes
    
    def _calculate_escalation_rate(self) -> float:
        """Calculate escalation rate as percentage."""
        
        total_requests = len(self.request_history) + len(self.active_requests)
        escalated_requests = sum(1 for r in self.request_history if r.escalation_count > 0)
        
        if total_requests == 0:
            return 0.0
        
        return (escalated_requests / total_requests) * 100
    
    def _calculate_resolution_rate(self) -> float:
        """Calculate resolution rate as percentage."""
        
        total_requests = len(self.request_history) + len(self.active_requests)
        resolved_requests = len(self.request_history)
        
        if total_requests == 0:
            return 0.0
        
        return (resolved_requests / total_requests) * 100
    
    async def _monitor_active_requests(self) -> None:
        """Background task to monitor active requests."""
        
        while True:
            try:
                now = datetime.now()
                expired_requests = []
                
                for request_id, request in self.active_requests.items():
                    if request.deadline < now:
                        expired_requests.append(request_id)
                
                for request_id in expired_requests:
                    request = self.active_requests[request_id]
                    
                    # Escalate if not already escalated too many times
                    point = self.intervention_points[request.point_id]
                    if request.escalation_count < point.escalation_policy.get("max_escalations", 2):
                        await self.escalate_intervention(request_id, "Deadline exceeded")
                    else:
                        # Mark as cancelled
                        request.status = InterventionStatus.CANCELLED
                        self.request_history.append(request)
                        del self.active_requests[request_id]
                        
                        await self.event_bus.emit(Event(
                            type="intervention_cancelled",
                            data={
                                "request_id": request_id,
                                "reason": "Deadline exceeded and max escalations reached"
                            }
                        ))
                
                # Sleep for 1 minute
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Error in monitoring task: {e}")
                await asyncio.sleep(30)
    
    async def shutdown(self) -> None:
        """Shutdown the intervention manager."""
        
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Intervention manager shutdown completed")