"""Neural Architecture Search — Automated neural network architecture optimization.

This module provides:
- Neural Architecture Search (NAS) algorithms
- Architecture space exploration
- Performance evaluation and ranking
- Multi-objective optimization
- Architecture transfer learning
- Automated model design
"""

from __future__ import annotations
import statistics

import asyncio
import logging
import json
import numpy as np
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
import uuid
from abc import ABC, abstractmethod
import random
import math
from collections import defaultdict

from backend.observability.event_bus import EventBus
from backend.observability.events import Event

logger = logging.getLogger(__name__)


class NASAlgorithm(Enum):
    """Types of Neural Architecture Search algorithms."""
    RANDOM_SEARCH = "random_search"
    GRID_SEARCH = "grid_search"
    EVOLUTIONARY = "evolutionary"
    REINFORCEMENT_LEARNING = "reinforcement_learning"
    BAYESIAN_OPTIMIZATION = "bayesian_optimization"
    GRADIENT_BASED = "gradient_based"
    ONE_SHOT = "one_shot"
    DIFFERENTIABLE = "differentiable"


class SearchSpace(Enum):
    """Types of search spaces."""
    CELL_BASED = "cell_based"
    LAYER_BASED = "layer_based"
    PATH_BASED = "path_based"
    NETWORK_BASED = "network_based"
    HIERARCHICAL = "hierarchical"


class ObjectiveType(Enum):
    """Types of optimization objectives."""
    ACCURACY = "accuracy"
    LATENCY = "latency"
    MEMORY = "memory"
    ENERGY = "energy"
    FLOPS = "flops"
    PARAMETERS = "parameters"


class ArchitectureType(Enum):
    """Types of neural architectures."""
    CNN = "cnn"
    RNN = "rnn"
    TRANSFORMER = "transformer"
    MLP = "mlp"
    GAN = "gan"
    AUTOENCODER = "autoencoder"
    HYBRID = "hybrid"


@dataclass
class NeuralArchitecture:
    """Represents a neural network architecture."""
    arch_id: str
    name: str
    architecture_type: ArchitectureType
    layers: List[Dict[str, Any]]
    connections: List[Dict[str, Any]]
    hyperparameters: Dict[str, Any]
    performance_metrics: Dict[str, float]
    complexity_metrics: Dict[str, float]
    created_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchSpaceDefinition:
    """Defines the search space for NAS."""
    space_id: str
    name: str
    space_type: SearchSpace
    layer_types: List[str]
    operations: List[Dict[str, Any]]
    constraints: Dict[str, Any]
    objectives: List[ObjectiveType]
    created_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NASResult:
    """Represents a NAS search result."""
    result_id: str
    search_id: str
    best_architecture: NeuralArchitecture
    all_evaluated: List[NeuralArchitecture]
    search_metrics: Dict[str, float]
    optimization_history: List[Dict[str, Any]]
    convergence_info: Dict[str, Any]
    created_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class ArchitectureGenerator(ABC):
    """Abstract base class for architecture generators."""
    
    @abstractmethod
    async def generate_architecture(self, search_space: SearchSpaceDefinition,
                                 constraints: Dict[str, Any] = None) -> NeuralArchitecture:
        """Generate a neural architecture."""
        pass


