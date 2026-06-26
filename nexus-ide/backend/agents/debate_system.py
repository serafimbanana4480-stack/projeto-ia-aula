"""Debate and Critic Agent System for Quality Improvement.

Implements structured debates, critic agents, consensus building,
argument evaluation, and quality enhancement through adversarial reasoning.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union, Tuple
from datetime import datetime

from ..orchestrator.communication_protocol import MessageProtocol, MessageEnvelope, MessageType
from ..agents.base import AgentBase, AgentRequest

logger = logging.getLogger(__name__)


class DebateRole(str, Enum):
    """Roles in debate system."""
    PROPOSER = "proposer"  # Proposes solution
    CRITIC = "critic"  # Critiques solution
    SUPPORTER = "supporter"  # Supports proposal
    MODERATOR = "moderator"  # Moderates debate
    SYNTHESIZER = "synthesizer"  # Synthesizes results


class ArgumentType(str, Enum):
    """Types of arguments in debate."""
    CLAIM = "claim"  # Main claim/thesis
    EVIDENCE = "evidence"  # Supporting evidence
    REASONING = "reasoning"  # Logical reasoning
    COUNTER = "counter"  # Counter-argument
    REBUTTAL = "rebuttal"  # Rebuttal to counter
    QUESTION = "question"  # Clarifying question
    OBJECTION = "objection"  # Formal objection


class ArgumentStrength(str, Enum):
    """Strength of arguments."""
    WEAK = "weak"  # 0.0-0.3
    MODERATE = "moderate"  # 0.3-0.6
    STRONG = "strong"  # 0.6-0.8
    VERY_STRONG = "very_strong"  # 0.8-1.0


@dataclass
class Argument:
    """Individual argument in debate."""
    argument_id: str = field(default_factory=lambda: f"arg-{uuid.uuid4().hex[:12]}")
    debate_id: str = ""
    agent_id: str = ""
    role: DebateRole = DebateRole.PROPOSER
    argument_type: ArgumentType = ArgumentType.CLAIM
    content: str = ""
    
    # Argument structure
    premise: str = ""
    conclusion: str = ""
    evidence: List[str] = field(default_factory=list)
    reasoning: str = ""
    
    # Quality metrics
    strength: ArgumentStrength = ArgumentStrength.MODERATE
    confidence: float = 0.5  # 0.0-1.0
    relevance: float = 0.5  # 0.0-1.0
    validity: float = 0.5  # 0.0-1.0
    
    # Relationships
    parent_argument_id: Optional[str] = None
    rebuttal_argument_ids: List[str] = field(default_factory=list)
    supporting_argument_ids: List[str] = field(default_factory=list)
    
    # Metadata
    timestamp: float = field(default_factory=time.time)
    round_number: int = 1
    tags: Set[str] = field(default_factory=set)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "argument_id": self.argument_id,
            "debate_id": self.debate_id,
            "agent_id": self.agent_id,
            "role": self.role.value,
            "argument_type": self.argument_type.value,
            "content": self.content,
            "premise": self.premise,
            "conclusion": self.conclusion,
            "evidence": self.evidence,
            "reasoning": self.reasoning,
            "strength": self.strength.value,
            "confidence": self.confidence,
            "relevance": self.relevance,
            "validity": self.validity,
            "parent_argument_id": self.parent_argument_id,
            "rebuttal_argument_ids": self.rebuttal_argument_ids,
            "supporting_argument_ids": self.supporting_argument_ids,
            "timestamp": self.timestamp,
            "round_number": self.round_number,
            "tags": list(self.tags),
        }


@dataclass
class Debate:
    """Structured debate session."""
    debate_id: str = field(default_factory=lambda: f"debate-{uuid.uuid4().hex[:12]}")
    topic: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    
    # Participants
    proposer_id: str = ""
    critic_ids: List[str] = field(default_factory=list)
    supporter_ids: List[str] = field(default_factory=list)
    moderator_id: str = ""
    synthesizer_id: str = ""
    
    # Debate structure
    max_rounds: int = 3
    current_round: int = 1
    max_arguments_per_round: int = 5
    time_limit_per_round: float = 300.0  # 5 minutes
    
    # Arguments
    arguments: List[Argument] = field(default_factory=list)
    argument_graph: Dict[str, List[str]] = field(default_factory=dict)
    
    # Results
    consensus_reached: bool = False
    consensus_statement: str = ""
    final_recommendation: str = ""
    quality_score: float = 0.0
    
    # Metadata
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "debate_id": self.debate_id,
            "topic": self.topic,
            "context": self.context,
            "proposer_id": self.proposer_id,
            "critic_ids": self.critic_ids,
            "supporter_ids": self.supporter_ids,
            "moderator_id": self.moderator_id,
            "synthesizer_id": self.synthesizer_id,
            "max_rounds": self.max_rounds,
            "current_round": self.current_round,
            "max_arguments_per_round": self.max_arguments_per_round,
            "time_limit_per_round": self.time_limit_per_round,
            "arguments": [arg.to_dict() for arg in self.arguments],
            "argument_graph": self.argument_graph,
            "consensus_reached": self.consensus_reached,
            "consensus_statement": self.consensus_statement,
            "final_recommendation": self.final_recommendation,
            "quality_score": self.quality_score,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class CritiqueResult:
    """Result of critic agent analysis."""
    critique_id: str = field(default_factory=lambda: f"crit-{uuid.uuid4().hex[:12]}")
    target_content: str = ""
    critique_type: str = "general"
    
    # Critique dimensions
    logical_validity: float = 0.0  # 0.0-1.0
    factual_accuracy: float = 0.0  # 0.0-1.0
    clarity: float = 0.0  # 0.0-1.0
    completeness: float = 0.0  # 0.0-1.0
    consistency: float = 0.0  # 0.0-1.0
    
    # Specific issues
    logical_fallacies: List[str] = field(default_factory=list)
    factual_errors: List[str] = field(default_factory=list)
    ambiguities: List[str] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)
    inconsistencies: List[str] = field(default_factory=list)
    
    # Recommendations
    improvements: List[str] = field(default_factory=list)
    alternative_approaches: List[str] = field(default_factory=list)
    supporting_evidence: List[str] = field(default_factory=list)
    
    # Overall assessment
    overall_score: float = 0.0  # 0.0-1.0
    confidence: float = 0.0  # 0.0-1.0
    severity: str = "low"  # low, medium, high, critical
    
    # Metadata
    timestamp: float = field(default_factory=time.time)
    critic_id: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "critique_id": self.critique_id,
            "target_content": self.target_content,
            "critique_type": self.critique_type,
            "logical_validity": self.logical_validity,
            "factual_accuracy": self.factual_accuracy,
            "clarity": self.clarity,
            "completeness": self.completeness,
            "consistency": self.consistency,
            "logical_fallacies": self.logical_fallacies,
            "factual_errors": self.factual_errors,
            "ambiguities": self.ambiguities,
            "missing_information": self.missing_information,
            "inconsistencies": self.inconsistencies,
            "improvements": self.improvements,
            "alternative_approaches": self.alternative_approaches,
            "supporting_evidence": self.supporting_evidence,
            "overall_score": self.overall_score,
            "confidence": self.confidence,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "critic_id": self.critic_id,
        }


class DebateAgent:
    """Specialized agent for participating in debates."""
    
    def __init__(self, agent_id: str, role: DebateRole, model_client):
        self.agent_id = agent_id
        self.role = role
        self.model_client = model_client
        self.protocol = MessageProtocol()
        
    async def participate_in_debate(
        self,
        debate: Debate,
        round_number: int,
        previous_arguments: List[Argument]
    ) -> List[Argument]:
        """Participate in a debate round."""
        logger.info("Agent %s participating in debate %s round %d", 
                   self.agent_id, debate.debate_id, round_number)
        
        # Generate arguments based on role
        if self.role == DebateRole.PROPOSER:
            return await self._generate_proposal(debate, round_number, previous_arguments)
        elif self.role == DebateRole.CRITIC:
            return await self._generate_critiques(debate, round_number, previous_arguments)
        elif self.role == DebateRole.SUPPORTER:
            return await self._generate_support(debate, round_number, previous_arguments)
        elif self.role == DebateRole.MODERATOR:
            return await self._moderate_debate(debate, round_number, previous_arguments)
        elif self.role == DebateRole.SYNTHESIZER:
            return await self._synthesize_debate(debate, round_number, previous_arguments)
        else:
            return []
            
    async def _generate_proposal(
        self,
        debate: Debate,
        round_number: int,
        previous_arguments: List[Argument]
    ) -> List[Argument]:
        """Generate proposal arguments."""
        prompt = f"""You are a PROPOSER in a structured debate about: {debate.topic}

