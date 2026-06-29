"""Ensemble Reasoning System - Multi-agent consensus and conflict resolution.

Coordinates multiple agents to reach consensus on complex queries,
improving accuracy through diverse perspectives and voting mechanisms.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
from enum import Enum

from backend.agents.base import AgentBase, AgentRequest
from backend.tools.ollama_client import OllamaClient, ChatMessage
from backend.config.settings import get_model_config

logger = logging.getLogger(__name__)


class ConsensusMethod(str, Enum):
    """Methods for reaching consensus among agents."""
    MAJORITY_VOTE = "majority_vote"
    WEIGHTED_VOTE = "weighted_vote"
    BEST_RESPONSE = "best_response"
    SYNTHESIS = "synthesis"
    CONFLICT_RESOLUTION = "conflict_resolution"


@dataclass
class AgentResponse:
    """A response from an individual agent."""
    agent_name: str
    model_key: str
    response: str
    confidence: float
    reasoning: str
    execution_time_ms: float
    tokens_used: int
    error: Optional[str] = None


@dataclass
class EnsembleResult:
    """The result of ensemble reasoning."""
    final_response: str
    consensus_method: ConsensusMethod
    participating_agents: List[str]
    individual_responses: List[AgentResponse]
    consensus_score: float
    conflict_detected: bool
    synthesis_reasoning: str
    total_execution_time_ms: float
    total_tokens_used: int


@dataclass
class EnsembleConfig:
    """Configuration for ensemble reasoning."""
    max_agents: int = 5
    timeout_seconds: int = 60
    consensus_threshold: float = 0.7
    conflict_threshold: float = 0.3
    synthesis_model: str = "qwen2.5:7b"
    enable_voting: bool = True
    enable_synthesis: bool = True


class EnsembleReasoner:
    """Multi-agent ensemble reasoning system.
    
    Features:
    - Parallel agent execution
    - Multiple consensus methods
    - Conflict detection and resolution
    - Response synthesis
    - Performance tracking
    """
    
    def __init__(
        self,
        ollama_client: OllamaClient,
        agent_registry: Dict[str, AgentBase],
        config: Optional[EnsembleConfig] = None
    ) -> None:
        self.ollama = ollama_client
        self.agent_registry = agent_registry
        self.config = config or EnsembleConfig()
        
        # Performance tracking
        self._ensemble_history: List[EnsembleResult] = []
        self._agent_performance: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        
        # Lock for thread safety
        self._lock = asyncio.Lock()
    
    async def reason(
        self,
        query: str,
        session_id: str,
        agent_candidates: Optional[List[str]] = None,
        consensus_method: Optional[ConsensusMethod] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> EnsembleResult:
        """Perform ensemble reasoning on a complex query."""
        start_time = time.time()
        
        # Select agents for this query
        selected_agents = await self._select_agents(query, agent_candidates)
        
        if len(selected_agents) < 2:
            # Single agent fallback
            return await self._single_agent_fallback(query, session_id, selected_agents, context)
        
        # Execute agents in parallel
        individual_responses = await self._execute_agents_parallel(
            query, session_id, selected_agents, context
        )
        
        # Filter out failed responses
        valid_responses = [r for r in individual_responses if not r.error]
        
        if len(valid_responses) == 0:
            raise ValueError("All agents failed to respond")
        
        if len(valid_responses) == 1:
            # Only one valid response
            return self._create_result_from_single_response(valid_responses[0], start_time)
        
        # Detect conflicts
        conflict_detected = await self._detect_conflicts(valid_responses)
        
        # Choose consensus method
        method = consensus_method or await self._choose_consensus_method(
            valid_responses, conflict_detected
        )
        
        # Apply consensus method
        final_response, consensus_score, synthesis_reasoning = await self._apply_consensus_method(
            valid_responses, method, query, context
        )
        
        # Create result
        total_time = (time.time() - start_time) * 1000
        total_tokens = sum(r.tokens_used for r in valid_responses)
        
        result = EnsembleResult(
            final_response=final_response,
            consensus_method=method,
            participating_agents=[r.agent_name for r in valid_responses],
            individual_responses=valid_responses,
            consensus_score=consensus_score,
            conflict_detected=conflict_detected,
            synthesis_reasoning=synthesis_reasoning,
            total_execution_time_ms=total_time,
            total_tokens_used=total_tokens
        )
        
        # Update performance tracking
        await self._update_performance_tracking(result)
        
        return result
    
    async def get_agent_performance(self, agent_name: str) -> Dict[str, float]:
        """Get performance metrics for a specific agent."""
        async with self._lock:
            return dict(self._agent_performance.get(agent_name, {}))
    
    async def get_ensemble_stats(self) -> Dict[str, Any]:
        """Get ensemble reasoning statistics."""
        async with self._lock:
            if not self._ensemble_history:
                return {}
            
            recent_results = self._ensemble_history[-100:]  # Last 100 results
            
            stats = {
                "total_ensembles": len(self._ensemble_history),
                "recent_ensembles": len(recent_results),
                "avg_consensus_score": sum(r.consensus_score for r in recent_results) / len(recent_results),
                "conflict_rate": sum(1 for r in recent_results if r.conflict_detected) / len(recent_results),
                "avg_execution_time_ms": sum(r.total_execution_time_ms for r in recent_results) / len(recent_results),
                "avg_tokens_used": sum(r.total_tokens_used for r in recent_results) / len(recent_results),
                "consensus_methods": {
                    method.value: sum(1 for r in recent_results if r.consensus_method == method)
                    for method in ConsensusMethod
                },
                "agent_participation": await self._calculate_agent_participation(recent_results),
            }
            
            return stats
    
    async def _select_agents(
        self,
        query: str,
        agent_candidates: Optional[List[str]]
    ) -> List[str]:
        """Select the best agents for this query."""
        if agent_candidates:
            # Use provided candidates
            available = [name for name in agent_candidates if name in self.agent_registry]
        else:
            # Select based on query complexity and type
            available = await self._select_agents_by_query_type(query)
        
        # Limit to max_agents
        return available[:self.config.max_agents]
    
    async def _select_agents_by_query_type(self, query: str) -> List[str]:
        """Select agents based on query characteristics."""
        query_lower = query.lower()
        selected = []
        
        # Always include CODER for code-related queries
        if any(word in query_lower for word in ["code", "function", "implement", "debug"]):
            selected.append("CODER")
        
        # Include ANALYZER for analysis tasks
        if any(word in query_lower for word in ["analyze", "review", "evaluate", "compare"]):
            selected.append("ANALYZER")
        
        # Include ARCHITECT for design tasks
        if any(word in query_lower for word in ["design", "architecture", "plan", "structure"]):
            selected.append("ARCHITECT")
        
        # Include RESEARCHER for information queries
        if any(word in query_lower for word in ["research", "find", "search", "information"]):
            selected.append("RESEARCHER")
        
        # Default agents if none selected
        if not selected:
            selected = ["CODER", "ANALYZER", "ARCHITECT"]
        
        # Filter to available agents
        return [name for name in selected if name in self.agent_registry]
    
    async def _execute_agents_parallel(
        self,
        query: str,
        session_id: str,
        agent_names: List[str],
        context: Optional[Dict[str, Any]]
    ) -> List[AgentResponse]:
        """Execute multiple agents in parallel."""
        tasks = []
        
        for agent_name in agent_names:
            task = asyncio.create_task(
                self._execute_single_agent(agent_name, query, session_id, context)
            )
            tasks.append(task)
        
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            responses = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error("Agent %s failed: %s", agent_names[i], result)
                    responses.append(AgentResponse(
                        agent_name=agent_names[i],
                        model_key="",
                        response="",
                        confidence=0.0,
                        reasoning="",
                        execution_time_ms=0.0,
                        tokens_used=0,
                        error=str(result)
                    ))
                else:
                    responses.append(result)
            
            return responses
            
        except Exception as e:
            logger.error("Parallel execution failed: %s", e)
            raise
    
    async def _execute_single_agent(
        self,
        agent_name: str,
        query: str,
        session_id: str,
        context: Optional[Dict[str, Any]]
    ) -> AgentResponse:
        """Execute a single agent and capture its response."""
        if agent_name not in self.agent_registry:
            raise ValueError(f"Agent {agent_name} not found in registry")
        
        agent = self.agent_registry[agent_name]
        start_time = time.time()
        
        try:
            # Build agent request
            request = AgentRequest(
                session_id=session_id,
                query=query,
                client=self.ollama,
                context=context or {},
                max_iterations=3,  # Limit iterations for ensemble
                enable_thinking=True
            )
            
            # Execute agent
            response_parts = []
            thinking_parts = []
            
            async for token in agent.run(request):
                if token.startswith("<thinking>"):
                    thinking_parts.append(token)
                else:
                    response_parts.append(token)
            
            response = "".join(response_parts)
            thinking = "".join(thinking_parts)
            
            # Estimate confidence (simplified)
            confidence = await self._estimate_agent_confidence(agent_name, response, thinking)
            
            execution_time = (time.time() - start_time) * 1000
            tokens_used = len(response_parts)  # Rough estimate
            
            return AgentResponse(
                agent_name=agent_name,
                model_key=agent.model_key,
                response=response,
                confidence=confidence,
                reasoning=thinking,
                execution_time_ms=execution_time,
                tokens_used=tokens_used
            )
            
        except Exception as e:
            logger.error("Agent %s execution failed: %s", agent_name, e)
            return AgentResponse(
                agent_name=agent_name,
                model_key=agent.model_key,
                response="",
                confidence=0.0,
                reasoning="",
                execution_time_ms=(time.time() - start_time) * 1000,
                tokens_used=0,
                error=str(e)
            )
    
    async def _detect_conflicts(self, responses: List[AgentResponse]) -> bool:
        """Detect if there are significant conflicts between responses."""
        if len(responses) < 2:
            return False
        
        # Simple conflict detection based on response similarity
        # In a more sophisticated implementation, this could use semantic similarity
        conflicts = 0
        total_comparisons = 0
        
        for i in range(len(responses)):
            for j in range(i + 1, len(responses)):
                similarity = await self._calculate_response_similarity(
                    responses[i].response, responses[j].response
                )
                if similarity < self.config.conflict_threshold:
                    conflicts += 1
                total_comparisons += 1
        
        conflict_rate = conflicts / total_comparisons if total_comparisons > 0 else 0
        return conflict_rate > 0.5  # More than 50% conflicts
    
    async def _calculate_response_similarity(self, response1: str, response2: str) -> float:
        """Calculate similarity between two responses."""
        # Simple word overlap similarity (can be enhanced with embeddings)
        words1 = set(response1.lower().split())
        words2 = set(response2.lower().split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union) if union else 0.0
    
    async def _choose_consensus_method(
        self,
        responses: List[AgentResponse],
        conflict_detected: bool
    ) -> ConsensusMethod:
        """Choose the best consensus method based on responses."""
        if conflict_detected:
            return ConsensusMethod.CONFLICT_RESOLUTION
        
        if len(responses) == 2:
            return ConsensusMethod.SYNTHESIS
        
        # Check if one response has much higher confidence
        confidences = [r.confidence for r in responses]
        max_confidence = max(confidences)
        avg_confidence = sum(confidences) / len(confidences)
        
        if max_confidence > avg_confidence * 1.5:
            return ConsensusMethod.BEST_RESPONSE
        
        return ConsensusMethod.WEIGHTED_VOTE
    
    async def _apply_consensus_method(
        self,
        responses: List[AgentResponse],
        method: ConsensusMethod,
        original_query: str,
        context: Optional[Dict[str, Any]]
    ) -> Tuple[str, float, str]:
        """Apply the chosen consensus method."""
        if method == ConsensusMethod.MAJORITY_VOTE:
            return await self._majority_vote(responses)
        elif method == ConsensusMethod.WEIGHTED_VOTE:
            return await self._weighted_vote(responses)
        elif method == ConsensusMethod.BEST_RESPONSE:
            return await self._best_response(responses)
        elif method == ConsensusMethod.SYNTHESIS:
            return await self._synthesize_responses(responses, original_query, context)
        elif method == ConsensusMethod.CONFLICT_RESOLUTION:
            return await self._resolve_conflicts(responses, original_query, context)
        else:
            # Fallback to weighted vote
            return await self._weighted_vote(responses)
    
    async def _majority_vote(self, responses: List[AgentResponse]) -> Tuple[str, float, str]:
        """Simple majority vote among responses."""
        # For simplicity, choose the response with highest confidence
        best_response = max(responses, key=lambda r: r.confidence)
        consensus_score = best_response.confidence
        reasoning = f"Selected response from {best_response.agent_name} with highest confidence ({best_response.confidence:.2f})"
        
        return best_response.response, consensus_score, reasoning
    
    async def _weighted_vote(self, responses: List[AgentResponse]) -> Tuple[str, float, str]:
        """Weighted vote based on confidence and agent performance."""
        # Calculate weights based on confidence and historical performance
        weights = []
        for response in responses:
            base_weight = response.confidence
            performance_bonus = self._agent_performance.get(response.agent_name, {}).get("success_rate", 0.5)
            weight = base_weight * (1 + performance_bonus)
            weights.append(weight)
        
        # Choose response with highest weighted score
        best_idx = max(range(len(responses)), key=lambda i: weights[i])
        best_response = responses[best_idx]
        
        consensus_score = weights[best_idx] / sum(weights) if sum(weights) > 0 else 0.0
        reasoning = f"Selected response from {best_response.agent_name} with weighted score ({weights[best_idx]:.2f})"
        
        return best_response.response, consensus_score, reasoning
    
    async def _best_response(self, responses: List[AgentResponse]) -> Tuple[str, float, str]:
        """Select the single best response."""
        best_response = max(responses, key=lambda r: r.confidence)
        consensus_score = best_response.confidence
        reasoning = f"Selected best response from {best_response.agent_name} (confidence: {best_response.confidence:.2f})"
        
        return best_response.response, consensus_score, reasoning
    
    async def _synthesize_responses(
        self,
        responses: List[AgentResponse],
        original_query: str,
        context: Optional[Dict[str, Any]]
    ) -> Tuple[str, float, str]:
        """Synthesize multiple responses into a single response."""
        prompt = f"""Synthesize the following responses into a single, comprehensive answer to the original query.