class RandomArchitectureGenerator(ArchitectureGenerator):
    """Random architecture generator."""
    
    async def generate_architecture(self, search_space: SearchSpaceDefinition,
                                 constraints: Dict[str, Any] = None) -> NeuralArchitecture:
        """Generate a random architecture."""
        
        arch_id = str(uuid.uuid4())
        
        # Randomly select architecture type
        arch_type = random.choice(list(ArchitectureType))
        
        # Generate random layers
        layers = []
        num_layers = random.randint(3, 10)
        
        for i in range(num_layers):
            layer_type = random.choice(search_space.layer_types)
            
            layer = {
                'layer_id': f'layer_{i}',
                'type': layer_type,
                'position': i,
                'config': self._generate_layer_config(layer_type, search_space)
            }
            
            layers.append(layer)
        
        # Generate random connections
        connections = []
        for i in range(num_layers - 1):
            connections.append({
                'from': f'layer_{i}',
                'to': f'layer_{i + 1}',
                'type': 'sequential'
            })
        
        # Add some skip connections
        if random.random() < 0.3:  # 30% chance of skip connections
            for i in range(0, num_layers - 2, 2):
                if random.random() < 0.5:
                    connections.append({
                        'from': f'layer_{i}',
                        'to': f'layer_{i + 2}',
                        'type': 'skip'
                    })
        
        # Generate hyperparameters
        hyperparameters = {
            'learning_rate': 10 ** random.uniform(-4, -1),
            'batch_size': random.choice([16, 32, 64, 128, 256]),
            'optimizer': random.choice(['adam', 'sgd', 'rmsprop']),
            'dropout_rate': random.uniform(0.0, 0.5),
            'weight_decay': 10 ** random.uniform(-6, -2)
        }
        
        architecture = NeuralArchitecture(
            arch_id=arch_id,
            name=f"Random_Arch_{random.randint(1000, 9999)}",
            architecture_type=arch_type,
            layers=layers,
            connections=connections,
            hyperparameters=hyperparameters,
            performance_metrics={},
            complexity_metrics=self._calculate_complexity_metrics(layers, connections),
            created_at=datetime.now()
        )
        
        return architecture
    
    def _generate_layer_config(self, layer_type: str, search_space: SearchSpaceDefinition) -> Dict[str, Any]:
        """Generate configuration for a specific layer type."""
        
        if layer_type == 'conv':
            return {
                'filters': random.choice([16, 32, 64, 128, 256]),
                'kernel_size': random.choice([3, 5, 7]),
                'stride': random.choice([1, 2]),
                'padding': random.choice(['same', 'valid']),
                'activation': random.choice(['relu', 'tanh', 'sigmoid'])
            }
        elif layer_type == 'dense':
            return {
                'units': random.choice([32, 64, 128, 256, 512]),
                'activation': random.choice(['relu', 'tanh', 'sigmoid'])
            }
        elif layer_type == 'lstm':
            return {
                'units': random.choice([32, 64, 128, 256]),
                'return_sequences': random.choice([True, False]),
                'dropout': random.uniform(0.0, 0.5)
            }
        elif layer_type == 'attention':
            return {
                'num_heads': random.choice([4, 8, 16]),
                'key_dim': random.choice([32, 64, 128]),
                'dropout': random.uniform(0.0, 0.5)
            }
        else:
            return {}
    
    def _calculate_complexity_metrics(self, layers: List[Dict[str, Any]], 
                                   connections: List[Dict[str, Any]]) -> Dict[str, float]:
        """Calculate complexity metrics for an architecture."""
        
        # Count parameters (simplified)
        total_params = 0
        for layer in layers:
            layer_type = layer['type']
            config = layer.get('config', {})
            
            if layer_type == 'conv':
                filters = config.get('filters', 64)
                kernel_size = config.get('kernel_size', 3)
                total_params += filters * kernel_size * kernel_size
            elif layer_type == 'dense':
                units = config.get('units', 128)
                total_params += units
            elif layer_type == 'lstm':
                units = config.get('units', 128)
                total_params += 4 * units * units  # Simplified LSTM parameter count
        
        # Calculate depth
        depth = len(layers)
        
        # Calculate connectivity
        connectivity = len(connections)
        
        return {
            'parameters': total_params,
            'depth': depth,
            'connectivity': connectivity,
            'complexity_score': total_params / 1000000  # Normalized complexity
        }


