"""Logical Judge for Enhanced Agent Parliament.

Uses a LARGE model to adjudicate decisions when consensus is not reached.
Analyzes arguments, voting patterns, and makes final decisions with reasoning.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from nexus_ide.backend.tools.ollama_client import OllamaClient
from nexus_ide.backend.config.settings import get_settings

from .voting_system import Vote, VoteResult, DecisionType
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from .cache import Cache
from .metrics import MetricsCollector, get_global_metrics_collector

logger = logging.getLogger(__name__)


class JudgeDecision(str, Enum):
    """Possible judge decisions."""
    CONSENSUS = "consensus"  # Accept consensus
    NEW_DECISION = "new_decision"  # Make new decision
    REQUEST_CLARIFICATION = "request_clarification"  # Ask for more info
    DEFER = "defer"  # Defer to human


@dataclass
class JudgeReasoning:
    """Reasoning from the logical judge."""
    decision: str
    reasoning: str
    confidence: float  # 0.0-1.0
    key_factors: List[str] = field(default_factory=list)
    alternative_considered: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "key_factors": self.key_factors,
            "alternative_considered": self.alternative_considered,
            "timestamp": self.timestamp,
        }


@dataclass
class ClarificationRequest:
    """Request for clarification from an agent."""
    agent_id: str
    question: str
    context: str
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "question": self.question,
            "context": self.context,
            "timestamp": self.timestamp,
        }


class LogicalJudge:
    """Logical judge for adjudicating agent debates.
    
    Uses a LARGE model (llama3:70b or qwen2.5:32b) to:
    - Analyze arguments from multiple agents
    - Consider weighted voting results
    - Make final decisions when consensus is not reached
    - Provide clear reasoning for decisions
    - Request clarifications when needed
    """
    
    def __init__(
        self,
        ollama_client: Optional[OllamaClient] = None,
        model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048
    ):
        """Initialize logical judge.
        
        Args:
            ollama_client: Ollama client for LLM calls
            model: Model to use for adjudication (default: llama3:70b)
            fallback_model: Fallback model if primary unavailable
            temperature: Temperature for generation (0.0-2.0)
            max_tokens: Maximum tokens to generate (must be positive)
        
        Raises:
            ValueError: If temperature or max_tokens are invalid
        """
        # Validate temperature
        if not 0.0 <= temperature <= 2.0:
            raise ValueError(
                f"temperature must be between 0.0 and 2.0, got {temperature}"
            )
        
        # Validate max_tokens
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            raise ValueError(
                f"max_tokens must be a positive integer, got {max_tokens}"
            )
        
        settings = get_settings()
        
        self.ollama = ollama_client or OllamaClient(settings.ollama_host)
        self.model = model or "llama3:70b"
        self.fallback_model = fallback_model or "llama3:8b"
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        # Circuit breaker for LLM calls
        circuit_config = CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout=60.0,
            expected_exception=(ConnectionError, TimeoutError),
            success_threshold=2
        )
        self.circuit_breaker = CircuitBreaker(circuit_config, name="logical_judge_llm")
        
        # Cache for LLM responses
        self.cache = Cache(default_ttl=600.0, max_size=100)  # 10 minutes, 100 entries
        
        # Metrics collector
        self.metrics_collector = get_global_metrics_collector()
        self.metrics_collector.register_component("logical_judge")
        
        # System prompt for the judge
        self.system_prompt = self._build_system_prompt()
        
        logger.info(
            f"LogicalJudge initialized with model={self.model}, "
            f"fallback={self.fallback_model}"
        )
    
    def _build_system_prompt(self) -> str:
        """Build system prompt for the logical judge."""
        return """You are a logical judge in a multi-agent AI debate system. Your role is to analyze arguments from specialized AI agents and make informed decisions when consensus cannot be reached.

## Your Responsibilities

1. **Analyze Arguments**: Carefully evaluate the arguments presented by each agent, considering:
   - Logical validity and coherence
   - Evidence and data provided
   - Alignment with project goals and constraints
   - Practical feasibility
   - Risk assessment and mitigation

