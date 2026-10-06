"""Oversight Interface — Main Human-in-the-Loop interface for AI system oversight.

This module provides:
- Unified interface for human oversight
- Integration with approval and intervention systems
- Real-time monitoring and alerts
- Human-AI collaboration workflows
- Oversight analytics and reporting
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

from backend.human_oversight.approval_queue import ApprovalPriority, ApprovalQueue, ApprovalType
from backend.human_oversight.intervention_points import InterventionManager
from backend.observability.event_bus import EventBus
from backend.observability.events import Event

logger = logging.getLogger(__name__)


class OversightRole(Enum):
    """Roles for human oversight."""
    APPROVER = "approver"              # Can approve/reject requests
    INTERVENTIONIST = "interventionist" # Can handle interventions
    MONITOR = "monitor"               # Can monitor system activity
    ADMINISTRATOR = "administrator"   # Full administrative access
    AUDITOR = "auditor"               # Can audit system behavior


class OversightLevel(Enum):
    """Levels of oversight required."""
    MINIMAL = "minimal"              # Basic monitoring only
    STANDARD = "standard"            # Standard oversight procedures
    ENHANCED = "enhanced"             # Enhanced oversight with more checks
    CRITICAL = "critical"             # Critical oversight for high-risk operations


@dataclass
class OversightSession:
    """Represents a human oversight session."""
    session_id: str
    human_id: str
    role: OversightRole
    start_time: datetime
    end_time: datetime | None
    activities: list[dict[str, Any]]
    decisions_made: int
    interventions_handled: int
    approvals_processed: int
    session_quality: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OversightAlert:
    """Represents an oversight alert."""
    alert_id: str
    alert_type: str
    severity: str
    title: str
    description: str
    context: dict[str, Any]
    required_action: str
    deadline: datetime | None
    assigned_to: str | None
    status: str
    created_at: datetime
    resolved_at: datetime | None


class HumanOversightInterface:
    """Main interface for human oversight of AI systems."""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.approval_queue = ApprovalQueue(event_bus)
        self.intervention_manager = InterventionManager(event_bus, self.approval_queue)
        
        # Oversight sessions
        self.active_sessions: dict[str, OversightSession] = {}
        self.session_history: list[OversightSession] = []
        
        # Human operators
        self.humans: dict[str, dict[str, Any]] = {}
        
        # Alerts and notifications
        self.active_alerts: dict[str, OversightAlert] = {}
        self.alert_history: list[OversightAlert] = []
        
        # Oversight policies
        self.oversight_policies: dict[str, dict[str, Any]] = {}
        
        # Analytics
        self.oversight_metrics: dict[str, Any] = {}
        
        # Initialize default policies
        self._initialize_default_policies()
        
        # Start background tasks
        self._alert_monitoring_task = asyncio.create_task(self._monitor_alerts())
        self._session_monitoring_task = asyncio.create_task(self._monitor_sessions())
    
    def _initialize_default_policies(self) -> None:
        """Initialize default oversight policies."""
        
        self.oversight_policies = {
            "standard_operations": {
                "required_level": OversightLevel.STANDARD,
                "approval_required": True,
                "intervention_threshold": 0.7,
                "session_timeout_minutes": 240,
                "max_decisions_per_session": 50,
                "quality_threshold": 0.8
            },
            "high_risk_operations": {
                "required_level": OversightLevel.ENHANCED,
                "approval_required": True,
                "intervention_threshold": 0.5,
                "session_timeout_minutes": 180,
                "max_decisions_per_session": 30,
                "quality_threshold": 0.9
            },
            "critical_operations": {
                "required_level": OversightLevel.CRITICAL,
                "approval_required": True,
                "intervention_threshold": 0.3,
                "session_timeout_minutes": 120,
                "max_decisions_per_session": 20,
                "quality_threshold": 0.95
            }
        }
    
    async def register_human_operator(self, human_id: str, human_info: dict[str, Any]) -> None:
        """Register a human operator for oversight."""
        
        self.humans[human_id] = {
            "name": human_info.get("name", human_id),
            "email": human_info.get("email", ""),
            "role": OversightRole(human_info.get("role", "monitor")),
            "permissions": human_info.get("permissions", []),
            "expertise_areas": human_info.get("expertise_areas", []),
            "working_hours": human_info.get("working_hours", {"start": "09:00", "end": "17:00"}),
            "timezone": human_info.get("timezone", "UTC"),
            "max_sessions_per_day": human_info.get("max_sessions_per_day", 5),
            "quality_threshold": human_info.get("quality_threshold", 0.8),
            "registered_at": datetime.now()
        }
        
        # Register with approval queue
        await self.approval_queue.register_approver(human_id, {
            "name": human_info.get("name", human_id),
            "email": human_info.get("email", ""),
            "role": human_info.get("role", "approver"),
            "allowed_types": self._get_allowed_approval_types(human_info.get("role", "monitor"))
        })
        
        # Emit registration event
        await self.event_bus.emit(Event(
            type="human_operator_registered",
            data={
                "human_id": human_id,
                "name": human_info.get("name", human_id),
                "role": human_info.get("role", "monitor")
            }
        ))
        
        logger.info(f"Human operator registered: {human_id}")
    
    async def start_oversight_session(self, human_id: str, operation_type: str, 
                                    context: dict[str, Any] = None) -> str:
        """Start an oversight session."""
        
        if human_id not in self.humans:
            raise ValueError(f"Human operator not registered: {human_id}")
        
        # Check if human already has active session
        if human_id in [s.human_id for s in self.active_sessions.values()]:
            raise ValueError(f"Human {human_id} already has active session")
        
        # Get policy for operation type
        policy = self.oversight_policies.get(operation_type, self.oversight_policies["standard_operations"])
        
        # Create session
        session_id = str(uuid.uuid4())
        session = OversightSession(
            session_id=session_id,
            human_id=human_id,
            role=self.humans[human_id]["role"],
            start_time=datetime.now(),
            end_time=None,
            activities=[],
            decisions_made=0,
            interventions_handled=0,
            approvals_processed=0,
            session_quality=0.0,
            metadata={
                "operation_type": operation_type,
                "policy": policy,
                "context": context or {}
            }
        )
        
        # Store session
        self.active_sessions[session_id] = session
        
        # Emit session start event
        await self.event_bus.emit(Event(
            type="oversight_session_started",
            data={
                "session_id": session_id,
                "human_id": human_id,
                "operation_type": operation_type,
                "role": session.role.value
            }
        ))
        
        logger.info(f"Oversight session started: {session_id} by {human_id}")
        
        return session_id
    
    async def end_oversight_session(self, session_id: str, summary: dict[str, Any] = None) -> bool:
        """End an oversight session."""
        
        if session_id not in self.active_sessions:
            return False
        
        session = self.active_sessions[session_id]
        
        # Calculate session quality
        session.session_quality = self._calculate_session_quality(session)
        
        # End session
        session.end_time = datetime.now()
        
        # Add summary if provided
        if summary:
            session.metadata["summary"] = summary
        
        # Move to history
        self.session_history.append(session)
        del self.active_sessions[session_id]
        
        # Emit session end event
        await self.event_bus.emit(Event(
            type="oversight_session_ended",
            data={
                "session_id": session_id,
                "human_id": session.human_id,
                "duration_minutes": (session.end_time - session.start_time).total_seconds() / 60,
                "quality_score": session.session_quality,
                "decisions_made": session.decisions_made,
                "interventions_handled": session.interventions_handled,
                "approvals_processed": session.approvals_processed
            }
        ))
        
        logger.info(f"Oversight session ended: {session_id}")
        
        return True
    
    async def request_oversight(self, context: dict[str, Any]) -> dict[str, Any]:
        """Request human oversight for AI operations."""
        
        # Determine operation type and required level
        operation_type = context.get("operation_type", "standard_operations")
        policy = self.oversight_policies.get(operation_type, self.oversight_policies["standard_operations"])
        
        # Check if intervention is needed
        intervention_requests = await self.intervention_manager.request_intervention(context)
        
        # Check if approval is needed
        approval_requests = []
        if policy["approval_required"]:
            approval_data = {
                "request_type": "decision",
                "title": f"Oversight Required: {operation_type}",
                "description": context.get("description", "Human oversight required for this operation"),
                "requester_id": "ai_system",
                "requester_name": "AI System",
                "context": context,
                "decision_data": context.get("decision_data", {}),
                "consequences": context.get("consequences", []),
                "alternatives": context.get("alternatives", []),
                "risk_assessment": context.get("risk_assessment", {}),
                "compliance_requirements": policy.get("compliance_requirements", []),
                "priority": self._determine_approval_priority(context),
                "expires_at": (datetime.now() + timedelta(hours=policy.get("session_timeout_minutes", 240) / 60)).isoformat()
            }
            
            approval_id = await self.approval_queue.submit_approval_request(approval_data)
            approval_requests.append(approval_id)
        
        # Create oversight alert if needed
        alert_id = None
        if context.get("create_alert", False):
            alert_id = await self._create_oversight_alert(context)
        
        return {
            "intervention_requests": intervention_requests,
            "approval_requests": approval_requests,
            "alert_id": alert_id,
            "required_level": policy["required_level"].value,
            "oversight_policy": policy
        }
    
    async def get_oversight_dashboard(self, human_id: str) -> dict[str, Any]:
        """Get oversight dashboard for a human operator."""
        
        if human_id not in self.humans:
            return {"error": "Human operator not registered"}
        
        # Get active session
        active_session = None
        for session in self.active_sessions.values():
            if session.human_id == human_id:
                active_session = session
                break
        
        # Get pending approvals
        pending_approvals = await self.approval_queue.get_pending_requests(human_id)
        
        # Get active interventions
        active_interventions = await self.intervention_manager.get_active_interventions(human_id)
        
        # Get active alerts
        active_alerts = [alert for alert in self.active_alerts.values() 
                        if alert.assigned_to == human_id or not alert.assigned_to]
        
        # Get recent activity
        recent_sessions = [s for s in self.session_history 
                          if s.human_id == human_id][-10:]  # Last 10 sessions
        
        return {
            "human_info": self.humans[human_id],
            "active_session": {
                "session_id": active_session.session_id,
                "start_time": active_session.start_time.isoformat(),
                "operation_type": active_session.metadata.get("operation_type"),
                "decisions_made": active_session.decisions_made,
                "interventions_handled": active_session.interventions_handled,
                "approvals_processed": active_session.approvals_processed
            } if active_session else None,
            "pending_approvals": len(pending_approvals),
            "active_interventions": len(active_interventions),
            "active_alerts": len(active_alerts),
            "recent_sessions": len(recent_sessions),
            "overall_quality": self._calculate_human_quality_score(human_id),
            "stats": {
                "total_sessions": len(recent_sessions) + (1 if active_session else 0),
                "total_decisions": sum(s.decisions_made for s in recent_sessions) + 
                               (active_session.decisions_made if active_session else 0),
                "total_interventions": sum(s.interventions_handled for s in recent_sessions) + 
                                   (active_session.interventions_handled if active_session else 0),
                "total_approvals": sum(s.approvals_processed for s in recent_sessions) + 
                                 (active_session.approvals_processed if active_session else 0)
            }
        }
    
    async def get_system_oversight_stats(self) -> dict[str, Any]:
        """Get system-wide oversight statistics."""
        
        # Get approval queue stats
        approval_stats = await self.approval_queue.get_queue_stats()
        
        # Get intervention stats
        intervention_stats = await self.intervention_manager.get_intervention_stats()
        
        # Calculate session stats
        total_sessions = len(self.session_history) + len(self.active_sessions)
        active_sessions = len(self.active_sessions)
        avg_session_duration = self._calculate_average_session_duration()
        
        # Calculate human operator stats
        total_humans = len(self.humans)
        active_humans = len(set(s.human_id for s in self.active_sessions.values()))
        
        # Calculate quality metrics
        avg_quality_score = self._calculate_average_quality_score()
        
        return {
            "approval_stats": approval_stats,
            "intervention_stats": intervention_stats,
            "session_stats": {
                "total_sessions": total_sessions,
                "active_sessions": active_sessions,
                "average_duration_minutes": avg_session_duration,
                "total_decisions": sum(s.decisions_made for s in self.session_history) + 
                                 sum(s.decisions_made for s in self.active_sessions.values()),
                "total_interventions": sum(s.interventions_handled for s in self.session_history) + 
                                     sum(s.interventions_handled for s in self.active_sessions.values()),
                "total_approvals": sum(s.approvals_processed for s in self.session_history) + 
                                 sum(s.approvals_processed for s in self.active_sessions.values())
            },
            "human_stats": {
                "total_operators": total_humans,
                "active_operators": active_humans,
                "operators_by_role": self._get_operators_by_role()
            },
            "quality_metrics": {
                "average_quality_score": avg_quality_score,
                "high_quality_sessions": len([s for s in self.session_history if s.session_quality > 0.8]),
                "low_quality_sessions": len([s for s in self.session_history if s.session_quality < 0.6])
            },
            "alert_stats": {
                "active_alerts": len(self.active_alerts),
                "total_alerts": len(self.alert_history),
                "alerts_by_severity": self._get_alerts_by_severity()
            }
        }
    
    def _get_allowed_approval_types(self, role: str) -> list[str]:
        """Get allowed approval types for a role."""
        
        role_permissions = {
            "monitor": [],
            "approver": ["decision", "action", "resource"],
            "interventionist": ["decision", "action", "security", "deployment"],
            "administrator": [t.value for t in ApprovalType],
            "auditor": ["decision", "action", "configuration"]
        }
        
        return role_permissions.get(role, [])
    
    def _determine_approval_priority(self, context: dict[str, Any]) -> str:
        """Determine approval priority based on context."""
        
        risk_score = context.get("risk_assessment", {}).get("overall_risk", 0.0)
        urgency = context.get("urgency", "normal")
        
        if risk_score > 0.8 or urgency == "emergency":
            return ApprovalPriority.EMERGENCY.value
        elif risk_score > 0.6 or urgency == "high":
            return ApprovalPriority.CRITICAL.value
        elif risk_score > 0.4 or urgency == "medium":
            return ApprovalPriority.HIGH.value
        else:
            return ApprovalPriority.MEDIUM.value
    
    def _calculate_session_quality(self, session: OversightSession) -> float:
        """Calculate quality score for a session."""
        
        if session.decisions_made == 0:
            return 0.5  # Neutral score for inactive sessions
        
        # Base quality on decisions made and session duration
        duration_minutes = (session.end_time or datetime.now() - session.start_time).total_seconds() / 60
        decisions_per_minute = session.decisions_made / max(duration_minutes, 1)
        
        # Quality factors
        decision_quality = min(1.0, decisions_per_minute / 2.0)  # Optimal: 2 decisions/minute
        intervention_quality = min(1.0, session.interventions_handled / max(session.decisions_made, 1))
        approval_quality = min(1.0, session.approvals_processed / max(session.decisions_made, 1))
        
        # Weighted average
        quality = (decision_quality * 0.4 + intervention_quality * 0.3 + approval_quality * 0.3)
        
        return quality
    
    def _calculate_human_quality_score(self, human_id: str) -> float:
        """Calculate overall quality score for a human operator."""
        
        human_sessions = [s for s in self.session_history if s.human_id == human_id]
        
        if not human_sessions:
            return 0.5  # Neutral score for new operators
        
        # Average quality across sessions
        total_quality = sum(s.session_quality for s in human_sessions)
        return total_quality / len(human_sessions)
    
    def _calculate_average_session_duration(self) -> float:
        """Calculate average session duration in minutes."""
        
        all_sessions = self.session_history + list(self.active_sessions.values())
        
        if not all_sessions:
            return 0.0
        
        total_duration = timedelta()
        count = 0
        
        for session in all_sessions:
            end_time = session.end_time or datetime.now()
            duration = end_time - session.start_time
            total_duration += duration
            count += 1
        
        if count == 0:
            return 0.0
        
        return total_duration.total_seconds() / (count * 60)  # Convert to minutes
    
    def _calculate_average_quality_score(self) -> float:
        """Calculate average quality score across all sessions."""
        
        all_sessions = self.session_history + list(self.active_sessions.values())
        
        if not all_sessions:
            return 0.0
        
        total_quality = sum(s.session_quality for s in all_sessions)
        return total_quality / len(all_sessions)
    
    def _get_operators_by_role(self) -> dict[str, int]:
        """Get count of operators by role."""
        
        role_counts = {}
        
        for human in self.humans.values():
            role = human["role"].value
            role_counts[role] = role_counts.get(role, 0) + 1
        
        return role_counts
    
    def _get_alerts_by_severity(self) -> dict[str, int]:
        """Get count of alerts by severity."""
        
        severity_counts = {}
        
        for alert in self.active_alerts.values():
            severity = alert.severity
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
        
        return severity_counts
    
    async def _create_oversight_alert(self, context: dict[str, Any]) -> str:
        """Create an oversight alert."""
        
        alert_id = str(uuid.uuid4())
        
        alert = OversightAlert(
            alert_id=alert_id,
            alert_type=context.get("alert_type", "oversight_required"),
            severity=context.get("severity", "medium"),
            title=context.get("title", "Oversight Alert"),
            description=context.get("description", "Human oversight required"),
            context=context,
            required_action=context.get("required_action", "review"),
            deadline=datetime.fromisoformat(context["deadline"]) if context.get("deadline") else None,
            assigned_to=context.get("assigned_to"),
            status="active",
            created_at=datetime.now()
        )
        
        self.active_alerts[alert_id] = alert
        
        # Emit alert event
        await self.event_bus.emit(Event(
            type="oversight_alert_created",
            data={
                "alert_id": alert_id,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "assigned_to": alert.assigned_to
            }
        ))
        
        return alert_id
    
    async def _monitor_alerts(self) -> None:
        """Background task to monitor alerts."""
        
        while True:
            try:
                now = datetime.now()
                expired_alerts = []
                
                for alert_id, alert in self.active_alerts.items():
                    if alert.deadline and alert.deadline < now:
                        expired_alerts.append(alert_id)
                
                for alert_id in expired_alerts:
                    alert = self.active_alerts[alert_id]
                    alert.status = "expired"
                    alert.resolved_at = now
                    
                    # Move to history
                    self.alert_history.append(alert)
                    del self.active_alerts[alert_id]
                    
                    await self.event_bus.emit(Event(
                        type="oversight_alert_expired",
                        data={
                            "alert_id": alert_id,
                            "expired_at": now.isoformat()
                        }
                    ))
                
                # Sleep for 5 minutes
                await asyncio.sleep(300)
                
            except Exception as e:
                logger.error(f"Error in alert monitoring: {e}")
                await asyncio.sleep(60)
    
    async def _monitor_sessions(self) -> None:
        """Background task to monitor sessions."""
        
        while True:
            try:
                now = datetime.now()
                expired_sessions = []
                
                for session_id, session in self.active_sessions.items():
                    # Check session timeout
                    policy = session.metadata.get("policy", {})
                    timeout_minutes = policy.get("session_timeout_minutes", 240)
                    
                    if (now - session.start_time).total_seconds() > (timeout_minutes * 60):
                        expired_sessions.append(session_id)
                
                for session_id in expired_sessions:
                    await self.end_oversight_session(session_id, {
                        "reason": "Session timeout",
                        "auto_ended": True
                    })
                
                # Sleep for 1 minute
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Error in session monitoring: {e}")
                await asyncio.sleep(30)
    
    async def shutdown(self) -> None:
        """Shutdown the oversight interface."""
        
        # Cancel background tasks
        if self._alert_monitoring_task:
            self._alert_monitoring_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._alert_monitoring_task
        
        if self._session_monitoring_task:
            self._session_monitoring_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._session_monitoring_task
        
        # End all active sessions
        for session_id in list(self.active_sessions.keys()):
            await self.end_oversight_session(session_id, {
                "reason": "System shutdown",
                "auto_ended": True
            })
        
        # Shutdown components
        await self.approval_queue.shutdown()
        await self.intervention_manager.shutdown()
        
        logger.info("Human oversight interface shutdown completed")