CONTEXT: {json.dumps(debate.context, indent=2)}

PREVIOUS ARGUMENTS:
{self._format_arguments(previous_arguments)}

YOUR ROLE: Propose a comprehensive solution to the topic. Be clear, logical, and evidence-based.

GENERATE 1-3 arguments following this structure:
1. Main claim with clear premise and conclusion
2. Supporting evidence and reasoning
3. Address potential counter-arguments

RESPONSE FORMAT:
Return JSON array:
{{
  "arguments": [
    {{
      "content": "Main argument content",
      "premise": "Premise of the argument",
      "conclusion": "Conclusion of the argument",
      "evidence": ["Evidence 1", "Evidence 2"],
      "reasoning": "Logical reasoning",
      "strength": "strong",
      "confidence": 0.8,
      "relevance": 0.9,
      "validity": 0.85,
      "tags": ["proposal", "solution"]
    }}
  ]
}}

Return ONLY the JSON array."""
        
        try:
            response = await self.model_client.chat_complete(
                model="llama3.2",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Generate proposal arguments"},
                ],
                options={"temperature": 0.7, "num_predict": 2048},
            )
            
            return self._parse_arguments(response, debate.debate_id, round_number)
            
        except Exception as exc:
            logger.error("Failed to generate proposal: %s", exc)
            return []
            
    async def _generate_critiques(
        self,
        debate: Debate,
        round_number: int,
        previous_arguments: List[Argument]
    ) -> List[Argument]:
        """Generate critique arguments."""
        prompt = f"""You are a CRITIC in a structured debate about: {debate.topic}