class EvolutionaryArchitectureGenerator(ArchitectureGenerator):
    """Evolutionary architecture generator."""
    
    def __init__(self, population_size: int = 50, mutation_rate: float = 0.1,
                 crossover_rate: float = 0.8):
        self.population_size = population_size
        self.mutation_rate = mutation_rate
        self.crossover_rate = crossover_rate
        self.population = []
        self.generation = 0
    
    async def generate_architecture(self, search_space: SearchSpaceDefinition,
                                 constraints: Dict[str, Any] = None) -> NeuralArchitecture:
        """Generate architecture using evolutionary algorithm."""
        
        if not self.population:
            # Initialize population
            await self._initialize_population(search_space)
        
        # Select parents
        parents = self._select_parents()
        
        # Create offspring through crossover
        offspring = await self._crossover(parents[0], parents[1])
        
        # Apply mutation
        if random.random() < self.mutation_rate:
            offspring = await self._mutate(offspring, search_space)
        
        # Update generation
        self.generation += 1
        
        return offspring
    
    async def _initialize_population(self, search_space: SearchSpaceDefinition) -> None:
        """Initialize the evolutionary population."""
        
        generator = RandomArchitectureGenerator()
        
        for _ in range(self.population_size):
            arch = await generator.generate_architecture(search_space)
            self.population.append(arch)
    
    def _select_parents(self) -> List[NeuralArchitecture]:
        """Select parents using tournament selection."""
        
        # Simple tournament selection
        parents = []
        
        for _ in range(2):
            tournament = random.sample(self.population, min(5, len(self.population)))
            
            # Select best from tournament (simplified - would use actual performance)
            best = max(tournament, key=lambda a: a.complexity_metrics.get('complexity_score', 0))
            parents.append(best)
        
        return parents
    
    async def _crossover(self, parent1: NeuralArchitecture, parent2: NeuralArchitecture) -> NeuralArchitecture:
        """Perform crossover between two parent architectures."""
        
        arch_id = str(uuid.uuid4())
        
        # Choose crossover point
        crossover_point = random.randint(1, min(len(parent1.layers), len(parent2.layers)) - 1)
        
        # Create child architecture
        child_layers = parent1.layers[:crossover_point] + parent2.layers[crossover_point:]
        
        # Combine connections
        child_connections = []
        
        # Add connections from first parent
        for conn in parent1.connections:
            if conn['to'] in [layer['layer_id'] for layer in child_layers]:
                child_connections.append(conn)
        
        # Add connections from second parent
        for conn in parent2.connections:
            if conn['from'] in [layer['layer_id'] for layer in child_layers]:
                child_connections.append(conn)
        
        # Combine hyperparameters
        child_hyperparameters = {}
        for key in parent1.hyperparameters:
            if random.random() < 0.5:
                child_hyperparameters[key] = parent1.hyperparameters[key]
            else:
                child_hyperparameters[key] = parent2.hyperparameters.get(key)
        
        architecture = NeuralArchitecture(
            arch_id=arch_id,
            name=f"Evo_Arch_{self.generation}_{random.randint(1000, 9999)}",
            architecture_type=parent1.architecture_type,
            layers=child_layers,
            connections=child_connections,
            hyperparameters=child_hyperparameters,
            performance_metrics={},
            complexity_metrics=self._calculate_complexity_metrics(child_layers, child_connections),
            created_at=datetime.now(),
            metadata={
                'generation': self.generation,
                'parent1_id': parent1.arch_id,
                'parent2_id': parent2.arch_id
            }
        )
        
        return architecture
    
    async def _mutate(self, architecture: NeuralArchitecture, 
                      search_space: SearchSpaceDefinition) -> NeuralArchitecture:
        """Apply mutation to an architecture."""
        
        arch_id = str(uuid.uuid4())
        mutated_layers = architecture.layers.copy()
        
        # Random mutation operation
        mutation_type = random.choice(['add_layer', 'remove_layer', 'modify_layer', 'modify_connection'])
        
        if mutation_type == 'add_layer' and len(mutated_layers) < 15:
            # Add a new layer
            layer_id = f'layer_{len(mutated_layers)}'
            layer_type = random.choice(search_space.layer_types)
            
            new_layer = {
                'layer_id': layer_id,
                'type': layer_type,
                'position': len(mutated_layers),
                'config': self._generate_layer_config(layer_type, search_space)
            }
            
            mutated_layers.append(new_layer)
            
            # Update connections
            if mutated_layers:
                architecture.connections.append({
                    'from': mutated_layers[-2]['layer_id'],
                    'to': layer_id,
                    'type': 'sequential'
                })
        
        elif mutation_type == 'remove_layer' and len(mutated_layers) > 3:
            # Remove a random layer
            layer_to_remove = random.randint(1, len(mutated_layers) - 2)
            del mutated_layers[layer_to_remove]
            
            # Update layer positions
            for i, layer in enumerate(mutated_layers):
                layer['position'] = i
            
            # Remove related connections
            architecture.connections = [
                conn for conn in architecture.connections
                if conn['from'] != f'layer_{layer_to_remove}' and conn['to'] != f'layer_{layer_to_remove}'
            ]
        
        elif mutation_type == 'modify_layer':
            # Modify a random layer
            layer_to_modify = random.randint(0, len(mutated_layers) - 1)
            layer = mutated_layers[layer_to_modify]
            
            # Modify layer configuration
            if layer['type'] == 'conv':
                config = layer['config']
                if random.random() < 0.5:
                    config['filters'] = random.choice([16, 32, 64, 128, 256])
                if random.random() < 0.5:
                    config['kernel_size'] = random.choice([3, 5, 7])
            elif layer['type'] == 'dense':
                config = layer['config']
                if random.random() < 0.5:
                    config['units'] = random.choice([32, 64, 128, 256, 512])
            
            mutated_architecture = NeuralArchitecture(
                arch_id=arch_id,
                name=f"Mutated_Arch_{self.generation}_{random.randint(1000, 9999)}",
                architecture_type=architecture.architecture_type,
                layers=mutated_layers,
                connections=architecture.connections,
                hyperparameters=architecture.hyperparameters,
                performance_metrics={},
                complexity_metrics=self._calculate_complexity_metrics(mutated_layers, architecture.connections),
                created_at=datetime.now(),
                metadata={
                    'generation': self.generation,
                    'mutation_type': mutation_type,
                    'parent_id': architecture.arch_id
                }
            )
            
            return mutated_architecture
        
        # For other mutations, return original architecture
        mutated_architecture = NeuralArchitecture(
            arch_id=arch_id,
            name=f"Mutated_Arch_{self.generation}_{random.randint(1000, 9999)}",
            architecture_type=architecture.architecture_type,
            layers=mutated_layers,
            connections=architecture.connections,
            hyperparameters=architecture.hyperparameters,
            performance_metrics={},
            complexity_metrics=self._calculate_complexity_metrics(mutated_layers, architecture.connections),
            created_at=datetime.now(),
            metadata={
                'generation': self.generation,
                'mutation_type': mutation_type,
                'parent_id': architecture.arch_id
            }
        )
        
        return mutated_architecture
    
    def _generate_layer_config(self, layer_type: str, search_space: SearchSpaceDefinition) -> Dict[str, Any]:
        """Generate configuration for a specific layer type."""
        
        if layer_type == 'conv':
            return {
                'filters': random.choice([16, 32, 64, 128, 256]),
                'kernel_size': random.choice([3, 5, 7]),
                'stride': random.choice([1, 2]),
                'padding': random.choice(['same', 'valid']),
                'activation': random.choice(['relu', 'tanh', 'sigmoid'])
            }
        elif layer_type == 'dense':
            return {
                'units': random.choice([32, 64, 128, 256, 512]),
                'activation': random.choice(['relu', 'tanh', 'sigmoid'])
            }
        elif layer_type == 'lstm':
            return {
                'units': random.choice([32, 64, 128, 256]),
                'return_sequences': random.choice([True, False]),
                'dropout': random.uniform(0.0, 0.5)
            }
        elif layer_type == 'attention':
            return {
                'num_heads': random.choice([4, 8, 16]),
                'key_dim': random.choice([32, 64, 128]),
                'dropout': random.uniform(0.0, 0.5)
            }
        else:
            return {}
    
    def _calculate_complexity_metrics(self, layers: List[Dict[str, Any]], 
                                   connections: List[Dict[str, Any]]) -> Dict[str, float]:
        """Calculate complexity metrics for an architecture."""
        
        # Count parameters (simplified)
        total_params = 0
        for layer in layers:
            layer_type = layer['type']
            config = layer.get('config', {})
            
            if layer_type == 'conv':
                filters = config.get('filters', 64)
                kernel_size = config.get('kernel_size', 3)
                total_params += filters * kernel_size * kernel_size
            elif layer_type == 'dense':
                units = config.get('units', 128)
                total_params += units
            elif layer_type == 'lstm':
                units = config.get('units', 128)
                total_params += 4 * units * units  # Simplified LSTM parameter count
        
        # Calculate depth
        depth = len(layers)
        
        # Calculate connectivity
        connectivity = len(connections)
        
        return {
            'parameters': total_params,
            'depth': depth,
            'connectivity': connectivity,
            'complexity_score': total_params / 1000000  # Normalized complexity
        }


