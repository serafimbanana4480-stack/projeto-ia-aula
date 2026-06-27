"""Meta-Cognition Engine — Advanced thinking pattern analysis and optimization.

This module provides sophisticated meta-cognitive capabilities for agents:
- Thinking pattern recognition and analysis
- Cognitive process optimization
- Decision quality assessment
- Learning strategy adaptation
- Mental model development
"""

from __future__ import annotations

import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
import numpy as np

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.knowledge.memory import MemorySystem
from backend.observability.event_bus import EventBus
from backend.observability.events import Event

logger = logging.getLogger(__name__)


class ThinkingPattern(Enum):
    """Types of thinking patterns agents can exhibit."""
    SEQUENTIAL = "sequential"           # Step-by-step linear thinking
    PARALLEL = "parallel"              # Multiple simultaneous thoughts
    DIVERGENT = "divergent"            # Exploring multiple possibilities
    CONVERGENT = "convergent"          # Focusing on single solution
    ANALYTICAL = "analytical"          # Breaking down into components
    SYNTHETIC = "synthetic"            # Combining different ideas
    CRITICAL = "critical"              # Evaluating and judging
    CREATIVE = "creative"              # Generating novel ideas
    SYSTEMIC = "systemic"              # Understanding systems and relationships
    METACOGNITIVE = "metacognitive"    # Thinking about thinking


class CognitiveStrategy(Enum):
    """Cognitive strategies for problem solving."""
    PROBLEM_DECOMPOSITION = "problem_decomposition"
    HYPOTHESIS_GENERATION = "hypothesis_generation"
    ANALOGICAL_REASONING = "analogical_reasoning"
    CASE_BASED_REASONING = "case_based_reasoning"
    ABSTRACT_REASONING = "abstract_reasoning"
    CONCRETE_REASONING = "concrete_reasoning"
    INDUCTIVE_REASONING = "inductive_reasoning"
    DEDUCTIVE_REASONING = "deductive_reasoning"
    HEURISTIC_SEARCH = "heuristic_search"
    ALGORITHMIC_APPROACH = "algorithmic_approach"


@dataclass
class ThinkingProcess:
    """Represents a thinking process with its characteristics."""
    process_id: str
    pattern: ThinkingPattern
    strategy: CognitiveStrategy
    start_time: datetime
    end_time: Optional[datetime]
    steps: List[Dict[str, Any]]
    decisions: List[Dict[str, Any]]
    outcomes: List[Dict[str, Any]]
    effectiveness_score: float
    confidence_level: float
    context_factors: List[str]
    mental_models: List[str]


@dataclass
class CognitiveInsight:
    """Insight about cognitive processes."""
    insight_type: str
    description: str
    confidence: float
    evidence: List[str]
    implications: List[str]
    recommendations: List[str]


@dataclass
class MentalModel:
    """Represents a mental model used by the agent."""
    model_id: str
    name: str
    description: str
    domain: str
    accuracy_score: float
    applicability_domains: List[str]
    last_updated: datetime
    usage_count: int
    success_rate: float


