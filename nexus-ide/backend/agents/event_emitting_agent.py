"""Event Emitting Agent Base - Enhanced agent with real-time event emission.

This module provides:
- Base agent class with event emission
- Real-time status updates
- Performance metrics tracking
- Heartbeat management
- Task lifecycle events
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, AsyncIterator
from dataclasses import dataclass, field
from enum import Enum

from backend.agents.base import AgentBase, AgentRequest
from backend.observability.event_system import EventBus, Event, EventType, EventPriority
from backend.observability.events import Event as ObservabilityEvent

logger = logging.getLogger(__name__)


class AgentState(str, Enum):
    """Agent execution states."""
    IDLE = "idle"
    STARTING = "starting"
    BUSY = "busy"
    THINKING = "thinking"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    ERROR = "error"
    OFFLINE = "offline"


@dataclass
class AgentMetrics:
    """Agent performance metrics."""
    agent_id: str
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_tokens: int = 0
    total_processing_time: float = 0.0
    average_response_time: float = 0.0
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    last_heartbeat: datetime = field(default_factory=datetime.now)
    uptime: float = 0.0
    error_rate: float = 0.0
    
    def update_task_completed(self, processing_time: float, tokens: int = 0) -> None:
        """Update metrics after task completion."""
        self.tasks_completed += 1
        self.total_processing_time += processing_time
        self.total_tokens += tokens
        self.average_response_time = self.total_processing_time / self.tasks_completed
        self.error_rate = self.tasks_failed / max(1, self.tasks_completed + self.tasks_failed)
    
    def update_task_failed(self) -> None:
        """Update metrics after task failure."""
        self.tasks_failed += 1
        self.error_rate = self.tasks_failed / max(1, self.tasks_completed + self.tasks_failed)


class EventEmittingAgent(AgentBase):
    """Enhanced agent base class with real-time event emission."""
    
    def __init__(self, name: str, event_bus: Optional[EventBus] = None):
        super().__init__(name)
        self.event_bus = event_bus
        self.state = AgentState.IDLE
        self.metrics = AgentMetrics(agent_id=name)
        self.current_task_id: Optional[str] = None
        self.heartbeat_interval = 30  # seconds
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._start_time = datetime.now()
        
    async def start(self) -> None:
        """Start the agent and begin heartbeat."""
        if self.event_bus:
            await self._emit_event(EventType.AGENT_STARTED, {
                "agent_name": self.name,
                "state": self.state.value,
                "capabilities": getattr(self, 'capabilities', []),
                "start_time": self._start_time.isoformat()
            })
        
        # Start heartbeat task
        if not self._heartbeat_task or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        self.state = AgentState.IDLE
        logger.info(f"Agent {self.name} started")
    
    async def stop(self) -> None:
        """Stop the agent and cleanup."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        
        if self.event_bus:
            await self._emit_event(EventType.AGENT_COMPLETED, {
                "agent_name": self.name,
                "final_state": self.state.value,
                "total_tasks": self.metrics.tasks_completed + self.metrics.tasks_failed,
                "total_tokens": self.metrics.total_tokens,
                "uptime_seconds": (datetime.now() - self._start_time).seconds,
                "final_metrics": self.metrics.__dict__
            })
        
        self.state = AgentState.OFFLINE
        logger.info(f"Agent {self.name} stopped")
    
    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Enhanced run method with event emission."""
        task_id = f"task-{int(time.time())}-{self.name}"
        self.current_task_id = task_id
        start_time = time.time()
        
        try:
            # Emit task started event
            await self._emit_event(EventType.TASK_STARTED, {
                "task_id": task_id,
                "agent_name": self.name,
                "session_id": request.session_id,
                "query": request.query[:200],  # Truncate for space
                "start_time": datetime.now().isoformat()
            })
            
            # Update agent state
            self.state = AgentState.BUSY
            
            # Emit thinking event
            await self._emit_event(EventType.AGENT_HEARTBEAT, {
                "agent_name": self.name,
                "state": AgentState.THINKING.value,
                "task_id": task_id,
                "message": "Starting task processing"
            })
            
            # Process tokens and count them
            tokens = 0
            async for token in self._process_request_with_events(request):
                tokens += len(token)
                yield token
            
            # Update metrics
            processing_time = time.time() - start_time
            self.metrics.update_task_completed(processing_time, tokens)
            
            # Emit task completed event
            await self._emit_event(EventType.TASK_COMPLETED, {
                "task_id": task_id,
                "agent_name": self.name,
                "session_id": request.session_id,
                "processing_time": processing_time,
                "tokens_generated": tokens,
                "completion_time": datetime.now().isoformat(),
                "metrics": {
                    "tasks_completed": self.metrics.tasks_completed,
                    "average_response_time": self.metrics.average_response_time,
                    "error_rate": self.metrics.error_rate
                }
            })
            
            self.state = AgentState.COMPLETED
            
        except Exception as e:
            # Update error metrics
            self.metrics.update_task_failed()
            
            # Emit error event
            await self._emit_event(EventType.TASK_FAILED, {
                "task_id": task_id,
                "agent_name": self.name,
                "session_id": request.session_id,
                "error": str(e),
                "error_type": type(e).__name__,
                "processing_time": time.time() - start_time,
                "failure_time": datetime.now().isoformat(),
                "metrics": {
                    "tasks_failed": self.metrics.tasks_failed,
                    "error_rate": self.metrics.error_rate
                }
            })
            
            self.state = AgentState.ERROR
            logger.error(f"Agent {self.name} failed task {task_id}: {e}")
            raise
        finally:
            self.current_task_id = None
            if self.state != AgentState.ERROR:
                self.state = AgentState.IDLE
    
    async def _process_request_with_events(self, request: AgentRequest) -> AsyncIterator[str]:
        """Process request with intermediate events."""
        # This method should be overridden by subclasses
        # For now, just yield a simple response
        yield f"Response from {self.name} for: {request.query}"
    
    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeat events."""
        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                
                # Update uptime
                self.metrics.uptime = (datetime.now() - self._start_time).seconds
                self.metrics.last_heartbeat = datetime.now()
                
                # Emit heartbeat event
                await self._emit_event(EventType.AGENT_HEARTBEAT, {
                    "agent_name": self.name,
                    "state": self.state.value,
                    "current_task_id": self.current_task_id,
                    "metrics": {
                        "tasks_completed": self.metrics.tasks_completed,
                        "tasks_failed": self.metrics.tasks_failed,
                        "total_tokens": self.metrics.total_tokens,
                        "average_response_time": self.metrics.average_response_time,
                        "error_rate": self.metrics.error_rate,
                        "uptime_seconds": self.metrics.uptime,
                        "cpu_usage": self.metrics.cpu_usage,
                        "memory_usage": self.metrics.memory_usage
                    },
                    "heartbeat_time": datetime.now().isoformat()
                }, priority=EventPriority.LOW)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error for {self.name}: {e}")
                await asyncio.sleep(5)  # Wait before retrying
    
    async def _emit_event(self, event_type: EventType, payload: Dict[str, Any], 
                         priority: EventPriority = EventPriority.NORMAL) -> None:
        """Emit an event to the event bus."""
        if not self.event_bus:
            return
        
        try:
            event = Event(
                event_type=event_type,
                source=f"agent:{self.name}",
                agent=self.name,
                priority=priority,
                payload=payload,
                metadata={
                    "agent_state": self.state.value,
                    "agent_type": self.__class__.__name__,
                    "task_id": self.current_task_id
                }
            )
            
            await self.event_bus.publish(event)
            
        except Exception as e:
            logger.error(f"Failed to emit event {event_type.value} for {self.name}: {e}")
    
    async def emit_thinking_event(self, message: str) -> None:
        """Emit a thinking event."""
        await self._emit_event(EventType.AGENT_HEARTBEAT, {
            "agent_name": self.name,
            "state": AgentState.THINKING.value,
            "message": message,
            "thinking_time": datetime.now().isoformat()
        })
    
    async def emit_processing_event(self, message: str) -> None:
        """Emit a processing event."""
        await self._emit_event(EventType.AGENT_HEARTBEAT, {
            "agent_name": self.name,
            "state": AgentState.PROCESSING.value,
            "message": message,
            "processing_time": datetime.now().isoformat()
        })
    
    async def emit_metric_event(self, metric_name: str, value: float, unit: str = "") -> None:
        """Emit a metric update event."""
        await self._emit_event(EventType.METRIC_UPDATE, {
            "agent_name": self.name,
            "metric_name": metric_name,
            "value": value,
            "unit": unit,
            "timestamp": datetime.now().isoformat()
        })
    
    async def emit_system_event(self, message: str, level: str = "info") -> None:
        """Emit a system event."""
        event_type = EventType.SYSTEM_INFO
        if level == "warning":
            event_type = EventType.SYSTEM_WARNING
        elif level == "error":
            event_type = EventType.SYSTEM_ERROR
        
        await self._emit_event(event_type, {
            "agent_name": self.name,
            "message": message,
            "level": level,
            "timestamp": datetime.now().isoformat()
        })
    
    def get_current_metrics(self) -> Dict[str, Any]:
        """Get current agent metrics."""
        return {
            "agent_name": self.name,
            "state": self.state.value,
            "current_task_id": self.current_task_id,
            "is_busy": self.state in [AgentState.BUSY, AgentState.THINKING, AgentState.PROCESSING],
            "uptime_seconds": self.metrics.uptime,
            "tasks_completed": self.metrics.tasks_completed,
            "tasks_failed": self.metrics.tasks_failed,
            "total_tokens": self.metrics.total_tokens,
            "average_response_time": self.metrics.average_response_time,
            "error_rate": self.metrics.error_rate,
            "cpu_usage": self.metrics.cpu_usage,
            "memory_usage": self.metrics.memory_usage,
            "last_heartbeat": self.metrics.last_heartbeat.isoformat()
        }


