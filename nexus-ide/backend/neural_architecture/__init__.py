"""Neural Architecture Search Module — Automated neural network architecture optimization.

This module provides comprehensive NAS capabilities:
- Neural Architecture Search (NAS) algorithms
- Architecture space exploration
- Performance evaluation and ranking
- Multi-objective optimization
- Architecture transfer learning
- Automated model design
"""

from .neural_architecture_search import (
    ArchitectureEvaluator,
    ArchitectureGenerator,
    ArchitectureType,
    EvolutionaryArchitectureGenerator,
    NASAlgorithm,
    NASResult,
    NeuralArchitecture,
    NeuralArchitectureSearch,
    ObjectiveType,
    RandomArchitectureGenerator,
    SearchSpace,
    SearchSpaceDefinition,
)

__all__ = [
    "NeuralArchitectureSearch",
    "NeuralArchitecture",
    "SearchSpaceDefinition",
    "NASResult",
    "ArchitectureGenerator",
    "RandomArchitectureGenerator",
    "EvolutionaryArchitectureGenerator",
    "ArchitectureEvaluator",
    "NASAlgorithm",
    "SearchSpace",
    "ObjectiveType",
    "ArchitectureType"
]