class ThinkingPatternAnalyzer:
    """Analyzes and classifies thinking patterns."""
    
    def __init__(self, memory_system: MemorySystem, event_bus: EventBus):
        self.memory_system = memory_system
        self.event_bus = event_bus
        self.pattern_history = {}
        self.pattern_effectiveness = {}
    
    async def analyze_thinking_process(self, agent_id: str, 
                                     process_data: Dict[str, Any]) -> ThinkingProcess:
        """Analyze a thinking process and extract patterns."""
        
        # Extract process characteristics
        steps = process_data.get("steps", [])
        decisions = process_data.get("decisions", [])
        outcomes = process_data.get("outcomes", [])
        start_time = datetime.fromisoformat(process_data.get("start_time", datetime.now().isoformat()))
        end_time = datetime.fromisoformat(process_data.get("end_time", datetime.now().isoformat()))
        
        # Identify thinking pattern
        pattern = self._identify_thinking_pattern(steps, decisions)
        
        # Identify cognitive strategy
        strategy = self._identify_cognitive_strategy(steps, decisions)
        
        # Calculate effectiveness score
        effectiveness = self._calculate_effectiveness(decisions, outcomes)
        
        # Calculate confidence level
        confidence = self._calculate_confidence(steps, decisions, outcomes)
        
        # Extract context factors
        context_factors = self._extract_context_factors(process_data)
        
        # Identify mental models used
        mental_models = self._identify_mental_models(steps, decisions)
        
        # Create thinking process
        thinking_process = ThinkingProcess(
            process_id=process_data.get("process_id", f"process_{int(time.time())}"),
            pattern=pattern,
            strategy=strategy,
            start_time=start_time,
            end_time=end_time,
            steps=steps,
            decisions=decisions,
            outcomes=outcomes,
            effectiveness_score=effectiveness,
            confidence_level=confidence,
            context_factors=context_factors,
            mental_models=mental_models
        )
        
        # Store in history
        if agent_id not in self.pattern_history:
            self.pattern_history[agent_id] = []
        self.pattern_history[agent_id].append(thinking_process)
        
        # Update pattern effectiveness
        if pattern not in self.pattern_effectiveness:
            self.pattern_effectiveness[pattern] = []
        self.pattern_effectiveness[pattern].append(effectiveness)
        
        # Emit analysis event
        await self.event_bus.emit(Event(
            type="thinking_pattern_analyzed",
            data={
                "agent_id": agent_id,
                "pattern": pattern.value,
                "strategy": strategy.value,
                "effectiveness": effectiveness,
                "confidence": confidence
            }
        ))
        
        return thinking_process
    
    def _identify_thinking_pattern(self, steps: List[Dict[str, Any]], 
                                decisions: List[Dict[str, Any]]) -> ThinkingPattern:
        """Identify the primary thinking pattern from steps and decisions."""
        
        # Analyze step structure
        step_count = len(steps)
        parallel_steps = sum(1 for step in steps if step.get("parallel", False))
        
        # Analyze decision characteristics
        decision_count = len(decisions)
        divergent_decisions = sum(1 for d in decisions if d.get("type") == "exploration")
        convergent_decisions = sum(1 for d in decisions if d.get("type") == "selection")
        
        # Determine pattern based on characteristics
        if parallel_steps > step_count * 0.5:
            return ThinkingPattern.PARALLEL
        elif divergent_decisions > convergent_decisions:
            return ThinkingPattern.DIVERGENT
        elif convergent_decisions > divergent_decisions:
            return ThinkingPattern.CONVERGENT
        elif step_count > 10 and all(step.get("analytical", False) for step in steps[:3]):
            return ThinkingPattern.ANALYTICAL
        elif any(step.get("creative", False) for step in steps):
            return ThinkingPattern.CREATIVE
        elif any(step.get("systemic", False) for step in steps):
            return ThinkingPattern.SYSTEMIC
        else:
            return ThinkingPattern.SEQUENTIAL
    
    def _identify_cognitive_strategy(self, steps: List[Dict[str, Any]], 
                                   decisions: List[Dict[str, Any]]) -> CognitiveStrategy:
        """Identify the cognitive strategy used."""
        
        # Look for strategy indicators in steps and decisions
        strategy_indicators = {
            CognitiveStrategy.PROBLEM_DECOMPOSITION: ["decompose", "break down", "split"],
            CognitiveStrategy.HYPOTHESIS_GENERATION: ["hypothesis", "assume", "propose"],
            CognitiveStrategy.ANALOGICAL_REASONING: ["similar", "analogy", "compare"],
            CognitiveStrategy.CASE_BASED_REASONING: ["case", "example", "previous"],
            CognitiveStrategy.HEURISTIC_SEARCH: ["heuristic", "rule", "guideline"],
            CognitiveStrategy.ALGORITHMIC_APPROACH: ["algorithm", "procedure", "steps"]
        }
        
        # Count indicators
        indicator_counts = {}
        for strategy, indicators in strategy_indicators.items():
            count = 0
            for step in steps:
                text = step.get("description", "").lower()
                count += sum(1 for indicator in indicators if indicator in text)
            for decision in decisions:
                text = decision.get("reasoning", "").lower()
                count += sum(1 for indicator in indicators if indicator in text)
            indicator_counts[strategy] = count
        
        # Return strategy with most indicators
        if indicator_counts:
            return max(indicator_counts, key=indicator_counts.get)
        else:
            return CognitiveStrategy.HEURISTIC_SEARCH
    
    def _calculate_effectiveness(self, decisions: List[Dict[str, Any]], 
                              outcomes: List[Dict[str, Any]]) -> float:
        """Calculate effectiveness of the thinking process."""
        if not outcomes:
            return 0.0
        
        effectiveness_scores = []
        for i, outcome in enumerate(outcomes):
            success_score = outcome.get("success_score", 0.0)
            efficiency_score = outcome.get("efficiency_score", 0.0)
            quality_score = outcome.get("quality_score", 0.0)
            
            # Weighted average
            effectiveness = (success_score * 0.4 + efficiency_score * 0.3 + quality_score * 0.3)
            effectiveness_scores.append(effectiveness)
        
        return sum(effectiveness_scores) / len(effectiveness_scores)
    
    def _calculate_confidence(self, steps: List[Dict[str, Any]], 
                            decisions: List[Dict[str, Any]], 
                            outcomes: List[Dict[str, Any]]) -> float:
        """Calculate confidence in the thinking process analysis."""
        
        # Data completeness
        step_completeness = min(1.0, len(steps) / 5.0)  # Expect at least 5 steps
        decision_completeness = min(1.0, len(decisions) / 3.0)  # Expect at least 3 decisions
        outcome_completeness = min(1.0, len(outcomes) / len(decisions)) if decisions else 0.0
        
        # Data quality
        step_quality = sum(step.get("confidence", 0.5) for step in steps) / len(steps) if steps else 0.0
        decision_quality = sum(dec.get("confidence", 0.5) for dec in decisions) / len(decisions) if decisions else 0.0
        
        # Overall confidence
        confidence = (step_completeness * 0.2 + 
                     decision_completeness * 0.2 + 
                     outcome_completeness * 0.3 + 
                     step_quality * 0.15 + 
                     decision_quality * 0.15)
        
        return min(1.0, confidence)
    
    def _extract_context_factors(self, process_data: Dict[str, Any]) -> List[str]:
        """Extract context factors from process data."""
        context = process_data.get("context", {})
        
        factors = []
        
        # Task complexity
        complexity = context.get("complexity", "medium")
        factors.append(f"complexity_{complexity}")
        
        # Time pressure
        time_pressure = context.get("time_pressure", "normal")
        factors.append(f"time_pressure_{time_pressure}")
        
        # Resource constraints
        resources = context.get("resources", "sufficient")
        factors.append(f"resources_{resources}")
        
        # Domain
        domain = context.get("domain", "general")
        factors.append(f"domain_{domain}")
        
        # Collaboration
        collaboration = context.get("collaboration", "individual")
        factors.append(f"collaboration_{collaboration}")
        
        return factors
    
    def _identify_mental_models(self, steps: List[Dict[str, Any]], 
                             decisions: List[Dict[str, Any]]) -> List[str]:
        """Identify mental models used in the thinking process."""
        models = []
        
        # Look for model indicators
        model_indicators = {
            "system_model": ["system", "interconnected", "feedback"],
            "causal_model": ["cause", "effect", "because"],
            "procedural_model": ["procedure", "process", "steps"],
            "conceptual_model": ["concept", "idea", "framework"],
            "mathematical_model": ["calculate", "formula", "equation"],
            "spatial_model": ["space", "location", "position"]
        }
        
        for model, indicators in model_indicators.items():
            found = False
            for step in steps:
                text = step.get("description", "").lower()
                if any(indicator in text for indicator in indicators):
                    models.append(model)
                    found = True
                    break
            if not found:
                for decision in decisions:
                    text = decision.get("reasoning", "").lower()
                    if any(indicator in text for indicator in indicators):
                        models.append(model)
                        break
        
        return models


