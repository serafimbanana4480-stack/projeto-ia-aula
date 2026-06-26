"""Federated Learning — Collaborative learning system for multi-agent environments.

This module provides:
- Federated learning orchestration
- Privacy-preserving model training
- Distributed model aggregation
- Secure model sharing
- Learning coordination across agents
- Performance tracking and validation
"""

from __future__ import annotations

import asyncio
import logging
import json
import pickle
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
import uuid
import numpy as np
from collections import defaultdict
import statistics

from backend.observability.event_bus import EventBus
from backend.observability.events import Event

logger = logging.getLogger(__name__)


class FederatedLearningType(Enum):
    """Types of federated learning approaches."""
    FEDERATED_AVERAGING = "federated_averaging"           # Standard FedAvg
    FEDERATED_PROXIMAL = "federated_proximal"           # FedProx for regularization
    FEDERATED_ENSEMBLE = "federated_ensemble"           # Ensemble-based approach
    HIERARCHICAL = "hierarchical"                       # Hierarchical federated learning
    PEER_TO_PEER = "peer_to_peer"                       # Peer-to-peer learning
    ADAPTIVE = "adaptive"                               # Adaptive federated learning


class PrivacyLevel(Enum):
    """Privacy protection levels."""
    NONE = "none"                    # No privacy protection
    DIFFERENTIAL = "differential"    # Differential privacy
    HOMOMORPHIC = "homomorphic"     # Homomorphic encryption
    SECURE_AGGREGATION = "secure"   # Secure multi-party computation
    MIXNET = "mixnet"               # Mixnet for anonymity


class ModelType(Enum):
    """Types of models that can be federated."""
    NEURAL_NETWORK = "neural_network"
    LINEAR_MODEL = "linear_model"
    DECISION_TREE = "decision_tree"
    ENSEMBLE = "ensemble"
    CUSTOM = "custom"


@dataclass
class FederatedModel:
    """Represents a federated learning model."""
    model_id: str
    name: str
    model_type: ModelType
    version: int
    architecture: Dict[str, Any]
    parameters: Dict[str, Any]
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    performance_metrics: Dict[str, float]
    privacy_level: PrivacyLevel
    participating_agents: List[str]
    global_performance: float = 0.0


@dataclass
class LocalModelUpdate:
    """Represents a local model update from an agent."""
    update_id: str
    agent_id: str
    model_id: str
    round_number: int
    local_parameters: Dict[str, Any]
    local_performance: Dict[str, float]
    training_samples: int
    update_timestamp: datetime
    privacy_noise: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FederatedRound:
    """Represents a round of federated learning."""
    round_id: str
    model_id: str
    round_number: int
    start_time: datetime
    end_time: Optional[datetime]
    participating_agents: List[str]
    updates_received: List[str]
    global_parameters: Dict[str, Any]
    global_performance: Dict[str, float]
    convergence_metrics: Dict[str, float]
    privacy_metrics: Dict[str, float]
    status: str


@dataclass
class LearningAggregation:
    """Represents model aggregation strategy."""
    aggregation_id: str
    name: str
    aggregation_type: FederatedLearningType
    weighting_strategy: str
    privacy_preservation: PrivacyLevel
    convergence_threshold: float
    min_participants: int
    max_rounds: int
    configuration: Dict[str, Any]


