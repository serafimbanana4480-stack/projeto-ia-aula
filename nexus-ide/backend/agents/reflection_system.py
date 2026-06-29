"""Reflection System — Advanced meta-cognition and self-improvement for agents.

This system provides agents with the ability to:
- Reflect on their own performance and decisions
- Conduct self-critique and identify improvement areas
- Adapt and improve based on experience
- Learn from both successes and failures
- Develop meta-cognitive awareness
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from backend.agents.base import AgentBase, AgentRequest
from backend.knowledge.memory import MemoryStore
from backend.observability.event_bus import EventBus
from backend.observability.events import Event

logger = logging.getLogger(__name__)


class ReflectionType(Enum):
    """Types of reflection an agent can perform."""
    PERFORMANCE = "performance"  # Reflect on task performance
    DECISION = "decision"      # Reflect on decision making
    LEARNING = "learning"      # Reflect on learning progress
    STRATEGY = "strategy"      # Reflect on strategy effectiveness
    COLLABORATION = "collaboration"  # Reflect on team interactions


class CritiqueLevel(Enum):
    """Levels of self-critique."""
    MILD = "mild"          # Minor suggestions for improvement
    MODERATE = "moderate"  # Significant areas for improvement
    SEVERE = "severe"      # Critical issues requiring immediate attention


@dataclass
class ReflectionResult:
    """Result of a reflection process."""
    agent_id: str
    reflection_type: ReflectionType
    timestamp: datetime
    performance_analysis: Dict[str, Any]
    self_critique: Dict[str, Any]
    improvement_suggestions: List[str]
    learning_insights: List[str]
    confidence_score: float
    action_items: List[str] = field(default_factory=list)


@dataclass
class SelfCritiqueResult:
    """Result of self-critique analysis."""
    strengths: List[str]
    weaknesses: List[str]
    opportunities: List[str]
    threats: List[str]
    critique_level: CritiqueLevel
    overall_assessment: str
    improvement_priority: List[str]


@dataclass
class MetaCognitionInsight:
    """Meta-cognitive insight about thinking patterns."""
    thinking_pattern: str
    effectiveness_score: float
    context_factors: List[str]
    improvement_suggestion: str
    confidence: float


class MetaCognitionEngine:
    """Engine for meta-cognitive analysis of agent thinking patterns."""
    
    def __init__(self, memory_system: MemoryStore, event_bus: EventBus):
        self.memory_system = memory_system
        self.event_bus = event_bus
        self.thinking_patterns = {}
        self.effectiveness_history = {}
    
    async def analyze_thinking_pattern(self, agent_id: str, task_result: Dict[str, Any]) -> List[MetaCognitionInsight]:
        """Analyze the agent's thinking patterns during task execution."""
        insights = []
        
        # Extract thinking process from task result
        thinking_process = task_result.get("thinking_process", [])
        decision_points = task_result.get("decisions", [])
        outcomes = task_result.get("outcomes", [])
        
        # Analyze pattern effectiveness
        for i, decision in enumerate(decision_points):
            pattern = decision.get("pattern", "unknown")
            outcome = outcomes[i] if i < len(outcomes) else None
            
            if outcome:
                effectiveness = self._calculate_effectiveness(decision, outcome)
                insight = MetaCognitionInsight(
                    thinking_pattern=pattern,
                    effectiveness_score=effectiveness,
                    context_factors=decision.get("context", []),
                    improvement_suggestion=self._generate_suggestion(pattern, effectiveness),
                    confidence=self._calculate_confidence(decision, outcome)
                )
                insights.append(insight)
        
        # Store patterns for future reference
        self.thinking_patterns[agent_id] = insights
        
        # Emit meta-cognition event
        await self.event_bus.emit(Event(
            type="meta_cognition_analyzed",
            data={
                "agent_id": agent_id,
                "insights_count": len(insights),
                "avg_effectiveness": sum(i.effectiveness_score for i in insights) / len(insights) if insights else 0
            }
        ))
        
        return insights
    
    def _calculate_effectiveness(self, decision: Dict[str, Any], outcome: Dict[str, Any]) -> float:
        """Calculate effectiveness score of a decision."""
        success_score = outcome.get("success_score", 0.0)
        efficiency_score = outcome.get("efficiency_score", 0.0)
        quality_score = outcome.get("quality_score", 0.0)
        
        # Weighted average
        return (success_score * 0.4 + efficiency_score * 0.3 + quality_score * 0.3)
    
    def _generate_suggestion(self, pattern: str, effectiveness: float) -> str:
        """Generate improvement suggestion based on pattern and effectiveness."""
        if effectiveness < 0.5:
            return f"Consider alternative approaches for {pattern} pattern - current effectiveness is low"
        elif effectiveness < 0.8:
            return f"Optimize {pattern} pattern for better results"
        else:
            return f"Continue using {pattern} pattern - it's working well"
    
    def _calculate_confidence(self, decision: Dict[str, Any], outcome: Dict[str, Any]) -> float:
        """Calculate confidence in the analysis."""
        data_completeness = decision.get("data_completeness", 0.5)
        outcome_clarity = outcome.get("clarity", 0.5)
        return (data_completeness + outcome_clarity) / 2