class CognitiveOptimizer:
    """Optimizes cognitive processes based on analysis results."""
    
    def __init__(self, memory_system: MemorySystem, event_bus: EventBus):
        self.memory_system = memory_system
        self.event_bus = event_bus
        self.optimization_history = {}
        self.optimization_strategies = {}
    
    async def optimize_thinking_process(self, agent_id: str, 
                                      thinking_process: ThinkingProcess) -> List[CognitiveInsight]:
        """Generate optimization insights for a thinking process."""
        
        insights = []
        
        # Analyze pattern effectiveness
        pattern_insights = await self._analyze_pattern_effectiveness(thinking_process)
        insights.extend(pattern_insights)
        
        # Analyze strategy effectiveness
        strategy_insights = await self._analyze_strategy_effectiveness(thinking_process)
        insights.extend(strategy_insights)
        
        # Analyze mental model usage
        model_insights = await self._analyze_mental_models(thinking_process)
        insights.extend(model_insights)
        
        # Analyze context factors
        context_insights = await self._analyze_context_factors(thinking_process)
        insights.extend(context_insights)
        
        # Store optimization insights
        if agent_id not in self.optimization_history:
            self.optimization_history[agent_id] = []
        self.optimization_history[agent_id].extend(insights)
        
        # Emit optimization event
        await self.event_bus.emit(Event(
            type="cognitive_optimization_generated",
            data={
                "agent_id": agent_id,
                "insights_count": len(insights),
                "pattern": thinking_process.pattern.value,
                "effectiveness": thinking_process.effectiveness_score
            }
        ))
        
        return insights
    
    async def _analyze_pattern_effectiveness(self, thinking_process: ThinkingProcess) -> List[CognitiveInsight]:
        """Analyze the effectiveness of the thinking pattern."""
        insights = []
        
        pattern = thinking_process.pattern
        effectiveness = thinking_process.effectiveness_score
        
        # Generate insight based on effectiveness
        if effectiveness < 0.5:
            insight = CognitiveInsight(
                insight_type="pattern_ineffectiveness",
                description=f"The {pattern.value} thinking pattern shows low effectiveness ({effectiveness:.2f})",
                confidence=0.8,
                evidence=[f"Effectiveness score: {effectiveness:.2f}"],
                implications=["May need to consider alternative patterns", "Current approach may not be suitable for this task type"],
                recommendations=[f"Consider switching to {self._suggest_alternative_pattern(pattern)} pattern", 
                              "Analyze task requirements more carefully"]
            )
            insights.append(insight)
        elif effectiveness > 0.8:
            insight = CognitiveInsight(
                insight_type="pattern_excellence",
                description=f"The {pattern.value} thinking pattern shows excellent effectiveness ({effectiveness:.2f})",
                confidence=0.9,
                evidence=[f"Effectiveness score: {effectiveness:.2f}"],
                implications=["Pattern is well-suited for this type of task", "Should be reused for similar tasks"],
                recommendations=[f"Continue using {pattern.value} pattern for similar tasks", 
                              "Document successful applications of this pattern"]
            )
            insights.append(insight)
        
        return insights
    
    async def _analyze_strategy_effectiveness(self, thinking_process: ThinkingProcess) -> List[CognitiveInsight]:
        """Analyze the effectiveness of the cognitive strategy."""
        insights = []
        
        strategy = thinking_process.strategy
        effectiveness = thinking_process.effectiveness_score
        
        # Strategy-specific analysis
        if strategy == CognitiveStrategy.HEURISTIC_SEARCH and effectiveness < 0.6:
            insight = CognitiveInsight(
                insight_type="heuristic_ineffectiveness",
                description="Heuristic search strategy is not performing well",
                confidence=0.7,
                evidence=[f"Effectiveness score: {effectiveness:.2f}"],
                implications=["Current heuristics may be inappropriate", "May need more systematic approach"],
                recommendations=["Consider algorithmic approach", "Review and update heuristics"]
            )
            insights.append(insight)
        
        return insights
    
    async def _analyze_mental_models(self, thinking_process: ThinkingProcess) -> List[CognitiveInsight]:
        """Analyze the usage of mental models."""
        insights = []
        
        models = thinking_process.mental_models
        
        if not models:
            insight = CognitiveInsight(
                insight_type="missing_mental_models",
                description="No clear mental models identified in thinking process",
                confidence=0.6,
                evidence=["No mental model indicators found"],
                implications=["Lack of structured thinking framework", "May lead to inconsistent approaches"],
                recommendations=["Develop explicit mental models", "Use established frameworks and models"]
            )
            insights.append(insight)
        elif len(models) == 1:
            insight = CognitiveInsight(
                insight_type="limited_mental_models",
                description="Only one mental model used in thinking process",
                confidence=0.5,
                evidence=[f"Single model: {models[0]}"],
                implications=["May benefit from multiple perspectives", "Limited cognitive flexibility"],
                recommendations=["Consider multiple mental models", "Develop model-switching capabilities"]
            )
            insights.append(insight)
        
        return insights
    
    async def _analyze_context_factors(self, thinking_process: ThinkingProcess) -> List[CognitiveInsight]:
        """Analyze the impact of context factors."""
        insights = []
        
        context_factors = thinking_process.context_factors
        
        # Analyze time pressure impact
        if "time_pressure_high" in context_factors:
            if thinking_process.effectiveness_score < 0.6:
                insight = CognitiveInsight(
                    insight_type="time_pressure_impact",
                    description="High time pressure may be negatively affecting performance",
                    confidence=0.7,
                    evidence=["High time pressure context", "Low effectiveness score"],
                    implications=["Time pressure reduces thinking quality", "May need better time management"],
                    recommendations=["Allocate more time for complex tasks", "Develop faster thinking strategies"]
                )
                insights.append(insight)
        
        # Analyze resource constraints
        if "resources_limited" in context_factors:
            insight = CognitiveInsight(
                insight_type="resource_constraints",
                description="Limited resources may be constraining thinking process",
                confidence=0.6,
                evidence=["Limited resources context"],
                implications=["Resource constraints affect decision quality", "May need resource optimization"],
                recommendations=["Request additional resources", "Optimize resource usage"]
            )
            insights.append(insight)
        
        return insights
    
    def _suggest_alternative_pattern(self, current_pattern: ThinkingPattern) -> str:
        """Suggest an alternative thinking pattern."""
        alternatives = {
            ThinkingPattern.SEQUENTIAL: ThinkingPattern.PARALLEL,
            ThinkingPattern.PARALLEL: ThinkingPattern.CONVERGENT,
            ThinkingPattern.DIVERGENT: ThinkingPattern.CONVERGENT,
            ThinkingPattern.CONVERGENT: ThinkingPattern.DIVERGENT,
            ThinkingPattern.ANALYTICAL: ThinkingPattern.SYNTHETIC,
            ThinkingPattern.SYNTHETIC: ThinkingPattern.ANALYTICAL,
            ThinkingPattern.CRITICAL: ThinkingPattern.CREATIVE,
            ThinkingPattern.CREATIVE: ThinkingPattern.CRITICAL,
            ThinkingPattern.SYSTEMIC: ThinkingPattern.ANALYTICAL
        }
        return alternatives.get(current_pattern, ThinkingPattern.SEQUENTIAL).value