class ArchitectureEvaluator:
    """Evaluates neural architectures."""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.evaluation_history: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    
    async def evaluate_architecture(self, architecture: NeuralArchitecture,
                                 objectives: List[ObjectiveType],
                                 dataset_info: Dict[str, Any] = None) -> Dict[str, float]:
        """Evaluate a neural architecture."""
        
        evaluation_id = str(uuid.uuid4())
        
        # Simulate evaluation (in practice, would train and test the model)
        evaluation_results = {}
        
        # Simulate accuracy based on architecture complexity
        complexity = architecture.complexity_metrics.get('complexity_score', 0)
        
        for objective in objectives:
            if objective == ObjectiveType.ACCURACY:
                # Simulate accuracy (higher complexity can lead to better accuracy up to a point)
                base_accuracy = 0.7
                complexity_bonus = min(0.2, complexity * 0.5)
                noise = random.uniform(-0.05, 0.05)
                evaluation_results['accuracy'] = base_accuracy + complexity_bonus + noise
                
            elif objective == ObjectiveType.LATENCY:
                # Simulate latency (higher complexity increases latency)
                base_latency = 0.1  # 100ms
                complexity_penalty = complexity * 0.5
                noise = random.uniform(-0.02, 0.02)
                evaluation_results['latency'] = base_latency + complexity_penalty + noise
                
            elif objective == ObjectiveType.MEMORY:
                # Simulate memory usage
                params = architecture.complexity_metrics.get('parameters', 0)
                base_memory = 100  # MB
                memory_usage = base_memory + params * 0.001  # 1 byte per parameter
                noise = random.uniform(-10, 10)
                evaluation_results['memory'] = memory_usage + noise
                
            elif objective == ObjectiveType.FLOPS:
                # Simulate FLOPS
                depth = architecture.complexity_metrics.get('depth', 0)
                params = architecture.complexity_metrics.get('parameters', 0)
                base_flops = 1000000  # 1M FLOPS
                fudge_factor = depth * params * 1000
                evaluation_results['flops'] = base_flops + fudge_factor
                
            elif objective == ObjectiveType.PARAMETERS:
                evaluation_results['parameters'] = architecture.complexity_metrics.get('parameters', 0)
        
        # Store evaluation history
        self.evaluation_history[architecture.arch_id].append({
            'evaluation_id': evaluation_id,
            'objectives': [obj.value for obj in objectives],
            'results': evaluation_results,
            'timestamp': datetime.now().isoformat()
        })
        
        # Keep only last 100 evaluations
        if len(self.evaluation_history[architecture.arch_id]) > 100:
            self.evaluation_history[architecture.arch_id] = self.evaluation_history[architecture.arch_id][-100:]
        
        # Update architecture performance metrics
        architecture.performance_metrics = evaluation_results
        
        # Emit evaluation event
        await self.event_bus.emit(Event(
            type="architecture_evaluated",
            data={
                "arch_id": architecture.arch_id,
                "objectives": [obj.value for obj in objectives],
                "results": evaluation_results
            }
        ))
        
        return evaluation_results
    
    def get_evaluation_summary(self, arch_id: str) -> Dict[str, Any]:
        """Get evaluation summary for an architecture."""
        
        if arch_id not in self.evaluation_history:
            return {"error": "No evaluation history found"}
        
        evaluations = self.evaluation_history[arch_id]
        
        if not evaluations:
            return {"error": "No evaluations found"}
        
        # Calculate statistics
        latest_results = evaluations[-1]['results']
        
        summary = {
            'arch_id': arch_id,
            'total_evaluations': len(evaluations),
            'latest_results': latest_results,
            'average_results': {},
            'best_results': {},
            'worst_results': {}
        }
        
        # Calculate averages
        all_results = defaultdict(list)
        for eval_data in evaluations:
            for key, value in eval_data['results'].items():
                all_results[key].append(value)
        
        for key, values in all_results.items():
            summary['average_results'][key] = statistics.mean(values)
            summary['best_results'][key] = max(values)
            summary['worst_results'][key] = min(values)
        
        return summary