Original Query: {original_query}

Responses from different agents:
"""
        
        for i, response in enumerate(responses):
            prompt += f"\nAgent {response.agent_name} (confidence: {response.confidence:.2f}):\n{response.response}\n"
        
        prompt += """
Please provide a synthesized response that:
1. Incorporates the best insights from all responses
2. Resolves any contradictions
3. Provides a clear, comprehensive answer
4. Maintains the original intent of the query

Synthesized response:"""
        
        try:
            synthesized = await self.ollama.chat_complete(
                model=self.config.synthesis_model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.3, "num_predict": 1000}
            )
            
            # Calculate consensus score based on agreement
            avg_confidence = sum(r.confidence for r in responses) / len(responses)
            consensus_score = min(1.0, avg_confidence * 1.2)  # Boost for synthesis
            
            reasoning = f"Synthesized {len(responses)} responses using {self.config.synthesis_model}"
            
            return synthesized, consensus_score, reasoning
            
        except Exception as e:
            logger.error("Synthesis failed: %s", e)
            # Fallback to best response
            return await self._best_response(responses)
    
    async def _resolve_conflicts(
        self,
        responses: List[AgentResponse],
        original_query: str,
        context: Optional[Dict[str, Any]]
    ) -> Tuple[str, float, str]:
        """Resolve conflicts between conflicting responses."""
        prompt = f"""The following agents provided conflicting responses to the same query. Please resolve the conflicts and provide the most accurate answer.