class MentalModelManager:
    """Manages mental models used by agents."""
    
    def __init__(self, memory_system: MemorySystem, event_bus: EventBus):
        self.memory_system = memory_system
        self.event_bus = event_bus
        self.mental_models = {}
        self.model_usage = {}
    
    async def register_mental_model(self, agent_id: str, model: MentalModel) -> None:
        """Register a mental model for an agent."""
        if agent_id not in self.mental_models:
            self.mental_models[agent_id] = {}
        
        self.mental_models[agent_id][model.model_id] = model
        
        # Track usage
        if model.model_id not in self.model_usage:
            self.model_usage[model.model_id] = []
        self.model_usage[model.model_id].append({
            "agent_id": agent_id,
            "timestamp": datetime.now(),
            "success": model.success_rate
        })
        
        # Emit registration event
        await self.event_bus.emit(Event(
            type="mental_model_registered",
            data={
                "agent_id": agent_id,
                "model_id": model.model_id,
                "model_name": model.name,
                "accuracy": model.accuracy_score
            }
        ))
    
    async def update_model_performance(self, agent_id: str, model_id: str, 
                                     success: bool, context: Dict[str, Any]) -> None:
        """Update mental model performance based on usage."""
        if agent_id not in self.mental_models or model_id not in self.mental_models[agent_id]:
            return
        
        model = self.mental_models[agent_id][model_id]
        
        # Update usage count
        model.usage_count += 1
        
        # Update success rate (moving average)
        if success:
            model.success_rate = (model.success_rate * (model.usage_count - 1) + 1.0) / model.usage_count
        else:
            model.success_rate = (model.success_rate * (model.usage_count - 1) + 0.0) / model.usage_count
        
        # Update last modified
        model.last_updated = datetime.now()
        
        # Emit update event
        await self.event_bus.emit(Event(
            type="mental_model_updated",
            data={
                "agent_id": agent_id,
                "model_id": model_id,
                "new_success_rate": model.success_rate,
                "usage_count": model.usage_count
            }
        ))
    
    async def get_recommended_models(self, agent_id: str, task_context: Dict[str, Any]) -> List[MentalModel]:
        """Get recommended mental models for a task context."""
        if agent_id not in self.mental_models:
            return []
        
        # Get all models for the agent
        models = list(self.mental_models[agent_id].values())
        
        # Filter by applicability
        domain = task_context.get("domain", "general")
        applicable_models = [
            model for model in models 
            if domain in model.applicability_domains or "general" in model.applicability_domains
        ]
        
        # Sort by success rate and accuracy
        applicable_models.sort(
            key=lambda m: (m.success_rate * 0.6 + m.accuracy_score * 0.4), 
            reverse=True
        )
        
        return applicable_models[:5]  # Return top 5


