"""Federated Learning Module — Collaborative learning system for multi-agent environments.

This module provides comprehensive federated learning capabilities:
- Federated learning orchestration
- Privacy-preserving model training
- Distributed model aggregation
- Secure model sharing
- Learning coordination across agents
- Performance tracking and validation
"""

from .federated_learning import (
    FederatedLearningOrchestrator,
    FederatedLearningType,
    FederatedModel,
    FederatedRound,
    LearningAggregation,
    LocalModelUpdate,
    ModelType,
    PrivacyLevel,
)

__all__ = [
    "FederatedLearningOrchestrator",
    "FederatedModel",
    "LocalModelUpdate",
    "FederatedRound",
    "LearningAggregation",
    "FederatedLearningType",
    "PrivacyLevel",
    "ModelType"
]