class SelfCritiqueEngine:
    """Engine for self-critique and improvement identification."""
    
    def __init__(self, memory_system: MemoryStore, event_bus: EventBus):
        self.memory_system = memory_system
        self.event_bus = event_bus
        self.critique_history = {}
    
    async def critique_performance(self, agent_id: str, task_result: Dict[str, Any]) -> SelfCritiqueResult:
        """Perform self-critique of agent performance."""
        
        # Analyze performance metrics
        performance_metrics = task_result.get("performance_metrics", {})
        success_rate = performance_metrics.get("success_rate", 0.0)
        efficiency_score = performance_metrics.get("efficiency_score", 0.0)
        quality_score = performance_metrics.get("quality_score", 0.0)
        
        # Identify strengths
        strengths = []
        if success_rate > 0.8:
            strengths.append("High success rate in task completion")
        if efficiency_score > 0.8:
            strengths.append("Excellent resource utilization")
        if quality_score > 0.8:
            strengths.append("High quality output")
        
        # Identify weaknesses
        weaknesses = []
        if success_rate < 0.6:
            weaknesses.append("Low success rate needs improvement")
        if efficiency_score < 0.6:
            weaknesses.append("Resource utilization could be optimized")
        if quality_score < 0.6:
            weaknesses.append("Output quality needs enhancement")
        
        # Identify opportunities
        opportunities = []
        if success_rate > 0.6 and success_rate < 0.8:
            opportunities.append("Optimize successful patterns for better consistency")
        if efficiency_score > 0.6 and efficiency_score < 0.8:
            opportunities.append("Fine-tune resource allocation")
        opportunities.append("Learn from peer agent strategies")
        
        # Identify threats
        threats = []
        if success_rate < 0.5:
            threats.append("Risk of becoming unreliable")
        if efficiency_score < 0.5:
            threats.append("Resource waste affecting system performance")
        if quality_score < 0.5:
            threats.append("Poor quality may impact user trust")
        
        # Determine critique level
        overall_score = (success_rate + efficiency_score + quality_score) / 3
        if overall_score >= 0.8:
            critique_level = CritiqueLevel.MILD
        elif overall_score >= 0.6:
            critique_level = CritiqueLevel.MODERATE
        else:
            critique_level = CritiqueLevel.SEVERE
        
        # Generate overall assessment
        overall_assessment = self._generate_assessment(overall_score, critique_level)
        
        # Prioritize improvements
        improvement_priority = self._prioritize_improvements(strengths, weaknesses, opportunities, threats)
        
        result = SelfCritiqueResult(
            strengths=strengths,
            weaknesses=weaknesses,
            opportunities=opportunities,
            threats=threats,
            critique_level=critique_level,
            overall_assessment=overall_assessment,
            improvement_priority=improvement_priority
        )
        
        # Store critique history
        self.critique_history[agent_id] = result
        
        # Emit critique event
        await self.event_bus.emit(Event(
            type="self_critique_completed",
            data={
                "agent_id": agent_id,
                "critique_level": critique_level.value,
                "overall_score": overall_score,
                "improvements_needed": len(improvement_priority)
            }
        ))
        
        return result
    
    def _generate_assessment(self, overall_score: float, critique_level: CritiqueLevel) -> str:
        """Generate overall assessment of performance."""
        if critique_level == CritiqueLevel.MILD:
            return "Performance is excellent with minor areas for optimization"
        elif critique_level == CritiqueLevel.MODERATE:
            return "Performance is good but needs focused improvements"
        else:
            return "Performance requires immediate attention and significant improvements"
    
    def _prioritize_improvements(self, strengths: List[str], weaknesses: List[str], 
                                opportunities: List[str], threats: List[str]) -> List[str]:
        """Prioritize improvements based on SWOT analysis."""
        priorities = []
        
        # Prioritize addressing threats first
        priorities.extend([f"Address threat: {threat}" for threat in threats])
        
        # Then address weaknesses
        priorities.extend([f"Improve weakness: {weakness}" for weakness in weaknesses])
        
        # Finally, leverage opportunities
        priorities.extend([f"Exploit opportunity: {opportunity}" for opportunity in opportunities])
        
        return priorities