Original Query: {original_query}

Conflicting Responses:
"""
        
        for i, response in enumerate(responses):
            prompt += f"\nAgent {response.agent_name} (confidence: {response.confidence:.2f}):\n{response.response}\n"
        
        prompt += """
Please analyze the conflicts and provide:
1. An assessment of which response is most accurate
2. Reasons for your choice
3. A final, resolved answer

Conflict resolution:"""
        
        try:
            resolved = await self.ollama.chat_complete(
                model=self.config.synthesis_model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.2, "num_predict": 1000}
            )
            
            # Lower consensus score due to conflicts
            avg_confidence = sum(r.confidence for r in responses) / len(responses)
            consensus_score = avg_confidence * 0.8  # Penalty for conflict
            
            reasoning = f"Resolved conflicts between {len(responses)} conflicting responses"
            
            return resolved, consensus_score, reasoning
            
        except Exception as e:
            logger.error("Conflict resolution failed: %s", e)
            # Fallback to best response
            return await self._best_response(responses)
    
    async def _estimate_agent_confidence(self, agent_name: str, response: str, thinking: str) -> float:
        """Estimate confidence of an agent's response."""
        # Base confidence from historical performance
        base_confidence = self._agent_performance.get(agent_name, {}).get("success_rate", 0.7)
        
        # Adjust based on response characteristics
        response_length = len(response)
        if response_length < 50:
            base_confidence *= 0.8  # Penalty for very short responses
        elif response_length > 1000:
            base_confidence *= 0.9  # Slight penalty for very long responses
        
        # Boost if there's reasoning
        if thinking and len(thinking) > 100:
            base_confidence *= 1.1  # Boost for detailed reasoning
        
        return min(1.0, max(0.0, base_confidence))
    
    async def _single_agent_fallback(
        self,
        query: str,
        session_id: str,
        agents: List[str],
        context: Optional[Dict[str, Any]]
    ) -> EnsembleResult:
        """Fallback for single agent scenarios."""
        if not agents:
            raise ValueError("No agents available for fallback")
        
        agent_name = agents[0]
        response = await self._execute_single_agent(agent_name, query, session_id, context)
        
        return self._create_result_from_single_response(response, time.time())
    
    def _create_result_from_single_response(self, response: AgentResponse, start_time: float) -> EnsembleResult:
        """Create ensemble result from single response."""
        total_time = (time.time() - start_time) * 1000
        
        return EnsembleResult(
            final_response=response.response,
            consensus_method=ConsensusMethod.BEST_RESPONSE,
            participating_agents=[response.agent_name],
            individual_responses=[response],
            consensus_score=response.confidence,
            conflict_detected=False,
            synthesis_reasoning="Single agent execution",
            total_execution_time_ms=total_time,
            total_tokens_used=response.tokens_used
        )
    
    async def _update_performance_tracking(self, result: EnsembleResult) -> None:
        """Update performance tracking for agents."""
        async with self._lock:
            for response in result.individual_responses:
                perf = self._agent_performance[response.agent_name]
                
                # Update success rate
                if response.error:
                    perf["error_count"] = perf.get("error_count", 0) + 1
                else:
                    perf["success_count"] = perf.get("success_count", 0) + 1
                
                total = perf.get("success_count", 0) + perf.get("error_count", 0)
                perf["success_rate"] = perf.get("success_count", 0) / total if total > 0 else 0.0
                
                # Update average confidence
                current_avg = perf.get("avg_confidence", 0.0)
                count = perf.get("confidence_count", 0)
                perf["avg_confidence"] = (current_avg * count + response.confidence) / (count + 1)
                perf["confidence_count"] = count + 1
                
                # Update execution time
                current_avg_time = perf.get("avg_execution_time", 0.0)
                time_count = perf.get("execution_time_count", 0)
                perf["avg_execution_time"] = (current_avg_time * time_count + response.execution_time_ms) / (time_count + 1)
                perf["execution_time_count"] = time_count + 1
        
        # Store ensemble result
        self._ensemble_history.append(result)
        
        # Keep only recent history
        if len(self._ensemble_history) > 1000:
            self._ensemble_history = self._ensemble_history[-1000:]
    
    async def _calculate_agent_participation(self, results: List[EnsembleResult]) -> Dict[str, float]:
        """Calculate agent participation rates."""
        participation = defaultdict(int)
        total = len(results)
        
        for result in results:
            for agent_name in result.participating_agents:
                participation[agent_name] += 1
        
        return {agent: count / total for agent, count in participation.items()}


# Global ensemble reasoner instance
_ensemble_reasoner: Optional[EnsembleReasoner] = None


def get_ensemble_reasoner(
    ollama_client: OllamaClient,
    agent_registry: Dict[str, AgentBase],
    config: Optional[EnsembleConfig] = None
) -> EnsembleReasoner:
    """Get the global ensemble reasoner instance."""
    global _ensemble_reasoner
    if _ensemble_reasoner is None:
        _ensemble_reasoner = EnsembleReasoner(ollama_client, agent_registry, config)
    return _ensemble_reasoner