class NeuralArchitectureSearch:
    """Main Neural Architecture Search orchestrator."""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.search_spaces: Dict[str, SearchSpaceDefinition] = {}
        self.search_results: Dict[str, NASResult] = {}
        self.architecture_generator: ArchitectureGenerator = EvolutionaryArchitectureGenerator()
        self.evaluator = ArchitectureEvaluator(event_bus)
        
        # Search configuration
        self.max_iterations = 100
        self.early_stopping_patience = 10
        
        # Performance tracking
        self.search_metrics: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    
    async def create_search_space(self, name: str, space_type: SearchSpace,
                                layer_types: List[str], operations: List[Dict[str, Any]],
                                constraints: Dict[str, Any],
                                objectives: List[ObjectiveType]) -> str:
        """Create a search space for NAS."""
        
        space_id = str(uuid.uuid4())
        
        search_space = SearchSpaceDefinition(
            space_id=space_id,
            name=name,
            space_type=space_type,
            layer_types=layer_types,
            operations=operations,
            constraints=constraints,
            objectives=objectives,
            created_at=datetime.now()
        )
        
        # Store search space
        self.search_spaces[space_id] = search_space
        
        # Emit creation event
        await self.event_bus.emit(Event(
            type="search_space_created",
            data={
                "space_id": space_id,
                "name": name,
                "space_type": space_type.value,
                "layer_types": layer_types,
                "objectives": [obj.value for obj in objectives]
            }
        ))
        
        logger.info(f"Search space created: {space_id} ({name})")
        
        return space_id
    
    async def run_search(self, space_id: str, num_iterations: int = None,
                      objectives: List[ObjectiveType] = None) -> str:
        """Run Neural Architecture Search."""
        
        if space_id not in self.search_spaces:
            raise ValueError(f"Search space not found: {space_id}")
        
        search_space = self.search_spaces[space_id]
        search_id = str(uuid.uuid4())
        
        num_iterations = num_iterations or self.max_iterations
        objectives = objectives or search_space.objectives
        
        # Initialize search
        best_architecture = None
        best_score = -float('inf')
        all_evaluated = []
        optimization_history = []
        
        # Run search iterations
        for iteration in range(num_iterations):
            # Generate architecture
            architecture = await self.architecture_generator.generate_architecture(search_space)
            
            # Evaluate architecture
            evaluation_results = await self.evaluator.evaluate_architecture(
                architecture, objectives
            )
            
            # Calculate multi-objective score (weighted sum)
            score = self._calculate_multi_objective_score(evaluation_results, objectives)
            
            # Update best architecture
            if score > best_score:
                best_score = score
                best_architecture = architecture
            
            all_evaluated.append(architecture)
            
            # Track optimization history
            optimization_history.append({
                'iteration': iteration,
                'score': score,
                'architecture_id': architecture.arch_id,
                'evaluation_results': evaluation_results
            })
            
            # Store search metrics
            self.search_metrics[search_id].append({
                'iteration': iteration,
                'score': score,
                'best_score': best_score,
                'timestamp': datetime.now().isoformat()
            })
            
            # Early stopping check
            if iteration > self.early_stopping_patience:
                recent_scores = [h['score'] for h in optimization_history[-self.early_stopping_patience:]]
                if all(abs(recent_scores[i] - recent_scores[-1]) < 0.001 for i in range(len(recent_scores) - 1)):
                    logger.info(f"Early stopping at iteration {iteration}")
                    break
        
        # Create search result
        result = NASResult(
            result_id=search_id,
            search_id=search_id,
            best_architecture=best_architecture,
            all_evaluated=all_evaluated,
            search_metrics={
                'best_score': best_score,
                'num_iterations': iteration + 1,
                'convergence_iteration': self._find_convergence_point(optimization_history)
            },
            optimization_history=optimization_history,
            convergence_info=self._analyze_convergence(optimization_history),
            created_at=datetime.now()
        )
        
        # Store result
        self.search_results[search_id] = result
        
        # Emit completion event
        await self.event_bus.emit(Event(
            type="nas_completed",
            data={
                "search_id": search_id,
                "space_id": space_id,
                "best_score": best_score,
                "num_iterations": iteration + 1,
                "best_architecture_id": best_architecture.arch_id if best_architecture else None
            }
        ))
        
        logger.info(f"NAS completed: {search_id} (Best score: {best_score:.4f})")
        
        return search_id
    
    def _calculate_multi_objective_score(self, evaluation_results: Dict[str, float],
                                       objectives: List[ObjectiveType]) -> float:
        """Calculate multi-objective score."""
        
        # Define weights for different objectives
        weights = {
            ObjectiveType.ACCURACY: 0.4,
            ObjectiveType.LATENCY: -0.2,  # Lower latency is better
            ObjectiveType.MEMORY: -0.1,  # Lower memory is better
            ObjectiveType.FLOPS: 0.1,
            ObjectiveType.PARAMETERS: -0.2  # Fewer parameters is better
        }
        
        score = 0.0
        total_weight = 0.0
        
        for objective in objectives:
            if objective in evaluation_results and objective in weights:
                weight = weights[objective]
                value = evaluation_results[objective]
                
                # Normalize values (simplified)
                if objective == ObjectiveType.ACCURACY:
                    normalized_value = value  # Already 0-1
                elif objective == ObjectiveType.LATENCY:
                    normalized_value = max(0, 1 - value / 1.0)  # Assume max 1 second
                elif objective == ObjectiveType.MEMORY:
                    normalized_value = max(0, 1 - value / 1000)  # Assume max 1GB
                elif objective == ObjectiveType.FLOPS:
                    normalized_value = min(1, value / 100000000)  # Assume max 100M FLOPS
                elif objective == ObjectiveType.PARAMETERS:
                    normalized_value = max(0, 1 - value / 10000000)  # Assume max 10M params
                
                score += weight * normalized_value
                total_weight += abs(weight)
        
        return score / total_weight if total_weight > 0 else 0.0
    
    def _find_convergence_point(self, optimization_history: List[Dict[str, Any]]) -> int:
        """Find the iteration where convergence occurred."""
        
        if len(optimization_history) < 5:
            return len(optimization_history)
        
        # Look for point where improvement becomes minimal
        for i in range(len(optimization_history) - 1, 4, -1):
            recent_improvements = []
            
            for j in range(i, min(i + 5, len(optimization_history))):
                if j > 0:
                    improvement = optimization_history[j]['score'] - optimization_history[j-1]['score']
                    recent_improvements.append(abs(improvement))
            
            if all(imp < 0.001 for imp in recent_improvements):
                return i + 1
        
        return len(optimization_history)
    
    def _analyze_convergence(self, optimization_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze convergence characteristics."""
        
        if len(optimization_history) < 2:
            return {}
        
        scores = [h['score'] for h in optimization_history]
        
        # Calculate improvement rate
        improvements = []
        for i in range(1, len(scores)):
            improvement = scores[i] - scores[i-1]
            improvements.append(improvement)
        
        return {
            'final_score': scores[-1],
            'initial_score': scores[0],
            'total_improvement': scores[-1] - scores[0],
            'average_improvement': statistics.mean(improvements),
            'improvement_variance': statistics.variance(improvements) if len(improvements) > 1 else 0,
            'convergence_rate': len([imp for imp in improvements if abs(imp) < 0.001]) / len(improvements)
        }
    
    async def get_search_statistics(self) -> Dict[str, Any]:
        """Get comprehensive NAS statistics."""
        
        stats = {
            "search_spaces": {
                "total": len(self.search_spaces),
                "by_type": {
                    space_type.value: len([s for s in self.search_spaces.values() if s.space_type == space_type])
                    for space_type in SearchSpace
                }
            },
            "searches": {
                "total": len(self.search_results),
                "completed": len(self.search_results),
                "best_scores": [r.search_metrics['best_score'] for r in self.search_results.values()],
                "avg_iterations": statistics.mean([r.search_metrics['num_iterations'] for r in self.search_results.values()]) if self.search_results else 0
            },
            "architectures": {
                "total_evaluated": sum(len(r.all_evaluated) for r in self.search_results.values()),
                "unique_types": len(set(a.architecture_type.value for r in self.search_results.values() for a in r.all_evaluated))
            },
            "performance": {
                "average_best_score": statistics.mean([r.search_metrics['best_score'] for r in self.search_results.values()]) if self.search_results else 0,
                "convergence_rate": statistics.mean([r.convergence_info.get('convergence_rate', 0) for r in self.search_results.values() if r.convergence_info]) if self.search_results else 0
            }
        }
        
        return stats
    
    async def shutdown(self) -> None:
        """Shutdown the NAS system."""
        
        logger.info("Neural Architecture Search shutdown completed")


# Utility function to generate layer config
def _generate_layer_config(layer_type: str, search_space: SearchSpaceDefinition) -> Dict[str, Any]:
    """Generate configuration for a specific layer type."""
    
    if layer_type == 'conv':
        return {
            'filters': random.choice([16, 32, 64, 128, 256]),
            'kernel_size': random.choice([3, 5, 7]),
            'stride': random.choice([1, 2]),
            'padding': random.choice(['same', 'valid']),
            'activation': random.choice(['relu', 'tanh', 'sigmoid'])
        }
    elif layer_type == 'dense':
        return {
            'units': random.choice([32, 64, 128, 256, 512]),
            'activation': random.choice(['relu', 'tanh', 'sigmoid'])
        }
    elif layer_type == 'lstm':
        return {
            'units': random.choice([32, 64, 128, 256]),
            'return_sequences': random.choice([True, False]),
            'dropout': random.uniform(0.0, 0.5)
        }
    elif layer_type == 'attention':
        return {
            'num_heads': random.choice([4, 8, 16]),
            'key_dim': random.choice([32, 64, 128]),
            'dropout': random.uniform(0.0, 0.5)
        }
    else:
        return {}


# Add the missing method to EvolutionaryArchitectureGenerator
async def _initialize_population(self, search_space: SearchSpaceDefinition) -> None:
    """Initialize the evolutionary population."""
    
    generator = RandomArchitectureGenerator()
    
    for _ in range(self.population_size):
        arch = await generator.generate_architecture(search_space)
        self.population.append(arch)


# Add the missing method to EvolutionaryArchitectureGenerator
def _generate_layer_config(self, layer_type: str, search_space: SearchSpaceDefinition) -> Dict[str, Any]:
    """Generate configuration for a specific layer type."""
    
    if layer_type == 'conv':
        return {
            'filters': random.choice([16, 32, 64, 128, 256]),
            'kernel_size': random.choice([3, 5, 7]),
            'stride': random.choice([1, 2]),
            'padding': random.choice(['same', 'valid']),
            'activation': random.choice(['relu', 'tanh', 'sigmoid'])
        }
    elif layer_type == 'dense':
        return {
            'units': random.choice([32, 64, 128, 256, 512]),
            'activation': random.choice(['relu', 'tanh', 'sigmoid'])
        }
    elif layer_type == 'lstm':
        return {
            'units': random.choice([32, 64, 128, 256]),
            'return_sequences': random.choice([True, False]),
            'dropout': random.uniform(0.0, 0.5)
        }
    elif layer_type == 'attention':
        return {
            'num_heads': random.choice([4, 8, 16]),
            'key_dim': random.choice([32, 64, 128]),
            'dropout': random.uniform(0.0, 0.5)
        }
    else:
        return {}


# Add the missing method to EvolutionaryArchitectureGenerator
def _calculate_complexity_metrics(self, layers: List[Dict[str, Any]], 
                               connections: List[Dict[str, Any]]) -> Dict[str, float]:
    """Calculate complexity metrics for an architecture."""
    
    # Count parameters (simplified)
    total_params = 0
    for layer in layers:
        layer_type = layer['type']
        config = layer.get('config', {})
        
        if layer_type == 'conv':
            filters = config.get('filters', 64)
            kernel_size = config.get('kernel_size', 3)
            total_params += filters * kernel_size * kernel_size
        elif layer_type == 'dense':
            units = config.get('units', 128)
            total_params += units
        elif layer_type == 'lstm':
            units = config.get('units', 128)
            total_params += 4 * units * units  # Simplified LSTM parameter count
    
    # Calculate depth
    depth = len(layers)
    
    # Calculate connectivity
    connectivity = len(connections)
    
    return {
        'parameters': total_params,
        'depth': depth,
        'connectivity': connectivity,
        'complexity_score': total_params / 1000000  # Normalized complexity
    }


# Add the missing method to EvolutionaryArchitectureGenerator
def _mutate(self, architecture: NeuralArchitecture, 
             search_space: SearchSpaceDefinition) -> NeuralArchitecture:
    """Apply mutation to an architecture."""
    
    arch_id = str(uuid.uuid4())
    mutated_layers = architecture.layers.copy()
    
    # Random mutation operation
    mutation_type = random.choice(['add_layer', 'remove_layer', 'modify_layer', 'modify_connection'])
    
    if mutation_type == 'add_layer' and len(mutated_layers) < 15:
        # Add a new layer
        layer_id = f'layer_{len(mutated_layers)}'
        layer_type = random.choice(search_space.layer_types)
        
        new_layer = {
            'layer_id': layer_id,
            'type': layer_type,
            'position': len(mutated_layers),
            'config': _generate_layer_config(layer_type, search_space)
        }
        
        mutated_layers.append(new_layer)
        
        # Update connections
        if mutated_layers:
            architecture.connections.append({
                'from': mutated_layers[-2]['layer_id'],
                'to': layer_id,
                'type': 'sequential'
            })
    
    elif mutation_type == 'remove_layer' and len(mutated_layers) > 3:
        # Remove a random layer
        layer_to_remove = random.randint(1, len(mutated_layers) - 2)
        del mutated_layers[layer_to_remove]
        
        # Update layer positions
        for i, layer in enumerate(mutated_layers):
            layer['position'] = i
        
        # Remove related connections
        architecture.connections = [
            conn for conn in architecture.connections
            if conn['from'] != f'layer_{layer_to_remove}' and conn['to'] != f'layer_{layer_to_remove}'
        ]
    
    elif mutation_type == 'modify_layer':
        # Modify a random layer
        layer_to_modify = random.randint(0, len(mutated_layers) - 1)
        layer = mutated_layers[layer_to_modify]
        
        # Modify layer configuration
        if layer['type'] == 'conv':
            config = layer['config']
            if random.random() < 0.5:
                config['filters'] = random.choice([16, 32, 64, 128, 256])
            if random.random() < 0.5:
                config['kernel_size'] = random.choice([3, 5, 7])
        elif layer['type'] == 'dense':
            config = layer['config']
            if random.random() < 0.5:
                config['units'] = random.choice([32, 64, 128, 256, 512])
        
        mutated_architecture = NeuralArchitecture(
            arch_id=arch_id,
            name=f"Mutated_Arch_{self.generation}_{random.randint(1000, 9999)}",
            architecture_type=architecture.architecture_type,
            layers=mutated_layers,
            connections=architecture.connections,
            hyperparameters=architecture.hyperparameters,
            performance_metrics={},
            complexity_metrics=_calculate_complexity_metrics(mutated_layers, architecture.connections),
            created_at=datetime.now(),
            metadata={
                'generation': self.generation,
                'mutation_type': mutation_type,
                'parent_id': architecture.arch_id
            }
        )
        
        return mutated_architecture
    
    # For other mutations, return original architecture
    mutated_architecture = NeuralArchitecture(
        arch_id=arch_id,
        name=f"Mutated_Arch_{self.generation}_{random.randint(1000, 9999)}",
        architecture_type=architecture.architecture_type,
        layers=mutated_layers,
        connections=architecture.connections,
        hyperparameters=architecture.hyperparameters,
        performance_metrics={},
        complexity_metrics=_calculate_complexity_metrics(mutated_layers, architecture.connections),
        created_at=datetime.now(),
        metadata={
            'generation': self.generation,
            'mutation_type': mutation_type,
            'parent_id': architecture.arch_id
        }
    )
    
    return mutated_architecture


# Add the missing method to RandomArchitectureGenerator
def _calculate_complexity_metrics(self, layers: List[Dict[str, Any]], 
                               connections: List[Dict[str, Any]]) -> Dict[str, float]:
    """Calculate complexity metrics for an architecture."""
    
    # Count parameters (simplified)
    total_params = 0
    for layer in layers:
        layer_type = layer['type']
        config = layer.get('config', {})
        
        if layer_type == 'conv':
            filters = config.get('filters', 64)
            kernel_size = config.get('kernel_size', 3)
            total_params += filters * kernel_size * kernel_size
        elif layer_type == 'dense':
            units = config.get('units', 128)
            total_params += units
        elif layer_type == 'lstm':
            units = config.get('units', 128)
            total_params += 4 * units * units  # Simplified LSTM parameter count
    
    # Calculate depth
    depth = len(layers)
    
    # Calculate connectivity
    connectivity = len(connections)
    
    return {
        'parameters': total_params,
        'depth': depth,
        'connectivity': connectivity,
        'complexity_score': total_params / 1000000  # Normalized complexity
    }


# Add the missing method to RandomArchitectureGenerator
def _generate_layer_config(self, layer_type: str, search_space: SearchSpaceDefinition) -> Dict[str, Any]:
    """Generate configuration for a specific layer type."""
    
    if layer_type == 'conv':
        return {
            'filters': random.choice([16, 32, 64, 128, 256]),
            'kernel_size': random.choice([3, 5, 7]),
            'stride': random.choice([1, 2]),
            'padding': random.choice(['same', 'valid']),
            'activation': random.choice(['relu', 'tanh', 'sigmoid'])
        }
    elif layer_type == 'dense':
        return {
            'units': random.choice([32, 64, 128, 256, 512]),
            'activation': random.choice(['relu', 'tanh', 'sigmoid'])
        }
    elif layer_type == 'lstm':
        return {
            'units': random.choice([32, 64, 128, 256]),
            'return_sequences': random.choice([True, False]),
            'dropout': random.uniform(0.0, 0.5)
        }
    elif layer_type == 'attention':
        return {
            'num_heads': random.choice([4, 8, 16]),
            'key_dim': random.choice([32, 64, 128]),
            'dropout': random.uniform(0.0, 0.5)
        }
    else:
        return {}