class EventEmittingCoderAgent(EventEmittingAgent):
    """Event-emitting coder agent."""
    
    def __init__(self, event_bus: Optional[EventBus] = None):
        super().__init__("CODER", event_bus)
        self.capabilities = ["code_generation", "debugging", "refactoring"]
    
    async def _process_request_with_events(self, request: AgentRequest) -> AsyncIterator[str]:
        """Process coding request with events."""
        await self.emit_thinking_event("Analyzing coding request...")
        
        # Simulate thinking
        await asyncio.sleep(0.5)
        
        await self.emit_processing_event("Generating code...")
        
        # Simulate code generation
        code = f"def solution():\n    # Generated code for: {request.query}\n    return 'solution'"
        
        # Emit tokens
        for token in code.split():
            await self.emit_metric_event("tokens_generated", len(token), "characters")
            yield token + " "
            await asyncio.sleep(0.1)
        
        await self.emit_processing_event("Code generation completed")


class EventEmittingArchitectAgent(EventEmittingAgent):
    """Event-emitting architect agent."""
    
    def __init__(self, event_bus: Optional[EventBus] = None):
        super().__init__("ARCHITECT", event_bus)
        self.capabilities = ["architecture", "design", "planning"]
    
    async def _process_request_with_events(self, request: AgentRequest) -> AsyncIterator[str]:
        """Process architecture request with events."""
        await self.emit_thinking_event("Analyzing architectural requirements...")
        
        # Simulate thinking
        await asyncio.sleep(0.3)
        
        await self.emit_processing_event("Designing architecture...")
        
        # Simulate architecture design
        response = f"Architecture designed for: {request.query}\n\nComponents:\n- Frontend\n- Backend\n- Database\n- API"
        
        # Emit tokens
        for token in response.split():
            await self.emit_metric_event("tokens_generated", len(token), "characters")
            yield token + " "
            await asyncio.sleep(0.15)
        
        await self.emit_processing_event("Architecture design completed")


class EventEmittingDebuggerAgent(EventEmittingAgent):
    """Event-emitting debugger agent."""
    
    def __init__(self, event_bus: Optional[EventBus] = None):
        super().__init__("DEBUGGER", event_bus)
        self.capabilities = ["debugging", "error_analysis", "troubleshooting"]
    
    async def _process_request_with_events(self, request: AgentRequest) -> AsyncIterator[str]:
        """Process debugging request with events."""
        await self.emit_thinking_event("Analyzing debug request...")
        
        # Simulate thinking
        await asyncio.sleep(0.4)
        
        await self.emit_processing_event("Analyzing code for issues...")
        
        # Simulate debugging
        response = f"Debug analysis for: {request.query}\n\nIssues found:\n- Potential null reference\n- Missing error handling\n- Optimization opportunity"
        
        # Emit tokens
        for token in response.split():
            await self.emit_metric_event("tokens_generated", len(token), "characters")
            yield token + " "
            await asyncio.sleep(0.12)
        
        await self.emit_processing_event("Debug analysis completed")