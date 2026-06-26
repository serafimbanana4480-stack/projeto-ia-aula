"""WorkflowTracker — track workflow lifecycle with timeline and replay.

Stores workflow steps, agent communications, and outcomes
for dashboard visualization and debugging.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStep:
    """A single step in a workflow."""

    step_id: str = field(default_factory=lambda: f"step-{uuid.uuid4().hex[:8]}")
    name: str = ""  # e.g., "decompose", "generate", "test", "repair"
    agent: str = ""  # Agent responsible
    status: str = "pending"  # pending, running, completed, failed, skipped
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_ms: float = 0.0
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "agent": self.agent,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "error": self.error,
        }


@dataclass
class AgentMessage:
    """Structured message between agents."""

    msg_id: str = field(default_factory=lambda: f"msg-{uuid.uuid4().hex[:8]}")
    from_agent: str = ""
    to_agent: str = ""
    message_type: str = "consult"  # consult, delegate, report, conflict
    content: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "msg_id": self.msg_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "message_type": self.message_type,
            "content": self.content,
            "context": self.context,
            "timestamp": self.timestamp,
        }


@dataclass
class Workflow:
    """A complete workflow with all steps and metadata."""

    workflow_id: str = field(default_factory=lambda: f"wf-{uuid.uuid4().hex[:8]}")
    story_id: str = ""
    goal: str = ""
    status: str = "pending"  # pending, running, completed, failed, cancelled
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    steps: list[WorkflowStep] = field(default_factory=list)
    messages: list[AgentMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "story_id": self.story_id,
            "goal": self.goal,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "steps": [s.to_dict() for s in self.steps],
            "messages": [m.to_dict() for m in self.messages],
            "metadata": self.metadata,
        }

    @property
    def duration_ms(self) -> float:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at) * 1000
        if self.started_at:
            return (time.time() - self.started_at) * 1000
        return 0.0


class WorkflowTracker:
    """Tracks and manages workflow lifecycle."""

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}
        self._active: dict[str, str] = {}  # story_id -> workflow_id

    def create_workflow(self, story_id: str, goal: str, metadata: dict[str, Any] | None = None) -> Workflow:
        """Create a new workflow."""
        workflow = Workflow(
            story_id=story_id,
            goal=goal,
            metadata=metadata or {},
        )
        self._workflows[workflow.workflow_id] = workflow
        self._active[story_id] = workflow.workflow_id
        logger.info("Created workflow %s for story %s", workflow.workflow_id, story_id)
        return workflow

    def start_workflow(self, workflow_id: str) -> Workflow | None:
        """Mark workflow as started."""
        wf = self._workflows.get(workflow_id)
        if wf:
            wf.status = "running"
            wf.started_at = time.time()
        return wf

    def add_step(self, workflow_id: str, name: str, agent: str, inputs: dict[str, Any] | None = None) -> WorkflowStep:
        """Add a step to a workflow."""
        wf = self._workflows.get(workflow_id)
        if not wf:
            raise KeyError(f"Workflow {workflow_id} not found")

        step = WorkflowStep(
            name=name,
            agent=agent,
            status="running",
            started_at=time.time(),
            inputs=inputs or {},
        )
        wf.steps.append(step)
        logger.debug("Added step %s to workflow %s", name, workflow_id)
        return step

    def complete_step(self, workflow_id: str, step_id: str, outputs: dict[str, Any] | None = None) -> None:
        """Mark a step as completed."""
        wf = self._workflows.get(workflow_id)
        if not wf:
            return

        for step in wf.steps:
            if step.step_id == step_id:
                step.status = "completed"
                step.completed_at = time.time()
                step.duration_ms = (step.completed_at - step.started_at) * 1000
                step.outputs = outputs or {}
                break

    def fail_step(self, workflow_id: str, step_id: str, error: str) -> None:
        """Mark a step as failed."""
        wf = self._workflows.get(workflow_id)
        if not wf:
            return

        for step in wf.steps:
            if step.step_id == step_id:
                step.status = "failed"
                step.completed_at = time.time()
                step.duration_ms = (step.completed_at - step.started_at) * 1000
                step.error = error
                break

    def log_message(self, workflow_id: str, from_agent: str, to_agent: str, message_type: str, content: str, context: dict[str, Any] | None = None) -> AgentMessage:
        """Log an inter-agent message."""
        wf = self._workflows.get(workflow_id)
        if not wf:
            raise KeyError(f"Workflow {workflow_id} not found")

        msg = AgentMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=message_type,
            content=content,
            context=context or {},
        )
        wf.messages.append(msg)

        # Detect conflicts
        if message_type == "conflict":
            logger.warning("Conflict detected in workflow %s: %s -> %s", workflow_id, from_agent, to_agent)

        return msg

    def complete_workflow(self, workflow_id: str, status: str = "completed") -> None:
        """Mark workflow as completed or failed."""
        wf = self._workflows.get(workflow_id)
        if wf:
            wf.status = status
            wf.completed_at = time.time()
            if wf.story_id in self._active:
                del self._active[wf.story_id]
            logger.info("Workflow %s completed with status %s", workflow_id, status)

    def get_workflow(self, workflow_id: str) -> Workflow | None:
        """Get a workflow by ID."""
        return self._workflows.get(workflow_id)

    def list_workflows(self, status: str | None = None, limit: int = 50) -> list[Workflow]:
        """List workflows, optionally filtered by status."""
        workflows = list(self._workflows.values())
        if status:
            workflows = [w for w in workflows if w.status == status]
        # Sort by created_at descending
        workflows.sort(key=lambda w: w.created_at, reverse=True)
        return workflows[:limit]

    def get_timeline(self, workflow_id: str) -> list[dict[str, Any]]:
        """Get step-by-step timeline for replay."""
        wf = self._workflows.get(workflow_id)
        if not wf:
            return []

        timeline = []
        for step in wf.steps:
            timeline.append({
                "type": "step",
                "step_id": step.step_id,
                "name": step.name,
                "agent": step.agent,
                "status": step.status,
                "started_at": step.started_at,
                "completed_at": step.completed_at,
                "duration_ms": step.duration_ms,
            })

        # Interleave messages
        for msg in wf.messages:
            timeline.append({
                "type": "message",
                "msg_id": msg.msg_id,
                "from_agent": msg.from_agent,
                "to_agent": msg.to_agent,
                "message_type": msg.message_type,
                "content": msg.content,
                "timestamp": msg.timestamp,
            })

        # Sort by timestamp
        timeline.sort(key=lambda x: x.get("started_at", x.get("timestamp", 0)))
        return timeline

    def export_workflow(self, workflow_id: str) -> str:
        """Export workflow as JSON string."""
        wf = self._workflows.get(workflow_id)
        if not wf:
            return "{}"
        return json.dumps(wf.to_dict(), indent=2)

    def detect_conflicts(self, workflow_id: str) -> list[dict[str, Any]]:
        """Detect and return conflicts in a workflow."""
        wf = self._workflows.get(workflow_id)
        if not wf:
            return []

        conflicts = []
        for msg in wf.messages:
            if msg.message_type == "conflict":
                conflicts.append(msg.to_dict())

        # Detect duplicate work (same agent, same step name, different step_id)
        step_names: dict[str, list[str]] = {}
        for step in wf.steps:
            key = f"{step.agent}:{step.name}"
            if key not in step_names:
                step_names[key] = []
            step_names[key].append(step.step_id)

        for key, step_ids in step_names.items():
            if len(step_ids) > 1:
                conflicts.append({
                    "type": "duplicate_work",
                    "agent_step": key,
                    "step_ids": step_ids,
                    "message": f"Agent performed same step {len(step_ids)} times",
                })

        return conflicts