CONTEXT: {json.dumps(debate.context, indent=2)}

PREVIOUS ARGUMENTS:
{self._format_arguments(previous_arguments)}

YOUR ROLE: Critically analyze the proposals and identify weaknesses, gaps, and counter-arguments.

GENERATE 1-3 counter-arguments:
1. Identify logical fallacies or weak reasoning
2. Point out factual inaccuracies or missing evidence
3. Suggest alternative approaches

RESPONSE FORMAT:
Return JSON array:
{{
  "arguments": [
    {{
      "content": "Counter-argument content",
      "premise": "Premise of counter-argument",
      "conclusion": "Conclusion of counter-argument",
      "evidence": ["Contradictory evidence"],
      "reasoning": "Logical reasoning against proposal",
      "strength": "strong",
      "confidence": 0.8,
      "relevance": 0.9,
      "validity": 0.85,
      "parent_argument_id": "arg-to-counter",
      "tags": ["critique", "counter"]
    }}
  ]
}}

Return ONLY the JSON array."""
        
        try:
            response = await self.model_client.chat_complete(
                model="llama3.2",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Generate critique arguments"},
                ],
                options={"temperature": 0.6, "num_predict": 2048},
            )
            
            return self._parse_arguments(response, debate.debate_id, round_number)
            
        except Exception as exc:
            logger.error("Failed to generate critiques: %s", exc)
            return []
            
    async def _generate_support(
        self,
        debate: Debate,
        round_number: int,
        previous_arguments: List[Argument]
    ) -> List[Argument]:
        """Generate supporting arguments."""
        prompt = f"""You are a SUPPORTER in a structured debate about: {debate.topic}