class SelfImprovementEngine:
    """Engine for generating and implementing self-improvement plans."""
    
    def __init__(self, memory_system: MemoryStore, event_bus: EventBus):
        self.memory_system = memory_system
        self.event_bus = event_bus
        self.improvement_plans = {}
        self.improvement_history = {}
    
    async def generate_improvement_plan(self, agent_id: str, 
                                       meta_insights: List[MetaCognitionInsight],
                                       critique_result: SelfCritiqueResult) -> Dict[str, Any]:
        """Generate comprehensive improvement plan based on reflection results."""
        
        # Analyze meta-cognitive insights
        pattern_improvements = {}
        for insight in meta_insights:
            if insight.effectiveness_score < 0.7:
                pattern_improvements[insight.thinking_pattern] = insight.improvement_suggestion
        
        # Address critique priorities
        improvement_actions = []
        for priority in critique_result.improvement_priority:
            action = self._create_improvement_action(priority)
            improvement_actions.append(action)
        
        # Create learning objectives
        learning_objectives = self._create_learning_objectives(critique_result)
        
        # Generate implementation timeline
        timeline = self._create_implementation_timeline(improvement_actions)
        
        # Calculate expected improvements
        expected_improvements = self._calculate_expected_improvements(
            meta_insights, critique_result, improvement_actions
        )
        
        improvement_plan = {
            "agent_id": agent_id,
            "pattern_improvements": pattern_improvements,
            "improvement_actions": improvement_actions,
            "learning_objectives": learning_objectives,
            "timeline": timeline,
            "expected_improvements": expected_improvements,
            "confidence_score": self._calculate_plan_confidence(meta_insights, critique_result),
            "created_at": datetime.now().isoformat()
        }
        
        # Store improvement plan
        self.improvement_plans[agent_id] = improvement_plan
        
        # Emit improvement plan event
        await self.event_bus.emit(Event(
            type="improvement_plan_generated",
            data={
                "agent_id": agent_id,
                "actions_count": len(improvement_actions),
                "confidence_score": improvement_plan["confidence_score"]
            }
        ))
        
        return improvement_plan
    
    def _create_improvement_action(self, priority: str) -> Dict[str, Any]:
        """Create specific improvement action from priority."""
        if "threat" in priority.lower():
            return {
                "type": "mitigation",
                "priority": "high",
                "description": priority,
                "estimated_effort": "high",
                "timeline": "immediate"
            }
        elif "weakness" in priority.lower():
            return {
                "type": "improvement",
                "priority": "medium",
                "description": priority,
                "estimated_effort": "medium",
                "timeline": "short_term"
            }
        else:
            return {
                "type": "enhancement",
                "priority": "low",
                "description": priority,
                "estimated_effort": "low",
                "timeline": "long_term"
            }
    
    def _create_learning_objectives(self, critique_result: SelfCritiqueResult) -> List[str]:
        """Create learning objectives based on critique results."""
        objectives = []
        
        for weakness in critique_result.weaknesses:
            if "success rate" in weakness.lower():
                objectives.append("Improve task completion strategies")
            elif "resource" in weakness.lower():
                objectives.append("Optimize resource management")
            elif "quality" in weakness.lower():
                objectives.append("Enhance output quality standards")
        
        for opportunity in critique_result.opportunities:
            if "peer" in opportunity.lower():
                objectives.append("Learn from successful peer strategies")
            elif "optimize" in opportunity.lower():
                objectives.append("Develop optimization techniques")
        
        return objectives
    
    def _create_implementation_timeline(self, actions: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """Create implementation timeline for improvement actions."""
        timeline = {
            "immediate": [],
            "short_term": [],
            "long_term": []
        }
        
        for action in actions:
            timeline[action["timeline"]].append(action["description"])
        
        return timeline
    
    def _calculate_expected_improvements(self, meta_insights: List[MetaCognitionInsight],
                                       critique_result: SelfCritiqueResult,
                                       actions: List[Dict[str, Any]]) -> Dict[str, float]:
        """Calculate expected improvements from implementing the plan."""
        # Base improvements from addressing weaknesses
        base_improvement = len(critique_result.weaknesses) * 0.1
        
        # Additional improvements from pattern optimization
        pattern_improvement = sum(0.05 for insight in meta_insights if insight.effectiveness_score < 0.7)
        
        # Improvements from learning objectives
        learning_improvement = len(critique_result.opportunities) * 0.03
        
        return {
            "success_rate": min(1.0, base_improvement + 0.2),
            "efficiency": min(1.0, pattern_improvement + 0.15),
            "quality": min(1.0, learning_improvement + 0.1),
            "overall": min(1.0, base_improvement + pattern_improvement + learning_improvement)
        }
    
    def _calculate_plan_confidence(self, meta_insights: List[MetaCognitionInsight],
                                 critique_result: SelfCritiqueResult) -> float:
        """Calculate confidence in the improvement plan."""
        # Confidence based on data quality and clarity of insights
        avg_insight_confidence = sum(i.confidence for i in meta_insights) / len(meta_insights) if meta_insights else 0.5
        
        # Adjust based on critique severity
        severity_adjustment = {
            CritiqueLevel.MILD: 0.1,
            CritiqueLevel.MODERATE: 0.0,
            CritiqueLevel.SEVERE: -0.1
        }
        
        confidence = avg_insight_confidence + severity_adjustment[critique_result.critique_level]
        return max(0.0, min(1.0, confidence))


class ReflectionSystem:
    """Main reflection system coordinating meta-cognition, self-critique, and self-improvement."""
    
    def __init__(self, memory_system: MemoryStore, event_bus: EventBus):
        self.memory_system = memory_system
        self.event_bus = event_bus
        self.meta_cognition = MetaCognitionEngine(memory_system, event_bus)
        self.self_critique = SelfCritiqueEngine(memory_system, event_bus)
        self.self_improvement = SelfImprovementEngine(memory_system, event_bus)
        self.reflection_history = {}
    
    async def reflect_on_task(self, agent_id: str, task_result: Dict[str, Any],
                            reflection_types: List[ReflectionType] = None) -> ReflectionResult:
        """Perform comprehensive reflection on task execution."""
        
        if reflection_types is None:
            reflection_types = [ReflectionType.PERFORMANCE, ReflectionType.DECISION, ReflectionType.LEARNING]
        
        # Perform meta-cognitive analysis
        meta_insights = await self.meta_cognition.analyze_thinking_pattern(agent_id, task_result)
        
        # Perform self-critique
        critique_result = await self.self_critique.critique_performance(agent_id, task_result)
        
        # Generate improvement plan
        improvement_plan = await self.self_improvement.generate_improvement_plan(
            agent_id, meta_insights, critique_result
        )
        
        # Extract learning insights
        learning_insights = self._extract_learning_insights(meta_insights, critique_result)
        
        # Generate improvement suggestions
        improvement_suggestions = self._generate_improvement_suggestions(
            meta_insights, critique_result, improvement_plan
        )
        
        # Calculate confidence score
        confidence_score = self._calculate_overall_confidence(
            meta_insights, critique_result, improvement_plan
        )
        
        # Create action items
        action_items = self._create_action_items(improvement_plan)
        
        # Create reflection result
        result = ReflectionResult(
            agent_id=agent_id,
            reflection_type=ReflectionType.PERFORMANCE,  # Primary reflection type
            timestamp=datetime.now(),
            performance_analysis=task_result.get("performance_metrics", {}),
            self_critique={
                "strengths": critique_result.strengths,
                "weaknesses": critique_result.weaknesses,
                "opportunities": critique_result.opportunities,
                "threats": critique_result.threats,
                "overall_assessment": critique_result.overall_assessment
            },
            improvement_suggestions=improvement_suggestions,
            learning_insights=learning_insights,
            confidence_score=confidence_score,
            action_items=action_items
        )
        
        # Store reflection history
        self.reflection_history[agent_id] = result
        
        # Emit reflection completed event
        await self.event_bus.emit(Event(
            type="reflection_completed",
            data={
                "agent_id": agent_id,
                "confidence_score": confidence_score,
                "improvements_suggested": len(improvement_suggestions),
                "action_items": len(action_items)
            }
        ))
        
        return result
    
    def _extract_learning_insights(self, meta_insights: List[MetaCognitionInsight],
                                 critique_result: SelfCritiqueResult) -> List[str]:
        """Extract key learning insights from reflection results."""
        insights = []
        
        # Insights from meta-cognition
        for insight in meta_insights:
            if insight.effectiveness_score > 0.8:
                insights.append(f"Effective pattern: {insight.thinking_pattern}")
            elif insight.effectiveness_score < 0.5:
                insights.append(f"Ineffective pattern: {insight.thinking_pattern}")
        
        # Insights from critique
        insights.extend([f"Key strength: {strength}" for strength in critique_result.strengths])
        insights.extend([f"Critical weakness: {weakness}" for weakness in critique_result.weaknesses])
        
        return insights
    
    def _generate_improvement_suggestions(self, meta_insights: List[MetaCognitionInsight],
                                        critique_result: SelfCritiqueResult,
                                        improvement_plan: Dict[str, Any]) -> List[str]:
        """Generate specific improvement suggestions."""
        suggestions = []
        
        # Suggestions from meta-cognition
        for insight in meta_insights:
            if insight.effectiveness_score < 0.7:
                suggestions.append(insight.improvement_suggestion)
        
        # Suggestions from critique
        suggestions.extend(critique_result.improvement_priority[:3])  # Top 3 priorities
        
        # Suggestions from improvement plan
        for action in improvement_plan["improvement_actions"][:2]:  # Top 2 actions
            suggestions.append(action["description"])
        
        return suggestions
    
    def _calculate_overall_confidence(self, meta_insights: List[MetaCognitionInsight],
                                    critique_result: SelfCritiqueResult,
                                    improvement_plan: Dict[str, Any]) -> float:
        """Calculate overall confidence in reflection results."""
        meta_confidence = sum(i.confidence for i in meta_insights) / len(meta_insights) if meta_insights else 0.5
        plan_confidence = improvement_plan["confidence_score"]
        
        # Weight the confidences
        return (meta_confidence * 0.4 + plan_confidence * 0.6)
    
    def _create_action_items(self, improvement_plan: Dict[str, Any]) -> List[str]:
        """Create actionable items from improvement plan."""
        action_items = []
        
        # Immediate actions
        for item in improvement_plan["timeline"].get("immediate", []):
            action_items.append(f"IMMEDIATE: {item}")
        
        # Short-term actions
        for item in improvement_plan["timeline"].get("short_term", []):
            action_items.append(f"SHORT-TERM: {item}")
        
        # Long-term actions
        for item in improvement_plan["timeline"].get("long_term", []):
            action_items.append(f"LONG-TERM: {item}")
        
        return action_items
    
    async def get_reflection_summary(self, agent_id: str) -> Dict[str, Any]:
        """Get summary of reflection history for an agent."""
        if agent_id not in self.reflection_history:
            return {"error": "No reflection history found for agent"}
        
        result = self.reflection_history[agent_id]
        
        return {
            "agent_id": agent_id,
            "last_reflection": result.timestamp.isoformat(),
            "confidence_score": result.confidence_score,
            "improvements_suggested": len(result.improvement_suggestions),
            "action_items": len(result.action_items),
            "strengths": len(result.self_critique.get("strengths", [])),
            "weaknesses": len(result.self_critique.get("weaknesses", [])),
            "learning_insights": len(result.learning_insights)
        }
    
    async def get_system_reflection_stats(self) -> Dict[str, Any]:
        """Get system-wide reflection statistics."""
        total_reflections = len(self.reflection_history)
        if total_reflections == 0:
            return {"total_reflections": 0}
        
        avg_confidence = sum(r.confidence_score for r in self.reflection_history.values()) / total_reflections
        total_improvements = sum(len(r.improvement_suggestions) for r in self.reflection_history.values())
        total_actions = sum(len(r.action_items) for r in self.reflection_history.values())
        
        return {
            "total_reflections": total_reflections,
            "average_confidence": avg_confidence,
            "total_improvements_suggested": total_improvements,
            "total_action_items": total_actions,
            "agents_with_reflections": len(self.reflection_history)
        }


class ReflectionAgent(AgentBase):
    """Agent specialized in reflection and meta-cognition."""
    
    def __init__(self, reflection_system: ReflectionSystem):
        super().__init__(
            name="reflection_agent",
            description="Specialized agent for meta-cognition and self-improvement",
            capabilities=["reflection", "meta_cognition", "self_critique", "self_improvement"]
        )
        self.reflection_system = reflection_system
    
    async def process_request(self, request: AgentRequest) -> Dict[str, Any]:
        """Process reflection request."""
        task_type = request.task.get("type")
        
        if task_type == "reflect_on_task":
            return await self._reflect_on_task(request)
        elif task_type == "get_reflection_summary":
            return await self._get_reflection_summary(request)
        elif task_type == "get_system_stats":
            return await self._get_system_stats(request)
        else:
            return {"error": f"Unknown task type: {task_type}"}
    
    async def _reflect_on_task(self, request: AgentRequest) -> Dict[str, Any]:
        """Handle reflection on task request."""
        agent_id = request.task.get("agent_id")
        task_result = request.task.get("task_result")
        reflection_types = request.task.get("reflection_types")
        
        if not agent_id or not task_result:
            return {"error": "Missing agent_id or task_result"}
        
        result = await self.reflection_system.reflect_on_task(agent_id, task_result, reflection_types)
        
        return {
            "reflection_result": {
                "agent_id": result.agent_id,
                "timestamp": result.timestamp.isoformat(),
                "confidence_score": result.confidence_score,
                "performance_analysis": result.performance_analysis,
                "self_critique": result.self_critique,
                "improvement_suggestions": result.improvement_suggestions,
                "learning_insights": result.learning_insights,
                "action_items": result.action_items
            }
        }
    
    async def _get_reflection_summary(self, request: AgentRequest) -> Dict[str, Any]:
        """Handle get reflection summary request."""
        agent_id = request.task.get("agent_id")
        
        if not agent_id:
            return {"error": "Missing agent_id"}
        
        summary = await self.reflection_system.get_reflection_summary(agent_id)
        return {"reflection_summary": summary}
    
    async def _get_system_stats(self, request: AgentRequest) -> Dict[str, Any]:
        """Handle get system stats request."""
        stats = await self.reflection_system.get_system_reflection_stats()
        return {"system_stats": stats}