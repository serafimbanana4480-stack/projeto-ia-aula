"""Meta-Learning System - Adaptive AI with feedback-driven improvement.

Collects implicit and explicit feedback to continuously improve routing,
model selection, and response quality over time.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from backend.config.settings import get_model_config
from backend.orchestrator.events import EventBus, EventType, OrchestratorEvent
from backend.tools.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class FeedbackType(str, Enum):
    EXPLICIT_RATING = "explicit_rating"      # User ratings 1-5
    IMPLICIT_TIME = "implicit_time"          # Time spent on response
    IMPLICIT_EDIT = "implicit_edit"          # User edited the response
    IMPLICIT_FOLLOWUP = "implicit_followup"  # User asked follow-up
    IMPLICIT_COPY = "implicit_copy"          # User copied response
    ERROR_REPORT = "error_report"            # User reported error


@dataclass
class FeedbackEvent:
    """A single feedback event."""
    session_id: str
    query: str
    model_key: str
    response: str
    feedback_type: FeedbackType
    value: float  # Rating, time in seconds, or binary indicator
    timestamp: float
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelPerformance:
    """Performance metrics for a specific model."""
    model_key: str
    total_requests: int = 0
    successful_requests: int = 0
    avg_response_time_ms: float = 0.0
    avg_rating: float = 0.0
    error_rate: float = 0.0
    user_satisfaction: float = 0.0
    last_updated: float = field(default_factory=time.time)


@dataclass
class RoutingDecision:
    """A routing decision with outcomes."""
    query_hash: str
    query_type: str
    chosen_model: str
    alternative_models: list[str]
    success_score: float
    response_time_ms: float
    user_feedback: float
    timestamp: float


class MetaLearner:
    """Meta-learning system for continuous AI improvement.
    
    Features:
    - Implicit feedback collection
    - Model performance tracking
    - Adaptive routing optimization
    - Quality trend analysis
    - Personalization learning
    """
    
    def __init__(
        self,
        ollama_client: OllamaClient,
        *,
        event_bus: EventBus | None = None,
        feedback_history_size: int = 10000,
        performance_window_hours: float = 24.0,
        min_feedback_for_learning: int = 50,
        learning_rate: float = 0.1,
        exploration_rate: float = 0.1,
    ) -> None:
        self.ollama = ollama_client
        self.event_bus = event_bus
        self.feedback_history_size = feedback_history_size
        self.performance_window_hours = performance_window_hours
        self.min_feedback_for_learning = min_feedback_for_learning
        self.learning_rate = learning_rate
        self.exploration_rate = exploration_rate
        
        # Feedback storage
        self._feedback_history: deque = deque(maxlen=feedback_history_size)
        self._model_performance: dict[str, ModelPerformance] = {}
        self._routing_decisions: list[RoutingDecision] = []
        
        # Learning models
        self._model_preferences: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self._query_patterns: dict[str, list[str]] = defaultdict(list)
        self._user_profiles: dict[str, dict[str, Any]] = defaultdict(dict)
        
        # Background tasks
        self._learning_task: asyncio.Task | None = None
        self._running = False
        self._initialized = False
        
        # Lock for thread safety
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """Initialize the MetaLearner and register with EventBus."""
        if self._initialized:
            return
        self._initialized = True

        # Subscribe to ERROR events on the event bus
        if self.event_bus:
            await self.event_bus.subscribe(EventType.ERROR.value, self._on_error_event)
            logger.info("MetaLearner subscribed to ERROR events")

        await self.start()
        logger.info("MetaLearner initialized")

    async def start(self) -> None:
        """Start the meta-learning system."""
        if self._running:
            return
        
        self._running = True
        self._learning_task = asyncio.create_task(self._learning_loop())
        
        # Initialize model performance tracking
        await self._initialize_model_performance()
        
        logger.info("Meta-Learning system started")
    
    async def stop(self) -> None:
        """Stop the meta-learning system."""
        self._running = False
        if self._learning_task:
            self._learning_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._learning_task
        logger.info("Meta-Learning system stopped")
    
    async def record_feedback(
        self,
        session_id: str,
        query: str,
        model_key: str,
        response: str,
        feedback_type: FeedbackType,
        value: float,
        context: dict[str, Any] | None = None
    ) -> None:
        """Record a feedback event."""
        async with self._lock:
            event = FeedbackEvent(
                session_id=session_id,
                query=query,
                model_key=model_key,
                response=response,
                feedback_type=feedback_type,
                value=value,
                timestamp=time.time(),
                context=context or {}
            )
            
            self._feedback_history.append(event)
            
            # Update model performance
            await self._update_model_performance(event)
            
            # Update user profile
            await self._update_user_profile(event)
            
            logger.debug(
                "Recorded %s feedback for model %s (value: %.2f)",
                feedback_type.value, model_key, value
            )
    
    async def record_routing_decision(
        self,
        query_hash: str,
        query_type: str,
        chosen_model: str,
        alternative_models: list[str],
        response_time_ms: float,
        success_score: float = 1.0
    ) -> None:
        """Record a routing decision for learning."""
        async with self._lock:
            decision = RoutingDecision(
                query_hash=query_hash,
                query_type=query_type,
                chosen_model=chosen_model,
                alternative_models=alternative_models,
                success_score=success_score,
                response_time_ms=response_time_ms,
                user_feedback=0.0,  # Will be updated when feedback arrives
                timestamp=time.time()
            )
            
            self._routing_decisions.append(decision)
            
            # Keep only recent decisions
            if len(self._routing_decisions) > 1000:
                self._routing_decisions = self._routing_decisions[-1000:]
    
    async def get_model_recommendation(
        self,
        query: str,
        query_type: str,
        available_models: list[str],
        session_id: str | None = None
    ) -> tuple[str, float]:
        """Get the best model recommendation based on learning."""
        async with self._lock:
            if not available_models:
                return "", 0.0
            
            # Exploration vs exploitation
            if asyncio.current_task().get_name() == "exploration" or self._should_explore():
                # Explore: try a different model
                model = await self._explore_model(available_models, query_type)
                confidence = 0.5  # Lower confidence for exploration
            else:
                # Exploit: use learned preferences
                model, confidence = await self._exploit_best_model(
                    query, query_type, available_models, session_id
                )
            
            return model, confidence
    
    async def get_model_insights(self, model_key: str) -> dict[str, Any]:
        """Get detailed insights about a model's performance."""
        async with self._lock:
            if model_key not in self._model_performance:
                return {}
            
            perf = self._model_performance[model_key]
            
            # Calculate trends
            recent_feedback = [
                f for f in self._feedback_history
                if f.model_key == model_key and
                (time.time() - f.timestamp) < (self.performance_window_hours * 3600)
            ]
            
            insights = {
                "model_key": model_key,
                "performance": {
                    "total_requests": perf.total_requests,
                    "success_rate": perf.successful_requests / max(1, perf.total_requests),
                    "avg_response_time_ms": perf.avg_response_time_ms,
                    "avg_rating": perf.avg_rating,
                    "error_rate": perf.error_rate,
                    "user_satisfaction": perf.user_satisfaction,
                },
                "recent_feedback": len(recent_feedback),
                "trends": await self._calculate_trends(model_key, recent_feedback),
                "strengths": await self._identify_strengths(model_key),
                "weaknesses": await self._identify_weaknesses(model_key),
                "recommended_for": await self._get_recommended_use_cases(model_key),
            }
            
            return insights
    
    async def get_learning_stats(self) -> dict[str, Any]:
        """Get meta-learning statistics."""
        async with self._lock:
            return {
                "total_feedback_events": len(self._feedback_history),
                "models_tracked": len(self._model_performance),
                "routing_decisions": len(self._routing_decisions),
                "user_profiles": len(self._user_profiles),
                "learning_rate": self.learning_rate,
                "exploration_rate": self.exploration_rate,
                "feedback_types": {
                    ft.value: sum(1 for f in self._feedback_history if f.feedback_type == ft)
                    for ft in FeedbackType
                },
                "model_performance": {
                    key: {
                        "requests": perf.total_requests,
                        "success_rate": perf.successful_requests / max(1, perf.total_requests),
                        "avg_rating": perf.avg_rating,
                    }
                    for key, perf in self._model_performance.items()
                }
            }
    
    async def _initialize_model_performance(self) -> None:
        """Initialize performance tracking for all models."""
        model_configs = get_model_config()
        
        for model_key in model_configs:
            if isinstance(model_configs[model_key], dict):
                self._model_performance[model_key] = ModelPerformance(
                    model_key=model_key
                )
    
    async def _update_model_performance(self, event: FeedbackEvent) -> None:
        """Update model performance metrics based on feedback."""
        if event.model_key not in self._model_performance:
            self._model_performance[event.model_key] = ModelPerformance(
                model_key=event.model_key
            )
        
        perf = self._model_performance[event.model_key]
        perf.total_requests += 1
        perf.last_updated = time.time()
        
        # Update metrics based on feedback type
        if event.feedback_type == FeedbackType.EXPLICIT_RATING:
            # Update average rating
            perf.avg_rating = (
                (perf.avg_rating * (perf.total_requests - 1) + event.value) /
                perf.total_requests
            )
            perf.successful_requests += 1 if event.value >= 3 else 0
            
        elif event.feedback_type == FeedbackType.IMPLICIT_TIME:
            # Update response time (if provided in context)
            if "response_time_ms" in event.context:
                response_time = event.context["response_time_ms"]
                perf.avg_response_time_ms = (
                    (perf.avg_response_time_ms * (perf.total_requests - 1) + response_time) /
                    perf.total_requests
                )
            
            # Longer time might indicate lower satisfaction
            satisfaction = max(0.0, 1.0 - (event.value / 60.0))  # Normalize by minute
            perf.user_satisfaction = (
                (perf.user_satisfaction * (perf.total_requests - 1) + satisfaction) /
                perf.total_requests
            )
            perf.successful_requests += 1 if event.value < 30 else 0  # 30s threshold
            
        elif event.feedback_type == FeedbackType.IMPLICIT_EDIT:
            # User edited indicates original wasn't perfect
            perf.user_satisfaction = (
                (perf.user_satisfaction * (perf.total_requests - 1) + 0.7) /
                perf.total_requests
            )
            
        elif event.feedback_type == FeedbackType.ERROR_REPORT:
            perf.error_rate += 1.0 / perf.total_requests
    
    async def _update_user_profile(self, event: FeedbackEvent) -> None:
        """Update user preferences and patterns."""
        user_id = event.session_id
        profile = self._user_profiles[user_id]
        
        # Update model preferences
        if "model_preferences" not in profile:
            profile["model_preferences"] = defaultdict(float)
        
        if event.feedback_type == FeedbackType.EXPLICIT_RATING:
            profile["model_preferences"][event.model_key] = (
                profile["model_preferences"][event.model_key] * 0.8 + event.value * 0.2
            )
        
        # Update query patterns
        if "query_patterns" not in profile:
            profile["query_patterns"] = defaultdict(int)
        
        # Simple pattern extraction (can be enhanced)
        words = event.query.lower().split()
        for word in words:
            if len(word) > 3:  # Skip short words
                profile["query_patterns"][word] += 1
    
    async def _should_explore(self) -> bool:
        """Decide whether to explore or exploit."""
        import random
        return random.random() < self.exploration_rate
    
    async def _explore_model(self, available_models: list[str], query_type: str) -> str:
        """Explore by selecting a less-used model."""
        import random
        
        # Prefer models with less usage for this query type
        model_scores = {}
        for model in available_models:
            # Lower usage = higher exploration score
            usage = len([
                d for d in self._routing_decisions
                if d.chosen_model == model and d.query_type == query_type
            ])
            model_scores[model] = 1.0 / (1.0 + usage)
        
        # Weighted random selection
        total_score = sum(model_scores.values())
        if total_score == 0:
            return random.choice(available_models)
        
        rand_val = random.random() * total_score
        cumulative = 0.0
        
        for model, score in model_scores.items():
            cumulative += score
            if rand_val <= cumulative:
                return model
        
        return available_models[0]
    
    async def _exploit_best_model(
        self,
        query: str,
        query_type: str,
        available_models: list[str],
        session_id: str | None = None
    ) -> tuple[str, float]:
        """Exploit by selecting the best known model."""
        best_model = ""
        best_score = -1.0
        
        for model in available_models:
            score = await self._calculate_model_score(
                model, query, query_type, session_id
            )
            
            if score > best_score:
                best_score = score
                best_model = model
        
        confidence = min(1.0, best_score / 5.0)  # Normalize to 0-1
        return best_model, confidence
    
    async def _calculate_model_score(
        self,
        model_key: str,
        query: str,
        query_type: str,
        session_id: str | None = None
    ) -> float:
        """Calculate a score for a model based on learned preferences."""
        if model_key not in self._model_performance:
            return 1.0  # Default score for unknown models
        
        perf = self._model_performance[model_key]
        
        # Base score from performance
        score = perf.avg_rating * perf.user_satisfaction
        
        # Boost for recent success
        recent_success = len([
            d for d in self._routing_decisions
            if d.chosen_model == model_key and
            d.success_score > 0.8 and
            (time.time() - d.timestamp) < (self.performance_window_hours * 3600)
        ])
        score += recent_success * 0.1
        
        # User personalization
        if session_id and session_id in self._user_profiles:
            user_pref = self._user_profiles[session_id].get("model_preferences", {})
            if model_key in user_pref:
                score += user_pref[model_key] * 0.2
        
        # Query type specialization
        type_success = len([
            d for d in self._routing_decisions
            if d.chosen_model == model_key and d.query_type == query_type and d.success_score > 0.8
        ])
        score += type_success * 0.15
        
        return score
    
    async def _calculate_trends(
        self,
        model_key: str,
        recent_feedback: list[FeedbackEvent]
    ) -> dict[str, float]:
        """Calculate performance trends for a model."""
        if len(recent_feedback) < 10:
            return {"trend": 0.0, "direction": "stable"}
        
        # Split into two halves and compare
        mid = len(recent_feedback) // 2
        old_feedback = recent_feedback[:mid]
        new_feedback = recent_feedback[mid:]
        
        old_avg = sum(f.value for f in old_feedback) / len(old_feedback)
        new_avg = sum(f.value for f in new_feedback) / len(new_feedback)
        
        trend = new_avg - old_avg
        
        if trend > 0.1:
            direction = "improving"
        elif trend < -0.1:
            direction = "declining"
        else:
            direction = "stable"
        
        return {"trend": trend, "direction": direction}
    
    async def _identify_strengths(self, model_key: str) -> list[str]:
        """Identify a model's strengths based on performance."""
        strengths = []
        perf = self._model_performance[model_key]
        
        if perf.avg_rating >= 4.0:
            strengths.append("high_quality_responses")
        if perf.avg_response_time_ms < 1000:
            strengths.append("fast_responses")
        if perf.error_rate < 0.05:
            strengths.append("reliable")
        if perf.user_satisfaction >= 0.8:
            strengths.append("user_satisfaction")
        
        return strengths
    
    async def _identify_weaknesses(self, model_key: str) -> list[str]:
        """Identify a model's weaknesses based on performance."""
        weaknesses = []
        perf = self._model_performance[model_key]
        
        if perf.avg_rating < 3.0:
            weaknesses.append("low_quality_responses")
        if perf.avg_response_time_ms > 3000:
            weaknesses.append("slow_responses")
        if perf.error_rate > 0.1:
            weaknesses.append("error_prone")
        if perf.user_satisfaction < 0.6:
            weaknesses.append("low_user_satisfaction")
        
        return weaknesses
    
    async def _get_recommended_use_cases(self, model_key: str) -> list[str]:
        """Get recommended use cases for a model based on performance."""
        use_cases = []
        
        # Analyze successful routing decisions
        successful_decisions = [
            d for d in self._routing_decisions
            if d.chosen_model == model_key and d.success_score > 0.8
        ]
        
        query_type_counts = defaultdict(int)
        for decision in successful_decisions:
            query_type_counts[decision.query_type] += 1
        
        # Get top query types
        if query_type_counts:
            total = sum(query_type_counts.values())
            for query_type, count in query_type_counts.items():
                if count / total > 0.3:  # More than 30% of successful cases
                    use_cases.append(query_type)
        
        return use_cases
    
    async def _on_error_event(self, event: OrchestratorEvent) -> None:
        """Handle ERROR events from the event bus."""
        async with self._lock:
            # Record error as implicit negative feedback
            session_id = event.session_id or "system"
            model_key = event.data.get("model_key", "unknown")
            query = event.data.get("query", "")
            response = event.data.get("response", "")

            await self.record_feedback(
                session_id=session_id,
                query=query,
                model_key=model_key,
                response=response,
                feedback_type=FeedbackType.ERROR_REPORT,
                value=0.0,
                context={"error_message": event.content, "event_data": event.data},
            )
            logger.debug("MetaLearner recorded error event: %s", event.content)

    async def _learning_loop(self) -> None:
        """Background learning loop."""
        while self._running:
            try:
                await self._perform_learning()
                await asyncio.sleep(3600)  # Learn every hour
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Learning loop error: %s", e)
                await asyncio.sleep(3600)
    
    async def _perform_learning(self) -> None:
        """Perform learning from accumulated feedback."""
        if len(self._feedback_history) < self.min_feedback_for_learning:
            return
        
        logger.info("Performing meta-learning with %d feedback events", len(self._feedback_history))
        
        # Update model preferences
        await self._update_model_preferences()
        
        # Adjust exploration rate
        await self._adjust_exploration_rate()
        
        # Clean old data
        await self._cleanup_old_data()
        
        logger.info("Meta-learning completed")
    
    async def _update_model_preferences(self) -> None:
        """Update model preferences based on feedback."""
        for model_key, perf in self._model_performance.items():
            # Update preferences based on performance
            preference_score = perf.avg_rating * perf.user_satisfaction * (1.0 - perf.error_rate)
            
            # Store in preferences (simplified - could be more sophisticated)
            self._model_preferences["global"][model_key] = preference_score
    
    async def _adjust_exploration_rate(self) -> None:
        """Dynamically adjust exploration rate."""
        # Reduce exploration as we learn more
        total_feedback = len(self._feedback_history)
        if total_feedback > 1000:
            self.exploration_rate = max(0.05, self.exploration_rate * 0.95)
    
    async def _cleanup_old_data(self) -> None:
        """Clean up old data to manage memory."""
        cutoff_time = time.time() - (self.performance_window_hours * 3600)
        
        # Clean old routing decisions
        self._routing_decisions = [
            d for d in self._routing_decisions if d.timestamp > cutoff_time
        ]
        
        # Clean old user profiles (keep only recent activity)
        recent_sessions = set(f.session_id for f in self._feedback_history if f.timestamp > cutoff_time)
        self._user_profiles = {
            k: v for k, v in self._user_profiles.items() if k in recent_sessions
        }


# Global meta-learner instance
_meta_learner: MetaLearner | None = None


async def get_meta_learner() -> MetaLearner:
    """Get the global meta-learner instance."""
    global _meta_learner
    if _meta_learner is None:
        from backend.config.settings import get_settings
        settings = get_settings()
        ollama = OllamaClient(settings.ollama_host)
        _meta_learner = MetaLearner(ollama)
        await _meta_learner.start()
    return _meta_learner