CONTEXT: {json.dumps(debate.context, indent=2)}

PREVIOUS ARGUMENTS:
{self._format_arguments(previous_arguments)}

YOUR ROLE: Support the best proposals with additional evidence, reasoning, and examples.

GENERATE 1-3 supporting arguments:
1. Find additional evidence for strong proposals
2. Provide real-world examples or case studies
3. Strengthen logical reasoning

RESPONSE FORMAT:
Return JSON array:
{{
  "arguments": [
    {{
      "content": "Supporting argument content",
      "premise": "Premise of support",
      "conclusion": "Conclusion of support",
      "evidence": ["Additional evidence"],
      "reasoning": "Supporting reasoning",
      "strength": "strong",
      "confidence": 0.8,
      "relevance": 0.9,
      "validity": 0.85,
      "parent_argument_id": "arg-to-support",
      "tags": ["support", "evidence"]
    }}
  ]
}}

Return ONLY the JSON array."""
        
        try:
            response = await self.model_client.chat_complete(
                model="llama3.2",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Generate supporting arguments"},
                ],
                options={"temperature": 0.6, "num_predict": 2048},
            )
            
            return self._parse_arguments(response, debate.debate_id, round_number)
            
        except Exception as exc:
            logger.error("Failed to generate support: %s", exc)
            return []
            
    async def _moderate_debate(
        self,
        debate: Debate,
        round_number: int,
        previous_arguments: List[Argument]
    ) -> List[Argument]:
        """Moderate debate and provide guidance."""
        prompt = f"""You are a MODERATOR in a structured debate about: {debate.topic}

CONTEXT: {json.dumps(debate.context, indent=2)}

PREVIOUS ARGUMENTS:
{self._format_arguments(previous_arguments)}

YOUR ROLE: Moderate the debate by:
1. Identifying areas of agreement/disagreement
2. Clarifying ambiguous points
3. Suggesting areas needing more evidence
4. Guiding the debate toward consensus

GENERATE 1-2 moderation arguments:
1. Clarifying questions or observations
2. Suggestions for finding common ground

RESPONSE FORMAT:
Return JSON array:
{{
  "arguments": [
    {{
      "content": "Moderation content",
      "premise": "Moderation premise",
      "conclusion": "Moderation conclusion",
      "evidence": ["Observations"],
      "reasoning": "Moderation reasoning",
      "strength": "moderate",
      "confidence": 0.7,
      "relevance": 0.8,
      "validity": 0.8,
      "tags": ["moderation", "clarification"]
    }}
  ]
}}

Return ONLY the JSON array."""
        
        try:
            response = await self.model_client.chat_complete(
                model="llama3.2",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Generate moderation arguments"},
                ],
                options={"temperature": 0.5, "num_predict": 1024},
            )
            
            return self._parse_arguments(response, debate.debate_id, round_number)
            
        except Exception as exc:
            logger.error("Failed to moderate debate: %s", exc)
            return []
            
    async def _synthesize_debate(
        self,
        debate: Debate,
        round_number: int,
        previous_arguments: List[Argument]
    ) -> List[Argument]:
        """Synthesize debate results."""
        prompt = f"""You are a SYNTHESIZER in a structured debate about: {debate.topic}

CONTEXT: {json.dumps(debate.context, indent=2)}

PREVIOUS ARGUMENTS:
{self._format_arguments(previous_arguments)}

YOUR ROLE: Synthesize the debate by:
1. Identifying key points of agreement
2. Finding common ground between opposing views
3. Proposing consensus solutions
4. Summarizing the debate outcome

GENERATE 1-2 synthesis arguments:
1. Summary of key findings
2. Consensus proposal