2. **Consider Voting Patterns**: Take into account the weighted voting results, remembering that:
   - Different agents have different expertise weights
   - High-weight votes in specialized areas carry more significance
   - Unanimous or near-unanimous agreement should be respected

3. **Make Decisions**: When consensus is not clear, you must:
   - Choose the best option based on all available information
   - Provide clear, detailed reasoning for your decision
   - Assign a confidence score (0.0-1.0) to your decision
   - Identify key factors that influenced your decision

4. **Request Clarifications**: If information is insufficient, you may:
   - Ask specific agents for clarification
   - Request additional evidence or analysis
   - Suggest areas needing further investigation

## Response Format

Always respond in this exact format:

DECISION: [your decision - clear and specific]
REASONING: [detailed explanation of your reasoning, 2-5 paragraphs]
CONFIDENCE: [0.0-1.0]
KEY_FACTORS: [comma-separated list of key factors that influenced your decision]
ALTERNATIVE_CONSIDERED: [brief description of the main alternative you considered, or NONE]

## Decision Guidelines

- Prefer decisions that balance multiple factors (quality, feasibility, risk)
- Value evidence and data over opinion
- Consider long-term implications
- When in doubt, choose the more conservative option
- If uncertainty is very high, consider deferring to human judgment

## Example

DECISION: Use microservices architecture for the new system
REASONING: The ARCHITECT agent presented compelling arguments for microservices, citing scalability benefits and team autonomy. The RESEARCHER supported this with evidence from similar successful projects. While the CODER raised valid concerns about complexity, the weighted voting (2.0 for ARCHITECT, 1.2 for RESEARCHER, 1.0 for CODER) favors microservices. The long-term scalability benefits outweigh the initial complexity costs, especially given our projected growth.
CONFIDENCE: 0.85
KEY_FACTORS: scalability, team autonomy, evidence from similar projects, weighted voting pattern, long-term growth
ALTERNATIVE_CONSIDERED: Monolithic architecture with modular design