class FederatedLearningOrchestrator:
    """Orchestrates federated learning across multiple agents."""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        
        # Models and rounds
        self.federated_models: Dict[str, FederatedModel] = {}
        self.active_rounds: Dict[str, FederatedRound] = {}
        self.round_history: List[FederatedRound] = []
        
        # Local updates
        self.local_updates: Dict[str, LocalModelUpdate] = {}
        self.pending_updates: Dict[str, List[str]] = defaultdict(list)
        
        # Aggregation strategies
        self.aggregation_strategies: Dict[str, LearningAggregation] = {}
        
        # Agent participation
        self.agent_participation: Dict[str, Dict[str, Any]] = {}
        self.agent_reputation: Dict[str, float] = {}
        
        # Privacy and security
        self.privacy_configs: Dict[str, Dict[str, Any]] = {}
        
        # Performance tracking
        self.learning_metrics: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        
        # Initialize default aggregation strategies
        self._initialize_aggregation_strategies()
        
        # Start background tasks
        self._round_monitoring_task = asyncio.create_task(self._monitor_rounds())
        self._privacy_protection_task = asyncio.create_task(self._apply_privacy_protection())
    
    def _initialize_aggregation_strategies(self) -> None:
        """Initialize default aggregation strategies."""
        
        self.aggregation_strategies = {
            "fedavg": LearningAggregation(
                aggregation_id="fedavg",
                name="Federated Averaging",
                aggregation_type=FederatedLearningType.FEDERATED_AVERAGING,
                weighting_strategy="uniform",
                privacy_preservation=PrivacyLevel.NONE,
                convergence_threshold=0.001,
                min_participants=2,
                max_rounds=100,
                configuration={"learning_rate": 0.01, "momentum": 0.9}
            ),
            "fedprox": LearningAggregation(
                aggregation_id="fedprox",
                name="Federated Proximal",
                aggregation_type=FederatedLearningType.FEDERATED_PROXIMAL,
                weighting_strategy="uniform",
                privacy_preservation=PrivacyLevel.DIFFERENTIAL,
                convergence_threshold=0.001,
                min_participants=2,
                max_rounds=100,
                configuration={"learning_rate": 0.01, "mu": 0.01, "epsilon": 1.0}
            ),
            "fedensemble": LearningAggregation(
                aggregation_id="fedensemble",
                name="Federated Ensemble",
                aggregation_type=FederatedLearningType.FEDERATED_ENSEMBLE,
                weighting_strategy="performance_based",
                privacy_preservation=PrivacyLevel.SECURE_AGGREGATION,
                convergence_threshold=0.005,
                min_participants=3,
                max_rounds=50,
                configuration={"ensemble_size": 5, "voting_strategy": "weighted"}
            ),
            "adaptive": LearningAggregation(
                aggregation_id="adaptive",
                name="Adaptive Federated Learning",
                aggregation_type=FederatedLearningType.ADAPTIVE,
                weighting_strategy="adaptive",
                privacy_preservation=PrivacyLevel.DIFFERENTIAL,
                convergence_threshold=0.001,
                min_participants=2,
                max_rounds=100,
                configuration={"adaptation_rate": 0.1, "performance_threshold": 0.7}
            )
        }
    
    async def create_federated_model(self, name: str, model_type: ModelType,
                                   architecture: Dict[str, Any],
                                   initial_parameters: Dict[str, Any],
                                   privacy_level: PrivacyLevel = PrivacyLevel.DIFFERENTIAL,
                                   aggregation_strategy: str = "fedavg") -> str:
        """Create a new federated learning model."""
        
        model_id = str(uuid.uuid4())
        
        # Create federated model
        model = FederatedModel(
            model_id=model_id,
            name=name,
            model_type=model_type,
            version=1,
            architecture=architecture,
            parameters=initial_parameters,
            metadata={
                "aggregation_strategy": aggregation_strategy,
                "created_by": "federated_learning_orchestrator"
            },
            created_at=datetime.now(),
            updated_at=datetime.now(),
            performance_metrics={},
            privacy_level=privacy_level,
            participating_agents=[]
        )
        
        # Store model
        self.federated_models[model_id] = model
        
        # Initialize privacy configuration
        self.privacy_configs[model_id] = self._create_privacy_config(privacy_level)
        
        # Emit model creation event
        await self.event_bus.emit(Event(
            type="federated_model_created",
            data={
                "model_id": model_id,
                "name": name,
                "model_type": model_type.value,
                "privacy_level": privacy_level.value,
                "aggregation_strategy": aggregation_strategy
            }
        ))
        
        logger.info(f"Federated model created: {model_id} ({name})")
        
        return model_id
    
    async def start_learning_round(self, model_id: str, 
                                 participating_agents: List[str],
                                 min_updates: int = None) -> str:
        """Start a new federated learning round."""
        
        if model_id not in self.federated_models:
            raise ValueError(f"Model not found: {model_id}")
        
        model = self.federated_models[model_id]
        
        # Get current round number
        current_round = len([r for r in self.round_history if r.model_id == model_id])
        
        # Create round
        round_id = str(uuid.uuid4())
        round_number = current_round + 1
        
        federated_round = FederatedRound(
            round_id=round_id,
            model_id=model_id,
            round_number=round_number,
            start_time=datetime.now(),
            end_time=None,
            participating_agents=participating_agents,
            updates_received=[],
            global_parameters=model.parameters.copy(),
            global_performance={},
            convergence_metrics={},
            privacy_metrics={},
            status="active"
        )
        
        # Store round
        self.active_rounds[round_id] = federated_round
        
        # Update model participants
        model.participating_agents = participating_agents
        
        # Initialize pending updates
        self.pending_updates[round_id] = []
        
        # Set minimum updates
        if min_updates is None:
            strategy = self.aggregation_strategies[model.metadata.get("aggregation_strategy", "fedavg")]
            min_updates = strategy.min_participants
        
        # Emit round start event
        await self.event_bus.emit(Event(
            type="federated_round_started",
            data={
                "round_id": round_id,
                "model_id": model_id,
                "round_number": round_number,
                "participating_agents": participating_agents,
                "min_updates": min_updates
            }
        ))
        
        logger.info(f"Federated learning round started: {round_id} (Round {round_number})")
        
        return round_id
    
    async def submit_local_update(self, agent_id: str, round_id: str,
                                local_parameters: Dict[str, Any],
                                local_performance: Dict[str, Any],
                                training_samples: int) -> str:
        """Submit a local model update."""
        
        if round_id not in self.active_rounds:
            raise ValueError(f"Round not found: {round_id}")
        
        round_info = self.active_rounds[round_id]
        
        # Validate agent participation
        if agent_id not in round_info.participating_agents:
            raise ValueError(f"Agent not participating in round: {agent_id}")
        
        # Apply privacy protection
        privacy_config = self.privacy_configs[round_info.model_id]
        protected_parameters = await self._apply_privacy_to_parameters(
            local_parameters, privacy_config
        )
        
        # Create local update
        update_id = str(uuid.uuid4())
        local_update = LocalModelUpdate(
            update_id=update_id,
            agent_id=agent_id,
            model_id=round_info.model_id,
            round_number=round_info.round_number,
            local_parameters=protected_parameters,
            local_performance=local_performance,
            training_samples=training_samples,
            update_timestamp=datetime.now(),
            privacy_noise=privacy_config.get("noise_applied", {}),
            metadata={
                "privacy_level": privacy_config["level"].value,
                "protection_applied": True
            }
        )
        
        # Store update
        self.local_updates[update_id] = local_update
        self.pending_updates[round_id].append(update_id)
        round_info.updates_received.append(update_id)
        
        # Update agent participation
        if agent_id not in self.agent_participation:
            self.agent_participation[agent_id] = {
                "total_updates": 0,
                "models_participated": [],
                "reputation": 0.5,
                "last_update": None
            }
        
        self.agent_participation[agent_id]["total_updates"] += 1
        self.agent_participation[agent_id]["last_update"] = datetime.now()
        
        if round_info.model_id not in self.agent_participation[agent_id]["models_participated"]:
            self.agent_participation[agent_id]["models_participated"].append(round_info.model_id)
        
        # Check if round should be aggregated
        strategy = self.aggregation_strategies[self.federated_models[round_info.model_id].metadata.get("aggregation_strategy", "fedavg")]
        
        if len(self.pending_updates[round_id]) >= strategy.min_participants:
            await self._aggregate_round_updates(round_id)
        
        # Emit update submission event
        await self.event_bus.emit(Event(
            type="local_update_submitted",
            data={
                "update_id": update_id,
                "agent_id": agent_id,
                "round_id": round_id,
                "training_samples": training_samples,
                "performance": local_performance
            }
        ))
        
        logger.info(f"Local update submitted: {update_id} from agent {agent_id}")
        
        return update_id
    
    async def _aggregate_round_updates(self, round_id: str) -> None:
        """Aggregate updates from a federated learning round."""
        
        if round_id not in self.active_rounds:
            return
        
        round_info = self.active_rounds[round_id]
        model = self.federated_models[round_info.model_id]
        
        # Get updates
        update_ids = self.pending_updates[round_id]
        updates = [self.local_updates[uid] for uid in update_ids]
        
        if not updates:
            return
        
        # Get aggregation strategy
        strategy_name = model.metadata.get("aggregation_strategy", "fedavg")
        strategy = self.aggregation_strategies[strategy_name]
        
        # Aggregate parameters
        aggregated_parameters = await self._aggregate_parameters(
            updates, strategy
        )
        
        # Update global parameters
        model.parameters = aggregated_parameters
        model.updated_at = datetime.now()
        
        # Calculate global performance
        global_performance = self._calculate_global_performance(updates)
        model.global_performance = global_performance.get("accuracy", 0.0)
        
        # Update round
        round_info.global_parameters = aggregated_parameters
        round_info.global_performance = global_performance
        round_info.end_time = datetime.now()
        round_info.status = "completed"
        
        # Calculate convergence metrics
        round_info.convergence_metrics = self._calculate_convergence_metrics(
            round_info, updates
        )
        
        # Calculate privacy metrics
        round_info.privacy_metrics = self._calculate_privacy_metrics(
            round_info, updates
        )
        
        # Move to history
        self.round_history.append(round_info)
        del self.active_rounds[round_id]
        del self.pending_updates[round_id]
        
        # Update learning metrics
        self.learning_metrics[round_info.model_id].append({
            "round_number": round_info.round_number,
            "global_performance": global_performance,
            "convergence_metrics": round_info.convergence_metrics,
            "privacy_metrics": round_info.privacy_metrics,
            "participating_agents": len(round_info.participating_agents),
            "timestamp": round_info.end_time
        })
        
        # Update agent reputation
        await self._update_agent_reputation(updates)
        
        # Check convergence
        if self._check_convergence(round_info.model_id, strategy):
            await self._finalize_learning(round_info.model_id)
        else:
            # Start next round
            await self.start_learning_round(
                round_info.model_id,
                round_info.participating_agents
            )
        
        # Emit aggregation event
        await self.event_bus.emit(Event(
            type="round_aggregated",
            data={
                "round_id": round_id,
                "model_id": round_info.model_id,
                "round_number": round_info.round_number,
                "global_performance": global_performance,
                "converged": self._check_convergence(round_info.model_id, strategy)
            }
        ))
        
        logger.info(f"Round aggregated: {round_id} (Round {round_info.round_number})")
    
    async def _aggregate_parameters(self, updates: List[LocalModelUpdate],
                                  strategy: LearningAggregation) -> Dict[str, Any]:
        """Aggregate parameters from local updates."""
        
        if strategy.aggregation_type == FederatedLearningType.FEDERATED_AVERAGING:
            return await self._federated_averaging(updates, strategy)
        elif strategy.aggregation_type == FederatedLearningType.FEDERATED_PROXIMAL:
            return await self._federated_proximal(updates, strategy)
        elif strategy.aggregation_type == FederatedLearningType.FEDERATED_ENSEMBLE:
            return await self._federated_ensemble(updates, strategy)
        elif strategy.aggregation_type == FederatedLearningType.ADAPTIVE:
            return await self._adaptive_federated(updates, strategy)
        else:
            # Default to FedAvg
            return await self._federated_averaging(updates, strategy)
    
    async def _federated_averaging(self, updates: List[LocalModelUpdate],
                                 strategy: LearningAggregation) -> Dict[str, Any]:
        """Federated averaging aggregation."""
        
        if not updates:
            return {}
        
        # Get all parameter keys
        all_keys = set()
        for update in updates:
            all_keys.update(update.local_parameters.keys())
        
        # Calculate weighted average
        aggregated_params = {}
        
        for key in all_keys:
            values = []
            weights = []
            
            for update in updates:
                if key in update.local_parameters:
                    value = update.local_parameters[key]
                    
                    # Convert to numpy array if needed
                    if isinstance(value, (list, tuple)):
                        value = np.array(value)
                    
                    values.append(value)
                    
                    # Weight by training samples or performance
                    if strategy.weighting_strategy == "uniform":
                        weights.append(1.0)
                    elif strategy.weighting_strategy == "sample_based":
                        weights.append(update.training_samples)
                    elif strategy.weighting_strategy == "performance_based":
                        accuracy = update.local_performance.get("accuracy", 0.5)
                        weights.append(accuracy)
            
            if values:
                # Weighted average
                weights = np.array(weights)
                weights = weights / np.sum(weights)  # Normalize
                
                if isinstance(values[0], np.ndarray):
                    # Array parameters
                    weighted_values = [w * v for w, v in zip(weights, values)]
                    aggregated_params[key] = np.sum(weighted_values, axis=0)
                else:
                    # Scalar parameters
                    aggregated_params[key] = np.sum(weights * np.array(values))
        
        # Convert numpy arrays back to lists for JSON serialization
        for key, value in aggregated_params.items():
            if isinstance(value, np.ndarray):
                aggregated_params[key] = value.tolist()
        
        return aggregated_params
    
    async def _federated_proximal(self, updates: List[LocalModelUpdate],
                               strategy: LearningAggregation) -> Dict[str, Any]:
        """Federated proximal aggregation with regularization."""
        
        # Start with FedAvg
        fedavg_params = await self._federated_averaging(updates, strategy)
        
        # Get previous global parameters
        if not self.round_history:
            return fedavg_params
        
        last_round = max((r for r in self.round_history if r.model_id == updates[0].model_id), 
                        key=lambda r: r.round_number)
        
        if not last_round:
            return fedavg_params
        
        # Apply proximal term
        mu = strategy.configuration.get("mu", 0.01)
        learning_rate = strategy.configuration.get("learning_rate", 0.01)
        
        proximal_params = {}
        for key in fedavg_params:
            if key in last_round.global_parameters:
                global_param = np.array(last_round.global_parameters[key])
                local_param = np.array(fedavg_params[key])
                
                # Proximal update: θ_global = θ_local - lr * μ * (θ_local - θ_global)
                proximal_term = learning_rate * mu * (local_param - global_param)
                proximal_params[key] = (local_param - proximal_term).tolist()
            else:
                proximal_params[key] = fedavg_params[key]
        
        return proximal_params
    
    async def _federated_ensemble(self, updates: List[LocalModelUpdate],
                                strategy: LearningAggregation) -> Dict[str, Any]:
        """Federated ensemble aggregation."""
        
        if not updates:
            return {}
        
        # Sort updates by performance
        performance_weights = []
        for update in updates:
            accuracy = update.local_performance.get("accuracy", 0.5)
            performance_weights.append(accuracy)
        
        # Normalize weights
        total_weight = sum(performance_weights)
        if total_weight > 0:
            performance_weights = [w / total_weight for w in performance_weights]
        else:
            performance_weights = [1.0 / len(updates)] * len(updates)
        
        # Select top performers
        ensemble_size = strategy.configuration.get("ensemble_size", 5)
        sorted_updates = sorted(zip(updates, performance_weights), 
                              key=lambda x: x[1], reverse=True)
        selected_updates = sorted_updates[:ensemble_size]
        
        # Weighted ensemble
        ensemble_params = {}
        for update, weight in selected_updates:
            for key, value in update.local_parameters.items():
                if key not in ensemble_params:
                    ensemble_params[key] = 0
                
                if isinstance(value, (list, tuple)):
                    value = np.array(value)
                
                if isinstance(value, np.ndarray):
                    if isinstance(ensemble_params[key], int):
                        ensemble_params[key] = np.zeros_like(value)
                    ensemble_params[key] += weight * value
                else:
                    ensemble_params[key] += weight * value
        
        # Convert numpy arrays to lists
        for key, value in ensemble_params.items():
            if isinstance(value, np.ndarray):
                ensemble_params[key] = value.tolist()
        
        return ensemble_params
    
    async def _adaptive_federated(self, updates: List[LocalModelUpdate],
                               strategy: LearningAggregation) -> Dict[str, Any]:
        """Adaptive federated learning aggregation."""
        
        # Start with FedAvg
        fedavg_params = await self._federated_averaging(updates, strategy)
        
        # Adapt based on agent performance and reputation
        adaptive_params = {}
        
        for key in fedavg_params:
            values = []
            adaptive_weights = []
            
            for update in updates:
                if key in update.local_parameters:
                    value = update.local_parameters[key]
                    values.append(value)
                    
                    # Adaptive weight based on performance and reputation
                    accuracy = update.local_performance.get("accuracy", 0.5)
                    reputation = self.agent_reputation.get(update.agent_id, 0.5)
                    
                    # Combine accuracy and reputation
                    adaptive_weight = 0.7 * accuracy + 0.3 * reputation
                    adaptive_weights.append(adaptive_weight)
            
            if values:
                # Normalize adaptive weights
                total_weight = sum(adaptive_weights)
                if total_weight > 0:
                    adaptive_weights = [w / total_weight for w in adaptive_weights]
                else:
                    adaptive_weights = [1.0 / len(values)] * len(values)
                
                # Weighted average
                if isinstance(values[0], np.ndarray):
                    weighted_values = [w * np.array(v) for w, v in zip(adaptive_weights, values)]
                    adaptive_params[key] = np.sum(weighted_values, axis=0).tolist()
                else:
                    adaptive_params[key] = sum(w * v for w, v in zip(adaptive_weights, values))
        
        return adaptive_params
    
    def _calculate_global_performance(self, updates: List[LocalModelUpdate]) -> Dict[str, float]:
        """Calculate global performance metrics."""
        
        if not updates:
            return {}
        
        # Aggregate performance metrics
        metrics = {}
        
        # Get all metric keys
        all_keys = set()
        for update in updates:
            all_keys.update(update.local_performance.keys())
        
        # Calculate weighted averages
        for key in all_keys:
            values = []
            weights = []
            
            for update in updates:
                if key in update.local_performance:
                    values.append(update.local_performance[key])
                    weights.append(update.training_samples)
            
            if values:
                weights = np.array(weights)
                weights = weights / np.sum(weights)
                metrics[key] = float(np.sum(weights * np.array(values)))
        
        return metrics
    
    def _calculate_convergence_metrics(self, round_info: FederatedRound,
                                     updates: List[LocalModelUpdate]) -> Dict[str, float]:
        """Calculate convergence metrics."""
        
        metrics = {}
        
        # Parameter change magnitude
        if len(self.round_history) > 0:
            last_round = max((r for r in self.round_history if r.model_id == round_info.model_id),
                           key=lambda r: r.round_number)
            
            if last_round:
                param_change = self._calculate_parameter_distance(
                    last_round.global_parameters,
                    round_info.global_parameters
                )
                metrics["parameter_change"] = param_change
        
        # Performance variance
        performances = [u.local_performance.get("accuracy", 0.5) for u in updates]
        if performances:
            metrics["performance_variance"] = statistics.variance(performances)
            metrics["performance_std"] = statistics.stdev(performances)
        
        # Participation rate
        metrics["participation_rate"] = len(updates) / len(round_info.participating_agents)
        
        return metrics
    
    def _calculate_privacy_metrics(self, round_info: FederatedRound,
                                updates: List[LocalModelUpdate]) -> Dict[str, float]:
        """Calculate privacy protection metrics."""
        
        metrics = {}
        
        # Privacy budget consumption
        privacy_budget_used = 0.0
        for update in updates:
            if update.privacy_noise:
                epsilon = update.privacy_noise.get("epsilon", 0.0)
                privacy_budget_used += epsilon
        
        metrics["privacy_budget_used"] = privacy_budget_used
        
        # Noise level
        noise_levels = []
        for update in updates:
            if update.privacy_noise:
                noise_scale = update.privacy_noise.get("scale", 0.0)
                noise_levels.append(noise_scale)
        
        if noise_levels:
            metrics["average_noise_level"] = statistics.mean(noise_levels)
            metrics["max_noise_level"] = max(noise_levels)
        
        return metrics
    
    async def _update_agent_reputation(self, updates: List[LocalModelUpdate]) -> None:
        """Update agent reputation based on contribution quality."""
        
        for update in updates:
            agent_id = update.agent_id
            
            # Calculate contribution score
            accuracy = update.local_performance.get("accuracy", 0.5)
            training_samples = update.training_samples
            
            # Reputation update with smoothing
            current_reputation = self.agent_reputation.get(agent_id, 0.5)
            contribution_score = 0.7 * accuracy + 0.3 * min(1.0, training_samples / 1000)
            
            # Exponential moving average
            alpha = 0.1  # Learning rate for reputation
            new_reputation = (1 - alpha) * current_reputation + alpha * contribution_score
            
            self.agent_reputation[agent_id] = new_reputation
    
    def _check_convergence(self, model_id: str, strategy: LearningAggregation) -> bool:
        """Check if the model has converged."""
        
        # Get recent rounds
        recent_rounds = [r for r in self.round_history[-5:] if r.model_id == model_id]
        
        if len(recent_rounds) < 3:
            return False
        
        # Check parameter change
        param_changes = []
        for i in range(1, len(recent_rounds)):
            change = self._calculate_parameter_distance(
                recent_rounds[i-1].global_parameters,
                recent_rounds[i].global_parameters
            )
            param_changes.append(change)
        
        # Check if changes are below threshold
        avg_change = statistics.mean(param_changes)
        return avg_change < strategy.convergence_threshold
    
    async def _finalize_learning(self, model_id: str) -> None:
        """Finalize federated learning for a model."""
        
        model = self.federated_models[model_id]
        
        # Update model status
        model.metadata["status"] = "converged"
        model.metadata["finalized_at"] = datetime.now().isoformat()
        
        # Calculate final metrics
        final_metrics = {
            "total_rounds": len(self.round_history),
            "final_performance": model.global_performance,
            "convergence_round": len(self.round_history),
            "participating_agents": len(model.participating_agents)
        }
        
        model.metadata["final_metrics"] = final_metrics
        
        # Emit finalization event
        await self.event_bus.emit(Event(
            type="federated_learning_finalized",
            data={
                "model_id": model_id,
                "final_metrics": final_metrics
            }
        ))
        
        logger.info(f"Federated learning finalized: {model_id}")
    
    def _calculate_parameter_distance(self, params1: Dict[str, Any], 
                                   params2: Dict[str, Any]) -> float:
        """Calculate distance between parameter sets."""
        
        all_keys = set(params1.keys()) | set(params2.keys())
        distances = []
        
        for key in all_keys:
            if key in params1 and key in params2:
                val1 = np.array(params1[key]) if isinstance(params1[key], (list, tuple)) else params1[key]
                val2 = np.array(params2[key]) if isinstance(params2[key], (list, tuple)) else params2[key]
                
                if isinstance(val1, np.ndarray) and isinstance(val2, np.ndarray):
                    distance = np.linalg.norm(val1 - val2)
                    distances.append(distance)
                else:
                    distance = abs(float(val1) - float(val2))
                    distances.append(distance)
        
        return statistics.mean(distances) if distances else 0.0
    
    def _create_privacy_config(self, privacy_level: PrivacyLevel) -> Dict[str, Any]:
        """Create privacy configuration for a model."""
        
        configs = {
            PrivacyLevel.NONE: {
                "level": privacy_level,
                "noise_applied": {},
                "encryption": False,
                "aggregation": "plain"
            },
            PrivacyLevel.DIFFERENTIAL: {
                "level": privacy_level,
                "noise_applied": {"epsilon": 1.0, "delta": 1e-5},
                "encryption": False,
                "aggregation": "plain"
            },
            PrivacyLevel.HOMOMORPHIC: {
                "level": privacy_level,
                "noise_applied": {},
                "encryption": True,
                "aggregation": "homomorphic"
            },
            PrivacyLevel.SECURE_AGGREGATION: {
                "level": privacy_level,
                "noise_applied": {"epsilon": 0.5},
                "encryption": True,
                "aggregation": "secure_multiparty"
            },
            PrivacyLevel.MIXNET: {
                "level": privacy_level,
                "noise_applied": {"epsilon": 2.0},
                "encryption": True,
                "aggregation": "anonymous"
            }
        }
        
        return configs.get(privacy_level, configs[PrivacyLevel.NONE])
    
    async def _apply_privacy_to_parameters(self, parameters: Dict[str, Any],
                                         privacy_config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply privacy protection to parameters."""
        
        protected_params = parameters.copy()
        
        if privacy_config["level"] == PrivacyLevel.DIFFERENTIAL:
            # Add differential privacy noise
            noise_config = privacy_config["noise_applied"]
            epsilon = noise_config.get("epsilon", 1.0)
            
            for key, value in protected_params.items():
                if isinstance(value, (list, tuple)):
                    value = np.array(value)
                
                if isinstance(value, np.ndarray):
                    # Laplace noise for differential privacy
                    sensitivity = 1.0  # L2 sensitivity
                    scale = sensitivity / epsilon
                    noise = np.random.laplace(0, scale, value.shape)
                    protected_params[key] = (value + noise).tolist()
                else:
                    # Scalar noise
                    sensitivity = 1.0
                    scale = sensitivity / epsilon
                    noise = np.random.laplace(0, scale)
                    protected_params[key] = float(value) + noise
        
        elif privacy_config["level"] == PrivacyLevel.HOMOMORPHIC:
            # Apply homomorphic encryption (simplified)
            for key, value in protected_params.items():
                if isinstance(value, (list, tuple)):
                    value = np.array(value)
                
                if isinstance(value, np.ndarray):
                    # Simple encryption (in practice, use proper homomorphic encryption)
                    encrypted_value = self._simple_encrypt(value)
                    protected_params[key] = encrypted_value.tolist()
                else:
                    encrypted_value = self._simple_encrypt(np.array([float(value)]))
                    protected_params[key] = encrypted_value[0]
        
        return protected_params
    
    def _simple_encrypt(self, array: np.ndarray) -> np.ndarray:
        """Simple encryption for demonstration (use proper encryption in production)."""
        # This is a placeholder - use proper homomorphic encryption in production
        key = np.random.random(array.shape)
        return array + key
    
    async def _apply_privacy_protection(self) -> None:
        """Background task for privacy protection maintenance."""
        
        while True:
            try:
                # Check privacy budget consumption
                for model_id, config in self.privacy_configs.items():
                    if config["level"] == PrivacyLevel.DIFFERENTIAL:
                        # Check if privacy budget is exhausted
                        recent_rounds = [r for r in self.round_history[-10:] if r.model_id == model_id]
                        
                        if recent_rounds:
                            total_epsilon = sum(r.privacy_metrics.get("privacy_budget_used", 0) 
                                             for r in recent_rounds)
                            
                            if total_epsilon > 10.0:  # Privacy budget threshold
                                # Reduce epsilon for future rounds
                                config["noise_applied"]["epsilon"] *= 0.9
                
                # Sleep for 1 hour
                await asyncio.sleep(3600)
                
            except Exception as e:
                logger.error(f"Error in privacy protection: {e}")
                await asyncio.sleep(300)
    
    async def _monitor_rounds(self) -> None:
        """Background task to monitor federated learning rounds."""
        
        while True:
            try:
                # Check for stalled rounds
                now = datetime.now()
                stalled_rounds = []
                
                for round_id, round_info in self.active_rounds.items():
                    # Check if round has been active too long (30 minutes)
                    if (now - round_info.start_time).total_seconds() > 1800:
                        stalled_rounds.append(round_id)
                
                # Handle stalled rounds
                for round_id in stalled_rounds:
                    round_info = self.active_rounds[round_id]
                    round_info.status = "stalled"
                    round_info.end_time = now
                    
                    # Move to history
                    self.round_history.append(round_info)
                    del self.active_rounds[round_id]
                    del self.pending_updates[round_id]
                    
                    logger.warning(f"Round stalled: {round_id}")
                
                # Sleep for 5 minutes
                await asyncio.sleep(300)
                
            except Exception as e:
                logger.error(f"Error in round monitoring: {e}")
                await asyncio.sleep(60)
    
    async def get_federated_learning_stats(self) -> Dict[str, Any]:
        """Get comprehensive federated learning statistics."""
        
        stats = {
            "models": {
                "total": len(self.federated_models),
                "active": len([m for m in self.federated_models.values() 
                              if m.metadata.get("status") != "converged"]),
                "converged": len([m for m in self.federated_models.values() 
                                if m.metadata.get("status") == "converged"])
            },
            "rounds": {
                "total": len(self.round_history),
                "active": len(self.active_rounds),
                "completed": len([r for r in self.round_history if r.status == "completed"]),
                "stalled": len([r for r in self.round_history if r.status == "stalled"])
            },
            "agents": {
                "total": len(self.agent_participation),
                "active": len([a for a in self.agent_participation.values() 
                             if (datetime.now() - a["last_update"]).total_seconds() < 3600]),
                "avg_reputation": statistics.mean(self.agent_reputation.values()) if self.agent_reputation else 0.0
            },
            "updates": {
                "total": len(self.local_updates),
                "pending": sum(len(updates) for updates in self.pending_updates.values()),
                "avg_training_samples": statistics.mean([u.training_samples for u in self.local_updates.values()]) if self.local_updates else 0.0
            },
            "privacy": {
                "models_by_level": {
                    level.value: len([m for m in self.federated_models.values() if m.privacy_level == level])
                    for level in PrivacyLevel
                }
            }
        }
        
        return stats
    
    async def shutdown(self) -> None:
        """Shutdown the federated learning orchestrator."""
        
        # Cancel background tasks
        if self._round_monitoring_task:
            self._round_monitoring_task.cancel()
            try:
                await self._round_monitoring_task
            except asyncio.CancelledError:
                pass
        
        if self._privacy_protection_task:
            self._privacy_protection_task.cancel()
            try:
                await self._privacy_protection_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Federated learning orchestrator shutdown completed")