RESPONSE FORMAT:
Return JSON array:
{{
  "arguments": [
    {{
      "content": "Synthesis content",
      "premise": "Synthesis premise",
      "conclusion": "Synthesis conclusion",
      "evidence": ["Key findings"],
      "reasoning": "Synthesis reasoning",
      "strength": "strong",
      "confidence": 0.9,
      "relevance": 0.9,
      "validity": 0.9,
      "tags": ["synthesis", "consensus"]
    }}
  ]
}}

Return ONLY the JSON array."""
        
        try:
            response = await self.model_client.chat_complete(
                model="llama3.2",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Generate synthesis arguments"},
                ],
                options={"temperature": 0.4, "num_predict": 2048},
            )
            
            return self._parse_arguments(response, debate.debate_id, round_number)
            
        except Exception as exc:
            logger.error("Failed to synthesize debate: %s", exc)
            return []
            
    def _format_arguments(self, arguments: List[Argument]) -> str:
        """Format arguments for display."""
        if not arguments:
            return "No previous arguments"
            
        formatted = []
        for arg in arguments:
            formatted.append(f"[{arg.role.value.upper()}] {arg.content[:200]}...")
            
        return "\n".join(formatted)
        
    def _parse_arguments(
        self,
        response: str,
        debate_id: str,
        round_number: int
    ) -> List[Argument]:
        """Parse arguments from model response."""
        try:
            # Extract JSON from response
            if "```json" in response:
                json_start = response.find("```json")
                json_end = response.find("```", json_start + 7)
                json_str = response[json_start + 7:json_end]
            else:
                json_str = response
                
            data = json.loads(json_str)
            
            arguments = []
            for arg_data in data.get("arguments", []):
                argument = Argument(
                    debate_id=debate_id,
                    agent_id=self.agent_id,
                    role=self.role,
                    argument_type=ArgumentType.CLAIM,  # Default
                    content=arg_data.get("content", ""),
                    premise=arg_data.get("premise", ""),
                    conclusion=arg_data.get("conclusion", ""),
                    evidence=arg_data.get("evidence", []),
                    reasoning=arg_data.get("reasoning", ""),
                    strength=ArgumentStrength(arg_data.get("strength", "moderate")),
                    confidence=float(arg_data.get("confidence", 0.5)),
                    relevance=float(arg_data.get("relevance", 0.5)),
                    validity=float(arg_data.get("validity", 0.5)),
                    parent_argument_id=arg_data.get("parent_argument_id"),
                    round_number=round_number,
                    tags=set(arg_data.get("tags", [])),
                )
                arguments.append(argument)
                
            return arguments
            
        except Exception as exc:
            logger.error("Failed to parse arguments: %s", exc)
            return []


class CriticAgent:
    """Specialized agent for critiquing content."""
    
    def __init__(self, agent_id: str, model_client):
        self.agent_id = agent_id
        self.model_client = model_client
        
    async def critique_content(
        self,
        content: str,
        critique_type: str = "general",
        context: Optional[Dict[str, Any]] = None
    ) -> CritiqueResult:
        """Perform comprehensive critique of content."""
        logger.info("Critic agent %s analyzing content", self.agent_id)
        
        prompt = f"""You are an expert critic performing comprehensive analysis of content.

CONTENT TO CRITIQUE:
{content}

CRITIQUE TYPE: {critique_type}
CONTEXT: {json.dumps(context or {}, indent=2)}

ANALYSIS DIMENSIONS:
1. Logical Validity: Check for logical fallacies, invalid reasoning
2. Factual Accuracy: Verify factual claims, identify errors
3. Clarity: Assess clarity, identify ambiguities
4. Completeness: Check for missing information
5. Consistency: Identify internal contradictions

SPECIFIC ISSUES TO IDENTIFY:
- Logical fallacies (ad hominem, straw man, false dilemma, etc.)
- Factual errors or unsupported claims
- Ambiguous statements or unclear terminology
- Missing context or incomplete information
- Inconsistencies or contradictions

