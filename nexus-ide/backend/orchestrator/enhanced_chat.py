"""Enhanced Chat System - Real-time chat with dashboard integration.

This system provides:
- Real-time chat with event emission
- Dashboard integration
- Token tracking
- Session management
- Multi-modal support
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator, Dict, List, Optional, Any
from datetime import datetime

from backend.models.api import ChatRequest, RoutingDecision, StreamEvent
from backend.observability.event_system import EventBus, Event, EventType, EventPriority
from backend.orchestrator.fallback import invoke_with_fallback
from backend.orchestrator.registry import resolve
from backend.orchestrator.router import fast_route, route_with_model
from backend.agents.base import AgentRequest
from backend.tools.ollama_client import ChatMessage, OllamaError
from backend.tools.sanitizer import detect_injection
from backend.metrics.realtime_metrics import get_metrics_collector

logger = logging.getLogger(__name__)


class EnhancedChatSystem:
    """Enhanced chat system with real-time events and dashboard integration."""
    
    def __init__(self, event_bus: EventBus, context: Any | None = None):
        self.event_bus = event_bus
        self.context = context
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.session_metrics: Dict[str, Dict[str, Any]] = {}
        
    async def process_chat_request(self, req: ChatRequest, ollama, registry) -> AsyncIterator[str]:
        """Process chat request with enhanced event emission."""
        session_id = req.session_id
        start_time = time.time()
        
        # Initialize session if not exists
        if session_id not in self.active_sessions:
            self.active_sessions[session_id] = {
                "created_at": datetime.now().isoformat(),
                "message_count": 0,
                "total_tokens": 0,
                "last_activity": datetime.now().isoformat()
            }
            self.session_metrics[session_id] = {
                "requests": 0,
                "tokens": 0,
                "errors": 0,
                "avg_response_time": 0.0
            }
        
        # Update session activity
        self.active_sessions[session_id]["last_activity"] = datetime.now().isoformat()
        self.active_sessions[session_id]["message_count"] += 1
        self.session_metrics[session_id]["requests"] += 1
        
        # Emit chat message event
        await self._emit_chat_event(session_id, "message_received", {
            "message": req.message,
            "mode": req.mode,
            "message_length": len(req.message)
        })
        
        # Sanitize input
        injection = detect_injection(req.message)
        if injection.detected:
            logger.info(f"Blocked potential prompt injection: {injection.pattern}")
            await self._emit_chat_event(session_id, "message_blocked", {
                "reason": "prompt_injection",
                "pattern": injection.pattern
            })
            
            yield f"data: {json.dumps(StreamEvent(type='error', content=f'Request blocked: potential prompt injection ({injection.pattern}).').model_dump_json())}\n\n"
            yield f"data: {json.dumps(StreamEvent(type='done').model_dump_json())}\n\n"
            return
        
        # Route request
        mode = req.mode.lower()
        if mode == "plan":
            decision = RoutingDecision(
                primary_agent="ARCHITECT",
                routing_confidence=1.0,
                routing_reason="explicit-mode:plan",
                thinking_mode="deep",
                context_needed="high",
                task_type="planning",
            )
        elif mode == "debug":
            decision = RoutingDecision(
                primary_agent="DEBUGGER",
                routing_confidence=1.0,
                routing_reason="explicit-mode:debug",
                thinking_mode="iterative",
                context_needed="high",
                task_type="debugging",
            )
        elif mode == "ask":
            decision = RoutingDecision(
                primary_agent="MICRO",
                routing_confidence=1.0,
                routing_reason="explicit-mode:ask",
                thinking_mode="fast",
                context_needed="low",
                task_type="question",
            )
        else:
            decision = await self._decide_route(req.message, ollama)
        
        # Emit routing event
        await self._emit_chat_event(session_id, "routing_decision", {
            "primary_agent": decision.primary_agent,
            "confidence": decision.routing_confidence,
            "thinking_mode": decision.thinking_mode,
            "task_type": decision.task_type
        })
        
        # Emit routing event for dashboard
        yield f"data: {json.dumps(StreamEvent(type='routing', routing=decision.model_dump()).model_dump_json())}\n\n"
        
        # Get session history
        # Reuse the application-scoped store so this legacy enhanced route has
        # the same durable/reloadable history semantics as the main chat path.
        context = self.context
        if context is None:
            from backend.orchestrator.context_manager import ContextStore

            context = ContextStore()
        history = await context.get_history(session_id)

        project_memory = ""
        if req.project_path:
            try:
                from backend.knowledge.project_memory import read_project_memory

                project_memory = read_project_memory(req.project_path)
            except Exception:
                logger.debug("Enhanced chat project memory unavailable", exc_info=True)
        
        # Build agent request factory
        def make_invocation(agent_name: str):
            async def invoke() -> AsyncIterator[str]:
                agent = resolve(registry, agent_name)
                agent_req = AgentRequest(
                    session_id=session_id,
                    query=req.message,
                    client=ollama,
                    history=history,
                    project_path=req.project_path,
                    context={"_project_memory": project_memory} if project_memory else {},
                )
                return agent.run(agent_req)
            return invoke
        
        # Invoke with fallback
        try:
            outcome, token_stream = await invoke_with_fallback(
                decision.primary_agent,
                lambda name: make_invocation(name)(),
            )
        except OllamaError as exc:
            logger.exception(f"All fallbacks exhausted: {exc}")
            
            # Update error metrics
            self.session_metrics[session_id]["errors"] += 1
            
            await self._emit_chat_event(session_id, "processing_error", {
                "error": str(exc),
                "type": "ollama_error"
            })
            
            yield f"data: {json.dumps(StreamEvent(type='error', content=f'Upstream unavailable: {exc}').model_dump_json())}\n\n"
            yield f"data: {json.dumps(StreamEvent(type='done').model_dump_json())}\n\n"
            return
        
        # Emit agent started event
        await self._emit_chat_event(session_id, "agent_started", {
            "agent": outcome.used_agent,
            "primary_agent": decision.primary_agent
        })
        
        yield f"data: {json.dumps(StreamEvent(type='agent_started', agent=outcome.used_agent).model_dump_json())}\n\n"
        
        # Stream tokens and track metrics
        parts: List[str] = []
        token_count = 0
        
        try:
            async for token in token_stream:
                parts.append(token)
                token_count += len(token)
                
                # Emit token event periodically
                if token_count % 10 == 0:  # Emit every 10 tokens
                    await self._emit_chat_event(session_id, "token_stream", {
                        "token_count": token_count,
                        "agent": outcome.used_agent
                    })
                
                yield f"data: {json.dumps(StreamEvent(type='token', agent=outcome.used_agent, content=token).model_dump_json())}\n\n"
                
        except OllamaError as exc:
            logger.exception(f"Stream interrupted: {exc}")
            
            # Update error metrics
            self.session_metrics[session_id]["errors"] += 1
            
            await self._emit_chat_event(session_id, "stream_error", {
                "error": str(exc),
                "type": "stream_error",
                "tokens_processed": token_count
            })
            
            yield f"data: {json.dumps(StreamEvent(type='error', content=f'Stream interrupted: {exc}').model_dump_json())}\n\n"
            yield f"data: {json.dumps(StreamEvent(type='done').model_dump_json())}\n\n"
            return
        
        # Update session metrics
        processing_time = time.time() - start_time
        self.session_metrics[session_id]["tokens"] += token_count
        self.active_sessions[session_id]["total_tokens"] += token_count
        
        # Update average response time
        metrics = self.session_metrics[session_id]
        if metrics["requests"] > 0:
            total_time = metrics.get("total_response_time", 0) + processing_time
            metrics["total_response_time"] = total_time
            metrics["avg_response_time"] = total_time / metrics["requests"]
        
        # Persist exchange
        full = "".join(parts)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        await context.append_message(session_id, ChatMessage(role="user", content=req.message, timestamp=now))
        await context.append_message(session_id, ChatMessage(role="assistant", content=full, timestamp=now))
        
        # Update token metrics
        metrics_collector = await get_metrics_collector()
        await metrics_collector.token_collector.update_token_usage(
            input_tokens=len(req.message),
            output_tokens=token_count,
            model_name=outcome.used_agent
        )
        
        # Emit completion event
        await self._emit_chat_event(session_id, "message_completed", {
            "agent": outcome.used_agent,
            "processing_time": processing_time,
            "token_count": token_count,
            "response_length": len(full)
        })
        
        yield f"data: {json.dumps(StreamEvent(type='agent_finished', agent=outcome.used_agent).model_dump_json())}\n\n"
        yield f"data: {json.dumps(StreamEvent(type='done').model_dump_json())}\n\n"
    
    async def _emit_chat_event(self, session_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        """Emit chat-related event."""
        if not self.event_bus:
            return
        
        try:
            event = Event(
                event_type=EventType.CHAT_MESSAGE,
                source="chat_system",
                session_id=session_id,
                priority=EventPriority.NORMAL,
                payload={
                    "event_type": event_type,
                    **payload
                },
                metadata={
                    "component": "enhanced_chat",
                    "timestamp": datetime.now().isoformat()
                }
            )
            
            await self.event_bus.publish(event)
            
        except Exception as e:
            logger.error(f"Failed to emit chat event: {e}")
    
    async def _decide_route(self, query: str, ollama) -> RoutingDecision:
        """Enhanced routing decision with event emission."""
        fast = fast_route(query)
        if fast is not None:
            decision = RoutingDecision(
                primary_agent=fast,
                routing_confidence=0.9,
                routing_reason=f"fast-rule:{fast.lower()}",
            )
        else:
            decision = await route_with_model(query, ollama)
        
        return decision
    
    async def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session information."""
        if session_id not in self.active_sessions:
            return None
        
        return {
            **self.active_sessions[session_id],
            "metrics": self.session_metrics.get(session_id, {})
        }
    
    async def get_all_sessions(self) -> Dict[str, Dict[str, Any]]:
        """Get all active sessions."""
        result = {}
        for session_id, session_info in self.active_sessions.items():
            result[session_id] = {
                **session_info,
                "metrics": self.session_metrics.get(session_id, {})
            }
        return result
    
    async def cleanup_inactive_sessions(self, inactive_timeout: int = 3600) -> int:
        """Clean up inactive sessions."""
        current_time = datetime.now()
        inactive_sessions = []
        
        for session_id, session_info in self.active_sessions.items():
            last_activity = datetime.fromisoformat(session_info["last_activity"])
            if (current_time - last_activity).seconds > inactive_timeout:
                inactive_sessions.append(session_id)
        
        # Remove inactive sessions
        for session_id in inactive_sessions:
            del self.active_sessions[session_id]
            if session_id in self.session_metrics:
                del self.session_metrics[session_id]
            
            await self._emit_chat_event(session_id, "session_expired", {
                "reason": "inactive_timeout",
                "timeout_seconds": inactive_timeout
            })
        
        return len(inactive_sessions)
    
    async def get_system_stats(self) -> Dict[str, Any]:
        """Get chat system statistics."""
        total_sessions = len(self.active_sessions)
        total_messages = sum(s["message_count"] for s in self.active_sessions.values())
        total_tokens = sum(s["total_tokens"] for s in self.active_sessions.values())
        
        # Calculate average metrics
        avg_response_time = 0.0
        if self.session_metrics:
            all_response_times = [m.get("avg_response_time", 0) for m in self.session_metrics.values()]
            avg_response_time = sum(all_response_times) / len(all_response_times) if all_response_times else 0.0
        
        return {
            "active_sessions": total_sessions,
            "total_messages": total_messages,
            "total_tokens": total_tokens,
            "average_response_time": avg_response_time,
            "total_errors": sum(m.get("errors", 0) for m in self.session_metrics.values()),
            "sessions": await self.get_all_sessions()
        }


# Global chat system instance
_chat_system: Optional[EnhancedChatSystem] = None


async def get_chat_system(event_bus: EventBus, context: Any | None = None) -> EnhancedChatSystem:
    """Get the global chat system instance."""
    global _chat_system
    if _chat_system is None:
        _chat_system = EnhancedChatSystem(event_bus, context=context)
    return _chat_system