Remember: Your decisions will be implemented and their outcomes tracked for learning. Be thoughtful and thorough."""
    
    async def adjudicate(
        self,
        topic: str,
        arguments: List[str],
        votes: List[Vote],
        vote_result: VoteResult,
        decision_type: DecisionType = DecisionType.DEFAULT
    ) -> JudgeReasoning:
        """Adjudicate a debate when consensus is not reached.
        
        Args:
            topic: Topic of the debate
            arguments: List of arguments from agents
            votes: List of votes from agents
            vote_result: Result of weighted voting
            decision_type: Type of decision being made
            
        Returns:
            JudgeReasoning with decision and reasoning
        """
        # Build prompt for the judge
        prompt = self._build_adjudication_prompt(
            topic,
            arguments,
            votes,
            vote_result,
            decision_type
        )
        
        # Get decision from LLM with circuit breaker and retry logic
        max_retries = 2
        last_error = None

        for attempt in range(max_retries):
            try:
                response = await self.circuit_breaker.call(
                    self._get_llm_decision, prompt
                )
                reasoning = self._parse_judge_response(response)
                break  # Success, exit retry loop
            except Exception as e:
                # Circuit breaker may raise CircuitOpenError or the original exception
                from .circuit_breaker import CircuitOpenError
                
                if isinstance(e, CircuitOpenError):
                    logger.warning(f"Circuit breaker is open: {e}")
                    # Use fallback immediately if circuit is open
                    reasoning = self._create_fallback_reasoning(
                        topic,
                        vote_result,
                        decision_type
                    )
                    return reasoning
                
                last_error = e
                logger.warning(
                    f"Error on attempt {attempt + 1}/{max_retries}: {e}"
                )
                if attempt < max_retries - 1:
                    continue  # Retry
        else:
            # All retries exhausted, use fallback
            logger.error(
                f"Failed to get decision from LLM after {max_retries} attempts. "
                f"Last error: {last_error}. Using fallback reasoning."
            )
            reasoning = self._create_fallback_reasoning(
                topic,
                vote_result,
                decision_type
            )
        
        logger.info(
            f"Judge adjudication: decision={reasoning.decision}, "
            f"confidence={reasoning.confidence:.2f}"
        )
        
        return reasoning
    
    def _build_adjudication_prompt(
        self,
        topic: str,
        arguments: List[str],
        votes: List[Vote],
        vote_result: VoteResult,
        decision_type: DecisionType
    ) -> str:
        """Build prompt for adjudication."""
        prompt_parts = [
            f"# Debate Topic\n{topic}\n",
            f"# Decision Type\n{decision_type.value}\n",
        ]
        
        # Add arguments
        if arguments:
            prompt_parts.append("# Agent Arguments\n")
            for i, arg in enumerate(arguments, 1):
                prompt_parts.append(f"## Agent {i}\n{arg}\n")
        
        # Add votes
        if votes:
            prompt_parts.append("# Agent Votes\n")
            for vote in votes:
                weight = vote_result.vote_breakdown.get(vote.agent_id, 0)
                prompt_parts.append(
                    f"- {vote.agent_id}: {vote.value}/10 "
                    f"(weighted: {weight:.2f}) - {vote.reasoning}\n"
                )
        
        # Add voting result
        prompt_parts.append("\n# Voting Result\n")
        prompt_parts.append(
            f"Weighted Average: {vote_result.weighted_average:.2f}\n"
            f"Consensus Reached: {vote_result.consensus_reached}\n"
            f"Total Weight: {vote_result.total_weight:.2f}\n"
        )
        
        # Add instruction
        prompt_parts.append(
            "\n# Your Task\n"
            "Based on the arguments, votes, and voting result above, "
            "make a decision and provide your reasoning using the format specified in your system prompt.\n"
        )
        
        return "\n".join(prompt_parts)
    
    async def _get_llm_decision(self, prompt: str) -> str:
        """Get decision from LLM with caching."""
        # Check cache first
        cache_key = self.cache._generate_key(self.model, self.temperature, self.max_tokens, prompt)
        cached_response = self.cache.get(cache_key)
        
        if cached_response is not None:
            logger.debug("LLM response retrieved from cache")
            return cached_response
        
        # Not in cache, make LLM call
        try:
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ]
            
            response = ""
            async for chunk in self.ollama.chat_stream(
                model=self.model,
                messages=messages,
                options={
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                }
            ):
                response += chunk
            
            # Cache the response
            self.cache.set(cache_key, response, ttl=600.0)  # 10 minutes
            
            return response
        except Exception as e:
            logger.warning(f"Failed to use primary model {self.model}: {e}")
            # Try fallback model
            try:
                response = ""
                async for chunk in self.ollama.chat_stream(
                    model=self.fallback_model,
                    messages=messages,
                    options={
                        "temperature": self.temperature,
                        "num_predict": self.max_tokens,
                    }
                ):
                    response += chunk
                
                logger.info(f"Used fallback model {self.fallback_model}")
                return response
            except Exception as e2:
                logger.error(f"Failed to use fallback model: {e2}")
                raise
    
    def _parse_judge_response(self, response: str) -> JudgeReasoning:
        """Parse judge's response into structured format."""
        decision = ""
        reasoning = ""
        confidence = 0.5
        key_factors = []
        alternative = None
        
        # Parse response
        lines = response.strip().split('\n')
        current_section = None
        
        for line in lines:
            line = line.strip()
            
            if line.startswith("DECISION:"):
                decision = line.replace("DECISION:", "").strip()
                current_section = None
            elif line.startswith("REASONING:"):
                reasoning = line.replace("REASONING:", "").strip()
                current_section = "reasoning"
            elif line.startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.replace("CONFIDENCE:", "").strip())
                except ValueError:
                    confidence = 0.5
                current_section = None
            elif line.startswith("KEY_FACTORS:"):
                factors_str = line.replace("KEY_FACTORS:", "").strip()
                key_factors = [f.strip() for f in factors_str.split(',')]
                current_section = None
            elif line.startswith("ALTERNATIVE_CONSIDERED:"):
                alt = line.replace("ALTERNATIVE_CONSIDERED:", "").strip()
                alternative = alt if alt.upper() != "NONE" else None
                current_section = None
            elif current_section == "reasoning":
                reasoning += " " + line
        
        # Fallback if parsing failed
        if not decision:
            decision = response.split('\n')[0] if response else "No decision"
        if not reasoning:
            reasoning = response
        
        return JudgeReasoning(
            decision=decision,
            reasoning=reasoning.strip(),
            confidence=confidence,
            key_factors=key_factors,
            alternative_considered=alternative,
        )
    
    def _create_fallback_reasoning(
        self,
        topic: str,
        vote_result: VoteResult,
        decision_type: DecisionType
    ) -> JudgeReasoning:
        """Create fallback reasoning when LLM fails."""
        # Use the winning option from voting
        decision = vote_result.winning_option or f"Option with score {vote_result.weighted_average:.2f}"
        
        reasoning = (
            f"Based on the weighted voting result (average: {vote_result.weighted_average:.2f}), "
            f"the decision is {decision}. "
            f"This decision reflects the collective judgment of the specialized agents, "
            f"with their votes weighted according to their expertise in {decision_type.value}."
        )
        
        return JudgeReasoning(
            decision=decision,
            reasoning=reasoning,
            confidence=0.7,  # Moderate confidence for fallback
            key_factors=["weighted voting result", "agent expertise"],
            alternative_considered=None,
        )
    
    async def request_clarification(
        self,
        agent_id: str,
        question: str,
        context: str
    ) -> ClarificationRequest:
        """Request clarification from an agent.
        
        Args:
            agent_id: ID of agent to request clarification from
            question: Question to ask
            context: Context for the question
            
        Returns:
            ClarificationRequest
        """
        request = ClarificationRequest(
            agent_id=agent_id,
            question=question,
            context=context
        )
        
        logger.info(
            f"Clarification requested from {agent_id}: {question}"
        )
        
        return request
    
    def provide_reasoning(self, reasoning: JudgeReasoning) -> str:
        """Provide reasoning in human-readable format.
        
        Args:
            reasoning: Judge reasoning to format
            
        Returns:
            Formatted reasoning string
        """
        output = [
            f"Decision: {reasoning.decision}",
            f"Confidence: {reasoning.confidence:.2f}",
            "",
            "Reasoning:",
            reasoning.reasoning,
        ]
        
        if reasoning.key_factors:
            output.append("")
            output.append("Key Factors:")
            for factor in reasoning.key_factors:
                output.append(f"- {factor}")
        
        if reasoning.alternative_considered:
            output.append("")
            output.append(f"Alternative Considered: {reasoning.alternative_considered}")
        
        return "\n".join(output)
    
    def get_circuit_breaker_state(self) -> Dict[str, Any]:
        """Get circuit breaker state and statistics.
        
        Returns:
            Dictionary with circuit breaker state and stats
        """
        stats = self.circuit_breaker.get_stats()
        return {
            "state": stats.state.value,
            "failure_count": stats.failure_count,
            "success_count": stats.success_count,
            "last_failure_time": stats.last_failure_time,
            "last_success_time": stats.last_success_time,
            "total_calls": stats.total_calls,
            "total_failures": stats.total_failures,
            "total_successes": stats.total_successes,
        }
    
    def reset_circuit_breaker(self) -> None:
        """Reset circuit breaker to CLOSED state."""
        self.circuit_breaker.reset()
        logger.info("Circuit breaker reset to CLOSED state")
    
    def collect_metrics(self) -> None:
        """Collect metrics from all components."""
        # Collect circuit breaker metrics
        self.metrics_collector.collect_circuit_breaker_metrics(
            "logical_judge", self.circuit_breaker
        )
        
        # Collect cache metrics
        self.metrics_collector.collect_cache_metrics(
            "logical_judge", self.cache
        )
        
        # Record judge-specific metrics
        self.metrics_collector.set_gauge(
            "logical_judge", "judge_temperature", self.temperature
        )
        self.metrics_collector.set_gauge(
            "logical_judge", "judge_max_tokens", self.max_tokens
        )