RECOMMENDATIONS:
- Specific improvements
- Alternative approaches
- Supporting evidence needed

RESPONSE FORMAT:
Return JSON:
{{
  "logical_validity": 0.8,
  "factual_accuracy": 0.7,
  "clarity": 0.6,
  "completeness": 0.5,
  "consistency": 0.9,
  "logical_fallacies": ["straw man argument detected"],
  "factual_errors": ["Claim about X is not supported"],
  "ambiguities": ["Term 'system' is undefined"],
  "missing_information": ["No data provided for claim"],
  "inconsistencies": ["Contradiction between paragraphs"],
  "improvements": ["Define terms clearly", "Provide supporting data"],
  "alternative_approaches": ["Consider alternative framework"],
  "supporting_evidence": ["Cite specific studies"],
  "overall_score": 0.7,
  "confidence": 0.8,
  "severity": "medium"
}}

Return ONLY the JSON object."""
        
        try:
            response = await self.model_client.chat_complete(
                model="llama3.2",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Critique the content"},
                ],
                options={"temperature": 0.3, "num_predict": 2048},
            )
            
            return self._parse_critique_result(response, content, critique_type)
            
        except Exception as exc:
            logger.error("Critique failed: %s", exc)
            
            return CritiqueResult(
                target_content=content,
                critique_type=critique_type,
                overall_score=0.5,
                confidence=0.1,
                critic_id=self.agent_id,
            )
            
    def _parse_critique_result(
        self,
        response: str,
        content: str,
        critique_type: str
    ) -> CritiqueResult:
        """Parse critique result from model response."""
        try:
            # Extract JSON from response
            if "```json" in response:
                json_start = response.find("```json")
                json_end = response.find("```", json_start + 7)
                json_str = response[json_start + 7:json_end]
            else:
                json_str = response
                
            data = json.loads(json_str)
            
            return CritiqueResult(
                target_content=content,
                critique_type=critique_type,
                logical_validity=float(data.get("logical_validity", 0.0)),
                factual_accuracy=float(data.get("factual_accuracy", 0.0)),
                clarity=float(data.get("clarity", 0.0)),
                completeness=float(data.get("completeness", 0.0)),
                consistency=float(data.get("consistency", 0.0)),
                logical_fallacies=data.get("logical_fallacies", []),
                factual_errors=data.get("factual_errors", []),
                ambiguities=data.get("ambiguities", []),
                missing_information=data.get("missing_information", []),
                inconsistencies=data.get("inconsistencies", []),
                improvements=data.get("improvements", []),
                alternative_approaches=data.get("alternative_approaches", []),
                supporting_evidence=data.get("supporting_evidence", []),
                overall_score=float(data.get("overall_score", 0.0)),
                confidence=float(data.get("confidence", 0.0)),
                severity=data.get("severity", "low"),
                critic_id=self.agent_id,
            )
            
        except Exception as exc:
            logger.error("Failed to parse critique result: %s", exc)
            
            return CritiqueResult(
                target_content=content,
                critique_type=critique_type,
                overall_score=0.5,
                confidence=0.1,
                critic_id=self.agent_id,
            )


class DebateSystem:
    """Central debate system managing debates and critiques."""
    
    def __init__(self, model_client):
        self.model_client = model_client
        self.protocol = MessageProtocol()
        
        # Active debates
        self.active_debates: Dict[str, Debate] = {}
        self.debate_agents: Dict[str, DebateAgent] = {}
        
        # Debate history
        self.debate_history: List[Debate] = []
        self.critique_history: List[CritiqueResult] = []
        
        # Statistics
        self.total_debates = 0
        self.completed_debates = 0
        self.total_critiques = 0
        
    async def create_debate(
        self,
        topic: str,
        context: Dict[str, Any],
        max_rounds: int = 3,
        time_limit_per_round: float = 300.0
    ) -> Debate:
        """Create a new debate."""
        debate = Debate(
            topic=topic,
            context=context,
            max_rounds=max_rounds,
            time_limit_per_round=time_limit_per_round,
        )
        
        # Create debate agents
        debate.proposer_id = f"proposer-{debate.debate_id[:8]}"
        debate.critic_ids = [f"critic-{debate.debate_id[:8]}-{i}" for i in range(2)]
        debate.supporter_ids = [f"supporter-{debate.debate_id[:8]}-{i}" for i in range(2)]
        debate.moderator_id = f"moderator-{debate.debate_id[:8]}"
        debate.synthesizer_id = f"synthesizer-{debate.debate_id[:8]}"
        
        # Create agent instances
        self.debate_agents[debate.proposer_id] = DebateAgent(
            debate.proposer_id, DebateRole.PROPOSER, self.model_client
        )
        
        for critic_id in debate.critic_ids:
            self.debate_agents[critic_id] = DebateAgent(
                critic_id, DebateRole.CRITIC, self.model_client
            )
            
        for supporter_id in debate.supporter_ids:
            self.debate_agents[supporter_id] = DebateAgent(
                supporter_id, DebateRole.SUPPORTER, self.model_client
            )
            
        self.debate_agents[debate.moderator_id] = DebateAgent(
            debate.moderator_id, DebateRole.MODERATOR, self.model_client
        )
        
        self.debate_agents[debate.synthesizer_id] = DebateAgent(
            debate.synthesizer_id, DebateRole.SYNTHESIZER, self.model_client
        )
        
        self.active_debates[debate.debate_id] = debate
        self.total_debates += 1
        
        logger.info("Created debate %s: %s", debate.debate_id, topic)
        return debate
        
    async def run_debate(self, debate_id: str) -> Debate:
        """Run a complete debate."""
        if debate_id not in self.active_debates:
            raise ValueError(f"Debate {debate_id} not found")
            
        debate = self.active_debates[debate_id]
        debate.started_at = time.time()
        
        logger.info("Starting debate %s", debate.debate_id)
        
        # Run debate rounds
        for round_num in range(1, debate.max_rounds + 1):
            debate.current_round = round_num
            
            logger.info("Debate %s - Round %d", debate.debate_id, round_num)
            
            # Get arguments from all agents
            all_arguments = []
            
            # Proposer goes first
            proposer = self.debate_agents[debate.proposer_id]
            proposer_args = await proposer.participate_in_debate(
                debate, round_num, debate.arguments
            )
            all_arguments.extend(proposer_args)
            
            # Critics respond
            for critic_id in debate.critic_ids:
                critic = self.debate_agents[critic_id]
                critic_args = await critic.participate_in_debate(
                    debate, round_num, all_arguments
                )
                all_arguments.extend(critic_args)
                
            # Supporters respond
            for supporter_id in debate.supporter_ids:
                supporter = self.debate_agents[supporter_id]
                supporter_args = await supporter.participate_in_debate(
                    debate, round_num, all_arguments
                )
                all_arguments.extend(supporter_args)
                
            # Moderator provides guidance
            moderator = self.debate_agents[debate.moderator_id]
            moderator_args = await moderator.participate_in_debate(
                debate, round_num, all_arguments
            )
            all_arguments.extend(moderator_args)
            
            # Add all arguments to debate
            debate.arguments.extend(all_arguments)
            
            # Wait between rounds
            if round_num < debate.max_rounds:
                await asyncio.sleep(1.0)
                
        # Synthesize final results
        synthesizer = self.debate_agents[debate.synthesizer_id]
        synthesis_args = await synthesizer.participate_in_debate(
            debate, debate.max_rounds + 1, debate.arguments
        )
        debate.arguments.extend(synthesis_args)
        
        # Generate consensus and recommendation
        await self._generate_debate_consensus(debate)
        
        # Complete debate
        debate.completed_at = time.time()
        self.completed_debates += 1
        
        # Move to history
        self.debate_history.append(debate)
        del self.active_debates[debate_id]
        
        logger.info("Completed debate %s with quality score %.2f", 
                   debate.debate_id, debate.quality_score)
        
        return debate
        
    async def _generate_debate_consensus(self, debate: Debate) -> None:
        """Generate consensus statement and recommendation."""
        # Find synthesis arguments
        synthesis_args = [
            arg for arg in debate.arguments
            if arg.role == DebateRole.SYNTHESIZER
        ]
        
        if synthesis_args:
            # Use best synthesis
            best_synthesis = max(synthesis_args, key=lambda a: a.confidence)
            debate.consensus_statement = best_synthesis.content
            debate.final_recommendation = best_synthesis.conclusion
            debate.consensus_reached = True
        else:
            # Generate consensus from all arguments
            high_confidence_args = [
                arg for arg in debate.arguments
                if arg.confidence > 0.7
            ]
            
            if high_confidence_args:
                debate.consensus_statement = "Partial consensus reached on key points"
                debate.final_recommendation = "Proceed with caution and additional validation"
                debate.consensus_reached = False
            else:
                debate.consensus_statement = "No consensus reached"
                debate.final_recommendation = "Revisit topic with additional information"
                debate.consensus_reached = False
                
        # Calculate quality score
        debate.quality_score = self._calculate_debate_quality(debate)
        
    def _calculate_debate_quality(self, debate: Debate) -> float:
        """Calculate overall debate quality score."""
        if not debate.arguments:
            return 0.0
            
        # Average confidence across all arguments
        avg_confidence = sum(arg.confidence for arg in debate.arguments) / len(debate.arguments)
        
        # Average validity
        avg_validity = sum(arg.validity for arg in debate.arguments) / len(debate.arguments)
        
        # Argument diversity (different roles represented)
        roles_represented = len(set(arg.role for arg in debate.arguments))
        role_diversity = roles_represented / 5.0  # 5 possible roles
        
        # Consensus bonus
        consensus_bonus = 0.2 if debate.consensus_reached else 0.0
        
        # Round completion bonus
        round_bonus = (debate.current_round / debate.max_rounds) * 0.1
        
        quality_score = (
            avg_confidence * 0.3 +
            avg_validity * 0.3 +
            role_diversity * 0.2 +
            consensus_bonus +
            round_bonus
        )
        
        return min(1.0, quality_score)
        
    async def critique_content(
        self,
        content: str,
        critique_type: str = "general",
        context: Optional[Dict[str, Any]] = None
    ) -> CritiqueResult:
        """Perform content critique."""
        critic_id = f"critic-{uuid.uuid4().hex[:8]}"
        critic = CriticAgent(critic_id, self.model_client)
        
        result = await critic.critique_content(content, critique_type, context)
        
        self.critique_history.append(result)
        self.total_critiques += 1
        
        return result
        
    def get_debate_stats(self) -> Dict[str, Any]:
        """Get debate system statistics."""
        return {
            "total_debates": self.total_debates,
            "completed_debates": self.completed_debates,
            "active_debates": len(self.active_debates),
            "total_critiques": self.total_critiques,
            "average_debate_quality": (
                sum(d.quality_score for d in self.debate_history) / len(self.debate_history)
                if self.debate_history else 0.0
            ),
            "consensus_rate": (
                sum(1 for d in self.debate_history if d.consensus_reached) / len(self.debate_history)
                if self.debate_history else 0.0
            ),
        }
        
    def get_debate_history(
        self,
        limit: int = 50,
        min_quality: float = 0.0
    ) -> List[Debate]:
        """Get debate history with filters."""
        filtered = [
            debate for debate in self.debate_history
            if debate.quality_score >= min_quality
        ]
        
        return sorted(
            filtered,
            key=lambda d: d.completed_at or 0,
            reverse=True
        )[:limit]


# Global debate system instance
debate_system: Optional[DebateSystem] = None