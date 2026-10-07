"""Approval Queue — Human-in-the-Loop approval system for critical decisions.

This module provides:
- Queue management for human approvals
- Priority-based approval routing
- Approval workflow orchestration
- Decision tracking and audit trails
- Integration with agent systems
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from backend.observability.event_bus import EventBus
from backend.observability.events import Event

logger = logging.getLogger(__name__)


class ApprovalStatus(Enum):
    """Status of approval requests."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalPriority(Enum):
    """Priority levels for approval requests."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class ApprovalType(Enum):
    """Types of approval requests."""
    DECISION = "decision"           # Critical decision approval
    ACTION = "action"              # Action execution approval
    RESOURCE = "resource"          # Resource allocation approval
    SECURITY = "security"          # Security-related approval
    DEPLOYMENT = "deployment"      # Deployment approval
    CONFIGURATION = "configuration" # Configuration change approval
    ACCESS = "access"              # Access control approval
    POLICY = "policy"              # Policy change approval


@dataclass
class ApprovalRequest:
    """Represents an approval request."""
    request_id: str
    request_type: ApprovalType
    priority: ApprovalPriority
    title: str
    description: str
    requester_id: str
    requester_name: str
    context: dict[str, Any]
    decision_data: dict[str, Any]
    consequences: list[str]
    alternatives: list[dict[str, Any]]
    risk_assessment: dict[str, Any]
    compliance_requirements: list[str]
    created_at: datetime
    expires_at: datetime | None
    status: ApprovalStatus = ApprovalStatus.PENDING
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None
    comments: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApprovalDecision:
    """Represents an approval decision."""
    request_id: str
    decision: ApprovalStatus
    decision_maker: str
    decision_time: datetime
    reasoning: str
    conditions: list[str] = field(default_factory=list)
    follow_up_required: bool = False
    follow_up_actions: list[str] = field(default_factory=list)


class ApprovalQueue:
    """Manages approval requests and decisions."""
    
    def __init__(self, event_bus: EventBus, max_queue_size: int = 1000):
        self.event_bus = event_bus
        self.max_queue_size = max_queue_size
        self.pending_requests: dict[str, ApprovalRequest] = {}
        self.approved_requests: dict[str, ApprovalRequest] = {}
        self.rejected_requests: dict[str, ApprovalRequest] = {}
        self.expired_requests: dict[str, ApprovalRequest] = {}
        self.approval_history: list[ApprovalDecision] = []
        self.approvers: dict[str, dict[str, Any]] = {}
        self.approval_policies: dict[ApprovalType, dict[str, Any]] = {}
        
        # Initialize default policies
        self._initialize_default_policies()
        
        # Start background tasks
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_requests())
    
    def _initialize_default_policies(self) -> None:
        """Initialize default approval policies."""
        self.approval_policies = {
            ApprovalType.DECISION: {
                "default_priority": ApprovalPriority.HIGH,
                "default_expiry": timedelta(hours=24),
                "required_approvers": 1,
                "auto_approve_threshold": 0.9,
                "escalation_threshold": 0.1
            },
            ApprovalType.ACTION: {
                "default_priority": ApprovalPriority.MEDIUM,
                "default_expiry": timedelta(hours=12),
                "required_approvers": 1,
                "auto_approve_threshold": 0.8,
                "escalation_threshold": 0.2
            },
            ApprovalType.SECURITY: {
                "default_priority": ApprovalPriority.CRITICAL,
                "default_expiry": timedelta(hours=6),
                "required_approvers": 2,
                "auto_approve_threshold": 0.95,
                "escalation_threshold": 0.05
            },
            ApprovalType.DEPLOYMENT: {
                "default_priority": ApprovalPriority.HIGH,
                "default_expiry": timedelta(hours=8),
                "required_approvers": 1,
                "auto_approve_threshold": 0.85,
                "escalation_threshold": 0.15
            }
        }
    
    async def submit_approval_request(self, request_data: dict[str, Any]) -> str:
        """Submit a new approval request."""
        
        # Validate request data
        required_fields = ["request_type", "title", "description", "requester_id", "context", "decision_data"]
        for field_name in required_fields:
            if field_name not in request_data:
                raise ValueError(f"Missing required field: {field_name}")
        
        # Create approval request
        request_id = str(uuid.uuid4())
        request_type = ApprovalType(request_data["request_type"])
        policy = self.approval_policies.get(request_type, self.approval_policies[ApprovalType.DECISION])
        
        # Set expiry time
        expires_at = None
        if "expires_at" in request_data:
            expires_at = datetime.fromisoformat(request_data["expires_at"])
        else:
            expires_at = datetime.now() + policy["default_expiry"]
        
        # Determine priority
        priority = ApprovalPriority(request_data.get("priority", policy["default_priority"].value))
        
        approval_request = ApprovalRequest(
            request_id=request_id,
            request_type=request_type,
            priority=priority,
            title=request_data["title"],
            description=request_data["description"],
            requester_id=request_data["requester_id"],
            requester_name=request_data.get("requester_name", request_data["requester_id"]),
            context=request_data["context"],
            decision_data=request_data["decision_data"],
            consequences=request_data.get("consequences", []),
            alternatives=request_data.get("alternatives", []),
            risk_assessment=request_data.get("risk_assessment", {}),
            compliance_requirements=request_data.get("compliance_requirements", []),
            created_at=datetime.now(),
            expires_at=expires_at,
            metadata=request_data.get("metadata", {})
        )
        
        # Check queue size
        if len(self.pending_requests) >= self.max_queue_size:
            # Remove oldest low-priority requests
            await self._cleanup_low_priority_requests()
        
        # Add to queue
        self.pending_requests[request_id] = approval_request
        
        # Emit submission event
        await self.event_bus.emit(Event(
            type="approval_request_submitted",
            data={
                "request_id": request_id,
                "request_type": request_type.value,
                "priority": priority.value,
                "requester_id": request_data["requester_id"]
            }
        ))
        
        logger.info(f"Approval request submitted: {request_id} ({request_type.value})")
        
        # Check for auto-approval
        await self._check_auto_approval(approval_request)
        
        return request_id
    
    async def approve_request(self, request_id: str, approver_id: str, 
                            reasoning: str, conditions: list[str] = None) -> bool:
        """Approve an approval request."""
        
        if request_id not in self.pending_requests:
            return False
        
        request = self.pending_requests[request_id]
        
        # Update request
        request.status = ApprovalStatus.APPROVED
        request.approved_by = approver_id
        request.approved_at = datetime.now()
        request.comments.append(f"Approved by {approver_id}: {reasoning}")
        
        if conditions:
            request.comments.extend([f"Condition: {condition}" for condition in conditions])
        
        # Move to approved
        self.approved_requests[request_id] = request
        del self.pending_requests[request_id]
        
        # Record decision
        decision = ApprovalDecision(
            request_id=request_id,
            decision=ApprovalStatus.APPROVED,
            decision_maker=approver_id,
            decision_time=datetime.now(),
            reasoning=reasoning,
            conditions=conditions or []
        )
        self.approval_history.append(decision)
        
        # Emit approval event
        await self.event_bus.emit(Event(
            type="approval_request_approved",
            data={
                "request_id": request_id,
                "approver_id": approver_id,
                "decision_time": decision.decision_time.isoformat()
            }
        ))
        
        logger.info(f"Approval request approved: {request_id} by {approver_id}")
        
        return True
    
    async def reject_request(self, request_id: str, approver_id: str, 
                           reasoning: str) -> bool:
        """Reject an approval request."""
        
        if request_id not in self.pending_requests:
            return False
        
        request = self.pending_requests[request_id]
        
        # Update request
        request.status = ApprovalStatus.REJECTED
        request.rejection_reason = reasoning
        request.comments.append(f"Rejected by {approver_id}: {reasoning}")
        
        # Move to rejected
        self.rejected_requests[request_id] = request
        del self.pending_requests[request_id]
        
        # Record decision
        decision = ApprovalDecision(
            request_id=request_id,
            decision=ApprovalStatus.REJECTED,
            decision_maker=approver_id,
            decision_time=datetime.now(),
            reasoning=reasoning
        )
        self.approval_history.append(decision)
        
        # Emit rejection event
        await self.event_bus.emit(Event(
            type="approval_request_rejected",
            data={
                "request_id": request_id,
                "approver_id": approver_id,
                "decision_time": decision.decision_time.isoformat(),
                "reasoning": reasoning
            }
        ))
        
        logger.info(f"Approval request rejected: {request_id} by {approver_id}")
        
        return True
    
    async def get_pending_requests(self, approver_id: str = None, 
                                 request_type: ApprovalType = None) -> list[ApprovalRequest]:
        """Get pending approval requests."""
        
        requests = list(self.pending_requests.values())
        
        # Filter by approver if specified
        if approver_id:
            approver_info = self.approvers.get(approver_id, {})
            allowed_types = approver_info.get("allowed_types", [t.value for t in ApprovalType])
            requests = [r for r in requests if r.request_type.value in allowed_types]
        
        # Filter by request type if specified
        if request_type:
            requests = [r for r in requests if r.request_type == request_type]
        
        # Sort by priority and creation time
        priority_order = {
            ApprovalPriority.EMERGENCY: 0,
            ApprovalPriority.CRITICAL: 1,
            ApprovalPriority.HIGH: 2,
            ApprovalPriority.MEDIUM: 3,
            ApprovalPriority.LOW: 4
        }
        
        requests.sort(key=lambda r: (priority_order[r.priority], r.created_at))
        
        return requests
    
    async def get_request_details(self, request_id: str) -> ApprovalRequest | None:
        """Get details of a specific approval request."""
        
        # Check all request stores
        for store in [self.pending_requests, self.approved_requests, 
                     self.rejected_requests, self.expired_requests]:
            if request_id in store:
                return store[request_id]
        
        return None
    
    async def get_approval_history(self, requester_id: str = None, 
                                 start_date: datetime = None, 
                                 end_date: datetime = None) -> list[ApprovalDecision]:
        """Get approval history."""
        
        history = self.approval_history.copy()
        
        # Filter by requester if specified
        if requester_id:
            history = [d for d in history if self._get_requester_id(d.request_id) == requester_id]
        
        # Filter by date range if specified
        if start_date:
            history = [d for d in history if d.decision_time >= start_date]
        if end_date:
            history = [d for d in history if d.decision_time <= end_date]
        
        # Sort by decision time (newest first)
        history.sort(key=lambda d: d.decision_time, reverse=True)
        
        return history
    
    async def get_queue_stats(self) -> dict[str, Any]:
        """Get queue statistics."""
        
        stats = {
            "pending_requests": len(self.pending_requests),
            "approved_requests": len(self.approved_requests),
            "rejected_requests": len(self.rejected_requests),
            "expired_requests": len(self.expired_requests),
            "total_decisions": len(self.approval_history),
            "pending_by_priority": {},
            "pending_by_type": {},
            "average_approval_time": self._calculate_average_approval_time(),
            "approval_rate": self._calculate_approval_rate()
        }
        
        # Calculate pending by priority
        for request in self.pending_requests.values():
            priority = request.priority.value
            stats["pending_by_priority"][priority] = stats["pending_by_priority"].get(priority, 0) + 1
        
        # Calculate pending by type
        for request in self.pending_requests.values():
            req_type = request.request_type.value
            stats["pending_by_type"][req_type] = stats["pending_by_type"].get(req_type, 0) + 1
        
        return stats
    
    async def register_approver(self, approver_id: str, approver_info: dict[str, Any]) -> None:
        """Register a human approver."""
        
        self.approvers[approver_id] = {
            "name": approver_info.get("name", approver_id),
            "email": approver_info.get("email", ""),
            "role": approver_info.get("role", "approver"),
            "allowed_types": approver_info.get("allowed_types", [t.value for t in ApprovalType]),
            "max_approvals_per_day": approver_info.get("max_approvals_per_day", 50),
            "working_hours": approver_info.get("working_hours", {"start": "09:00", "end": "17:00"}),
            "timezone": approver_info.get("timezone", "UTC"),
            "registered_at": datetime.now()
        }
        
        # Emit registration event
        await self.event_bus.emit(Event(
            type="approver_registered",
            data={
                "approver_id": approver_id,
                "name": approver_info.get("name", approver_id),
                "role": approver_info.get("role", "approver")
            }
        ))
        
        logger.info(f"Approver registered: {approver_id}")
    
    async def _check_auto_approval(self, request: ApprovalRequest) -> None:
        """Check if request can be auto-approved."""
        
        policy = self.approval_policies.get(request.request_type, {})
        auto_approve_threshold = policy.get("auto_approve_threshold", 0.9)
        
        # Calculate approval score based on risk assessment
        risk_score = request.risk_assessment.get("risk_score", 0.5)
        
        # Auto-approve if risk is very low
        if risk_score <= (1.0 - auto_approve_threshold):
            await self.approve_request(
                request.request_id,
                "system_auto_approval",
                f"Auto-approved: Risk score {risk_score:.2f} below threshold {1.0 - auto_approve_threshold:.2f}"
            )
            
            await self.event_bus.emit(Event(
                type="approval_auto_approved",
                data={
                    "request_id": request.request_id,
                    "risk_score": risk_score,
                    "threshold": 1.0 - auto_approve_threshold
                }
            ))
    
    async def _cleanup_expired_requests(self) -> None:
        """Background task to clean up expired requests."""
        
        while True:
            try:
                now = datetime.now()
                expired_requests = []
                
                for request_id, request in self.pending_requests.items():
                    if request.expires_at and request.expires_at < now:
                        expired_requests.append(request_id)
                
                for request_id in expired_requests:
                    request = self.pending_requests[request_id]
                    request.status = ApprovalStatus.EXPIRED
                    self.expired_requests[request_id] = request
                    del self.pending_requests[request_id]
                    
                    # Emit expiration event
                    await self.event_bus.emit(Event(
                        type="approval_request_expired",
                        data={
                            "request_id": request_id,
                            "expired_at": now.isoformat()
                        }
                    ))
                    
                    logger.info(f"Approval request expired: {request_id}")
                
                # Sleep for 5 minutes
                await asyncio.sleep(300)
                
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                await asyncio.sleep(60)
    
    async def _cleanup_low_priority_requests(self) -> None:
        """Remove oldest low-priority requests to make space."""
        
        # Sort by priority and creation time
        priority_order = {
            ApprovalPriority.EMERGENCY: 0,
            ApprovalPriority.CRITICAL: 1,
            ApprovalPriority.HIGH: 2,
            ApprovalPriority.MEDIUM: 3,
            ApprovalPriority.LOW: 4
        }
        
        sorted_requests = sorted(
            self.pending_requests.items(),
            key=lambda x: (priority_order[x[1].priority], x[1].created_at),
            reverse=True
        )
        
        # Remove oldest low-priority requests
        removed_count = 0
        for request_id, request in sorted_requests:
            if removed_count >= 10:  # Remove max 10 at once
                break
            
            if request.priority in [ApprovalPriority.LOW, ApprovalPriority.MEDIUM]:
                request.status = ApprovalStatus.CANCELLED
                del self.pending_requests[request_id]
                removed_count += 1
                
                logger.warning(f"Cancelled low-priority approval request: {request_id}")
    
    def _get_requester_id(self, request_id: str) -> str:
        """Get requester ID from request ID."""
        
        for store in [self.approved_requests, self.rejected_requests, self.expired_requests]:
            if request_id in store:
                return store[request_id].requester_id
        
        return "unknown"
    
    def _calculate_average_approval_time(self) -> float:
        """Calculate average approval time in hours."""
        
        if not self.approval_history:
            return 0.0
        
        total_time = timedelta()
        count = 0
        
        for decision in self.approval_history:
            request = self._get_request_by_id(decision.request_id)
            if request and decision.decision_time:
                approval_time = decision.decision_time - request.created_at
                total_time += approval_time
                count += 1
        
        if count == 0:
            return 0.0
        
        return total_time.total_seconds() / (count * 3600)  # Convert to hours
    
    def _calculate_approval_rate(self) -> float:
        """Calculate approval rate as percentage."""
        
        total_decisions = len(self.approved_requests) + len(self.rejected_requests)
        if total_decisions == 0:
            return 0.0
        
        return (len(self.approved_requests) / total_decisions) * 100
    
    def _get_request_by_id(self, request_id: str) -> ApprovalRequest | None:
        """Get request by ID from any store."""
        
        for store in [self.approved_requests, self.rejected_requests, self.expired_requests]:
            if request_id in store:
                return store[request_id]
        
        return None
    
    async def shutdown(self) -> None:
        """Shutdown the approval queue."""
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
        
        logger.info("Approval queue shutdown completed")