class MetaCognitionEngine:
    """Main meta-cognition engine coordinating all cognitive components."""
    
    def __init__(self, memory_system: MemorySystem, event_bus: EventBus):
        self.memory_system = memory_system
        self.event_bus = event_bus
        self.pattern_analyzer = ThinkingPatternAnalyzer(memory_system, event_bus)
        self.cognitive_optimizer = CognitiveOptimizer(memory_system, event_bus)
        self.mental_model_manager = MentalModelManager(memory_system, event_bus)
        self.meta_cognition_history = {}
    
    async def analyze_cognitive_process(self, agent_id: str, 
                                      process_data: Dict[str, Any]) -> Dict[str, Any]:
        """Perform comprehensive meta-cognitive analysis."""
        
        # Analyze thinking process
        thinking_process = await self.pattern_analyzer.analyze_thinking_process(agent_id, process_data)
        
        # Generate optimization insights
        optimization_insights = await self.cognitive_optimizer.optimize_thinking_process(
            agent_id, thinking_process
        )
        
        # Register mental models if identified
        for model_name in thinking_process.mental_models:
            model = MentalModel(
                model_id=f"{agent_id}_{model_name}_{int(time.time())}",
                name=model_name,
                description=f"Mental model for {model_name}",
                domain=process_data.get("context", {}).get("domain", "general"),
                accuracy_score=thinking_process.effectiveness_score,
                applicability_domains=[process_data.get("context", {}).get("domain", "general")],
                last_updated=datetime.now(),
                usage_count=1,
                success_rate=thinking_process.effectiveness_score
            )
            await self.mental_model_manager.register_mental_model(agent_id, model)
        
        # Store analysis result
        analysis_result = {
            "agent_id": agent_id,
            "thinking_process": {
                "process_id": thinking_process.process_id,
                "pattern": thinking_process.pattern.value,
                "strategy": thinking_process.strategy.value,
                "effectiveness_score": thinking_process.effectiveness_score,
                "confidence_level": thinking_process.confidence_level,
                "context_factors": thinking_process.context_factors,
                "mental_models": thinking_process.mental_models
            },
            "optimization_insights": [
                {
                    "type": insight.insight_type,
                    "description": insight.description,
                    "confidence": insight.confidence,
                    "recommendations": insight.recommendations
                }
                for insight in optimization_insights
            ],
            "timestamp": datetime.now().isoformat()
        }
        
        # Store in history
        if agent_id not in self.meta_cognition_history:
            self.meta_cognition_history[agent_id] = []
        self.meta_cognition_history[agent_id].append(analysis_result)
        
        # Emit analysis completed event
        await self.event_bus.emit(Event(
            type="meta_cognition_completed",
            data={
                "agent_id": agent_id,
                "pattern": thinking_process.pattern.value,
                "effectiveness": thinking_process.effectiveness_score,
                "insights_count": len(optimization_insights)
            }
        ))
        
        return analysis_result
    
    async def get_cognitive_profile(self, agent_id: str) -> Dict[str, Any]:
        """Get comprehensive cognitive profile for an agent."""
        if agent_id not in self.meta_cognition_history:
            return {"error": "No meta-cognition history found for agent"}
        
        history = self.meta_cognition_history[agent_id]
        
        # Analyze pattern preferences
        pattern_counts = {}
        pattern_effectiveness = {}
        
        for analysis in history:
            pattern = analysis["thinking_process"]["pattern"]
            effectiveness = analysis["thinking_process"]["effectiveness_score"]
            
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
            if pattern not in pattern_effectiveness:
                pattern_effectiveness[pattern] = []
            pattern_effectiveness[pattern].append(effectiveness)
        
        # Calculate average effectiveness per pattern
        pattern_avg_effectiveness = {
            pattern: sum(scores) / len(scores)
            for pattern, scores in pattern_effectiveness.items()
        }
        
        # Get mental models
        mental_models = []
        if agent_id in self.mental_model_manager.mental_models:
            mental_models = [
                {
                    "model_id": model.model_id,
                    "name": model.name,
                    "accuracy": model.accuracy_score,
                    "success_rate": model.success_rate,
                    "usage_count": model.usage_count
                }
                for model in self.mental_model_manager.mental_models[agent_id].values()
            ]
        
        return {
            "agent_id": agent_id,
            "total_analyses": len(history),
            "pattern_preferences": pattern_counts,
            "pattern_effectiveness": pattern_avg_effectiveness,
            "mental_models": mental_models,
            "last_analysis": history[-1]["timestamp"] if history else None
        }


# Import time for timestamp generation
import time