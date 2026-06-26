"""Parallel Inference Engine with Multi-Model Orchestration.

Implements parallel inference across multiple models, batch processing,
model ensemble, result aggregation, load balancing, and dynamic scaling.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union, Callable
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import threading

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from backend.config.settings import get_settings

logger = logging.getLogger(__name__)


class InferenceStrategy(str, Enum):
    """Parallel inference strategies."""
    PARALLEL = "parallel"  # Run all models in parallel
    SEQUENTIAL = "sequential"  # Run models sequentially
    ENSEMBLE = "ensemble"  # Weighted ensemble
    CASCADE = "cascade"  # Try models in order until success
    MAJORITY_VOTE = "majority_vote"  # Majority voting
    WEIGHTED_AVERAGE = "weighted_average"  # Weighted averaging


class ModelStatus(str, Enum):
    """Model status tracking."""
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    MAINTENANCE = "maintenance"
    SCALING = "scaling"


@dataclass
class ModelConfig:
    """Model configuration for parallel inference."""
    model_id: str
    model_name: str
    endpoint: str
    max_concurrent: int = 5
    timeout: float = 30.0
    retry_attempts: int = 3
    weight: float = 1.0
    priority: int = 1
    capabilities: Set[str] = field(default_factory=set)
    cost_per_token: float = 0.0
    latency_target: float = 1.0
    
    def __post_init__(self):
        if isinstance(self.capabilities, list):
            self.capabilities = set(self.capabilities)


@dataclass
class InferenceRequest:
    """Request for parallel inference."""
    request_id: str = field(default_factory=lambda: f"req-{uuid.uuid4().hex[:12]}")
    prompt: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    strategy: InferenceStrategy = InferenceStrategy.PARALLEL
    model_ids: List[str] = field(default_factory=list)
    max_results: int = 1
    timeout: float = 30.0
    priority: int = 1
    
    # Advanced options
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float = 0.9
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    
    # Ensemble options
    ensemble_weights: Optional[Dict[str, float]] = None
    aggregation_method: str = "best"
    
    # Metadata
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "prompt": self.prompt,
            "context": self.context,
            "strategy": self.strategy.value,
            "model_ids": self.model_ids,
            "max_results": self.max_results,
            "timeout": self.timeout,
            "priority": self.priority,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "ensemble_weights": self.ensemble_weights,
            "aggregation_method": self.aggregation_method,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class InferenceResult:
    """Result from model inference."""
    model_id: str
    request_id: str
    response: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Performance metrics
    latency: float = 0.0
    tokens_generated: int = 0
    cost: float = 0.0
    
    # Quality metrics
    confidence: float = 0.0
    relevance_score: float = 0.0
    coherence_score: float = 0.0
    
    # Status
    status: ModelStatus = ModelStatus.BUSY
    error: Optional[str] = None
    completed_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "request_id": self.request_id,
            "response": self.response,
            "metadata": self.metadata,
            "latency": self.latency,
            "tokens_generated": self.tokens_generated,
            "cost": self.cost,
            "confidence": self.confidence,
            "relevance_score": self.relevance_score,
            "coherence_score": self.coherence_score,
            "status": self.status.value,
            "error": self.error,
            "completed_at": self.completed_at,
        }


@dataclass
class EnsembleResult:
    """Aggregated result from multiple models."""
    request_id: str
    strategy: InferenceStrategy
    individual_results: List[InferenceResult] = field(default_factory=list)
    aggregated_response: str = ""
    aggregated_confidence: float = 0.0
    aggregation_metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Performance metrics
    total_latency: float = 0.0
    total_cost: float = 0.0
    models_used: int = 0
    success_rate: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "strategy": self.strategy.value,
            "individual_results": [r.to_dict() for r in self.individual_results],
            "aggregated_response": self.aggregated_response,
            "aggregated_confidence": self.aggregated_confidence,
            "aggregation_metadata": self.aggregation_metadata,
            "total_latency": self.total_latency,
            "total_cost": self.total_cost,
            "models_used": self.models_used,
            "success_rate": self.success_rate,
        }


class ModelManager:
    """Manages individual model instances and connections."""
    
    def __init__(self, config: ModelConfig):
        self.config = config
        self.status = ModelStatus.IDLE
        self.active_requests: Set[str] = set()
        self.request_semaphore = asyncio.Semaphore(config.max_concurrent)
        self.performance_history: List[float] = []
        self.error_count = 0
        self.last_error_time = 0.0
        
    async def initialize(self) -> None:
        """Initialize model connection."""
        logger.info("Initializing model %s", self.config.model_id)
        # In real implementation, this would establish connection to model
        self.status = ModelStatus.IDLE
        
    async def shutdown(self) -> None:
        """Shutdown model connection."""
        logger.info("Shutting down model %s", self.config.model_id)
        self.status = ModelStatus.MAINTENANCE
        
    async def infer(self, request: InferenceRequest) -> InferenceResult:
        """Perform inference with this model."""
        async with self.request_semaphore:
            self.active_requests.add(request.request_id)
            self.status = ModelStatus.BUSY
            
            start_time = time.time()
            
            try:
                # Simulate model inference
                await asyncio.sleep(0.5 + len(request.prompt) * 0.001)  # Simulate latency
                
                # Generate mock response
                response = f"[{self.config.model_name}] Response to: {request.prompt[:100]}..."
                
                # Calculate metrics
                latency = time.time() - start_time
                tokens_generated = len(response.split())
                cost = tokens_generated * self.config.cost_per_token
                
                result = InferenceResult(
                    model_id=self.config.model_id,
                    request_id=request.request_id,
                    response=response,
                    latency=latency,
                    tokens_generated=tokens_generated,
                    cost=cost,
                    confidence=0.8 + (self.config.weight * 0.1),  # Mock confidence
                    status=ModelStatus.IDLE,
                )
                
                # Update performance history
                self.performance_history.append(latency)
                if len(self.performance_history) > 100:
                    self.performance_history.pop(0)
                    
                return result
                
            except Exception as exc:
                self.error_count += 1
                self.last_error_time = time.time()
                
                result = InferenceResult(
                    model_id=self.config.model_id,
                    request_id=request.request_id,
                    status=ModelStatus.ERROR,
                    error=str(exc),
                    latency=time.time() - start_time,
                )
                
                return result
                
            finally:
                self.active_requests.discard(request.request_id)
                if not self.active_requests:
                    self.status = ModelStatus.IDLE
                    
    def get_average_latency(self) -> float:
        """Get average latency for this model."""
        if not self.performance_history:
            return self.config.latency_target
        return sum(self.performance_history) / len(self.performance_history)
        
    def is_healthy(self) -> bool:
        """Check if model is healthy."""
        if self.status == ModelStatus.ERROR:
            return False
            
        # Check error rate
        if self.error_count > 5 and time.time() - self.last_error_time < 300:
            return False
            
        return True


class LoadBalancer:
    """Load balancer for model selection and routing."""
    
    def __init__(self):
        self.models: Dict[str, ModelManager] = {}
        self.round_robin_index = 0
        
    def add_model(self, model_manager: ModelManager) -> None:
        """Add model to load balancer."""
        self.models[model_manager.config.model_id] = model_manager
        
    def select_model(
        self,
        request: InferenceRequest,
        strategy: str = "best"
    ) -> Optional[ModelManager]:
        """Select best model for request."""
        available_models = [
            manager for manager in self.models.values()
            if manager.is_healthy() and manager.status != ModelStatus.MAINTENANCE
        ]
        
        if not available_models:
            return None
            
        if strategy == "round_robin":
            return self._select_round_robin(available_models)
        elif strategy == "least_loaded":
            return self._select_least_loaded(available_models)
        elif strategy == "fastest":
            return self._select_fastest(available_models)
        elif strategy == "best":
            return self._select_best(available_models, request)
        else:
            return available_models[0]
            
    def _select_round_robin(self, models: List[ModelManager]) -> ModelManager:
        """Select model using round-robin."""
        model = models[self.round_robin_index % len(models)]
        self.round_robin_index += 1
        return model
        
    def _select_least_loaded(self, models: List[ModelManager]) -> ModelManager:
        """Select model with least active requests."""
        return min(models, key=lambda m: len(m.active_requests))
        
    def _select_fastest(self, models: List[ModelManager]) -> ModelManager:
        """Select model with lowest average latency."""
        return min(models, key=lambda m: m.get_average_latency())
        
    def _select_best(self, models: List[ModelManager], request: InferenceRequest) -> ModelManager:
        """Select best model based on multiple factors."""
        scored_models = []
        
        for model in models:
            score = 0.0
            
            # Load factor (lower is better)
            load_factor = 1.0 - (len(model.active_requests) / model.config.max_concurrent)
            score += load_factor * 0.3
            
            # Latency factor (lower is better)
            avg_latency = model.get_average_latency()
            latency_factor = 1.0 / (1.0 + avg_latency)
            score += latency_factor * 0.3
            
            # Model weight
            score += model.config.weight * 0.2
            
            # Priority
            score += (5 - model.config.priority) * 0.1
            
            # Error rate
            error_factor = 1.0 - (model.error_count / 10.0)
            score += max(0, error_factor) * 0.1
            
            scored_models.append((score, model))
            
        # Return model with highest score
        scored_models.sort(key=lambda x: x[0], reverse=True)
        return scored_models[0][1]


class ResultAggregator:
    """Aggregates results from multiple models."""
    
    async def aggregate_results(
        self,
        request: InferenceRequest,
        results: List[InferenceResult]
    ) -> EnsembleResult:
        """Aggregate results based on strategy."""
        successful_results = [r for r in results if r.status == ModelStatus.IDLE]
        
        if not successful_results:
            return EnsembleResult(
                request_id=request.request_id,
                strategy=request.strategy,
                individual_results=results,
                success_rate=0.0,
            )
            
        if request.strategy == InferenceStrategy.PARALLEL:
            return await self._aggregate_parallel(request, successful_results)
        elif request.strategy == InferenceStrategy.ENSEMBLE:
            return await self._aggregate_ensemble(request, successful_results)
        elif request.strategy == InferenceStrategy.MAJORITY_VOTE:
            return await self._aggregate_majority_vote(request, successful_results)
        elif request.strategy == InferenceStrategy.WEIGHTED_AVERAGE:
            return await self._aggregate_weighted_average(request, successful_results)
        else:
            # Default to best result
            return await self._aggregate_best(request, successful_results)
            
    async def _aggregate_parallel(
        self,
        request: InferenceRequest,
        results: List[InferenceResult]
    ) -> EnsembleResult:
        """Aggregate parallel results (return fastest)."""
        best_result = min(results, key=lambda r: r.latency)
        
        return EnsembleResult(
            request_id=request.request_id,
            strategy=request.strategy,
            individual_results=results,
            aggregated_response=best_result.response,
            aggregated_confidence=best_result.confidence,
            total_latency=best_result.latency,
            total_cost=best_result.cost,
            models_used=len(results),
            success_rate=len(results) / len(results),
        )
        
    async def _aggregate_ensemble(
        self,
        request: InferenceRequest,
        results: List[InferenceResult]
    ) -> EnsembleResult:
        """Aggregate ensemble results with weights."""
        weights = request.ensemble_weights or {}
        
        # Calculate weighted response
        weighted_responses = []
        total_weight = 0.0
        
        for result in results:
            weight = weights.get(result.model_id, 1.0)
            weighted_responses.append((result.response, weight, result.confidence))
            total_weight += weight
            
        # Simple weighted concatenation (in real implementation, would be more sophisticated)
        if weighted_responses:
            best_response = max(weighted_responses, key=lambda x: x[2])[0]
            avg_confidence = sum(w[2] for w in weighted_responses) / len(weighted_responses)
        else:
            best_response = ""
            avg_confidence = 0.0
            
        return EnsembleResult(
            request_id=request.request_id,
            strategy=request.strategy,
            individual_results=results,
            aggregated_response=best_response,
            aggregated_confidence=avg_confidence,
            total_latency=max(r.latency for r in results),
            total_cost=sum(r.cost for r in results),
            models_used=len(results),
            success_rate=len(results) / len(results),
        )
        
    async def _aggregate_majority_vote(
        self,
        request: InferenceRequest,
        results: List[InferenceResult]
    ) -> EnsembleResult:
        """Aggregate using majority voting."""
        # Simple implementation - in real would use semantic similarity
        responses = [r.response for r in results]
        
        # Find most common response (simplified)
        response_counts = {}
        for response in responses:
            response_counts[response] = response_counts.get(response, 0) + 1
            
        if response_counts:
            best_response = max(response_counts, key=response_counts.get)
            vote_count = response_counts[best_response]
            confidence = vote_count / len(responses)
        else:
            best_response = ""
            confidence = 0.0
            
        return EnsembleResult(
            request_id=request.request_id,
            strategy=request.strategy,
            individual_results=results,
            aggregated_response=best_response,
            aggregated_confidence=confidence,
            total_latency=max(r.latency for r in results),
            total_cost=sum(r.cost for r in results),
            models_used=len(results),
            success_rate=len(results) / len(results),
        )
        
    async def _aggregate_weighted_average(
        self,
        request: InferenceRequest,
        results: List[InferenceResult]
    ) -> EnsembleResult:
        """Aggregate using weighted average."""
        weights = request.ensemble_weights or {}
        
        # Calculate weighted confidence
        total_weight = 0.0
        weighted_confidence = 0.0
        
        for result in results:
            weight = weights.get(result.model_id, 1.0)
            weighted_confidence += result.confidence * weight
            total_weight += weight
            
        avg_confidence = weighted_confidence / total_weight if total_weight > 0 else 0.0
        
        # Select best response based on weighted confidence
        best_result = max(results, key=lambda r: r.confidence)
        
        return EnsembleResult(
            request_id=request.request_id,
            strategy=request.strategy,
            individual_results=results,
            aggregated_response=best_result.response,
            aggregated_confidence=avg_confidence,
            total_latency=max(r.latency for r in results),
            total_cost=sum(r.cost for r in results),
            models_used=len(results),
            success_rate=len(results) / len(results),
        )
        
    async def _aggregate_best(
        self,
        request: InferenceRequest,
        results: List[InferenceResult]
    ) -> EnsembleResult:
        """Aggregate by selecting best result."""
        best_result = max(results, key=lambda r: r.confidence)
        
        return EnsembleResult(
            request_id=request.request_id,
            strategy=request.strategy,
            individual_results=results,
            aggregated_response=best_result.response,
            aggregated_confidence=best_result.confidence,
            total_latency=best_result.latency,
            total_cost=best_result.cost,
            models_used=1,
            success_rate=1.0,
        )


class ParallelInferenceEngine:
    """Main parallel inference engine."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.models: Dict[str, ModelManager] = {}
        self.load_balancer = LoadBalancer()
        self.aggregator = ResultAggregator()
        self.request_queue: asyncio.Queue = asyncio.Queue()
        self.active_requests: Dict[str, InferenceRequest] = {}
        
        # Threading for CPU-bound operations
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # Statistics
        self.total_requests = 0
        self.completed_requests = 0
        self.failed_requests = 0
        
    async def initialize(self) -> None:
        """Initialize the inference engine."""
        logger.info("Initializing Parallel Inference Engine")
        
        # Initialize default models
        await self._setup_default_models()
        
        # Start request processor
        asyncio.create_task(self._request_processor())
        
        logger.info("Parallel Inference Engine initialized")
        
    async def _setup_default_models(self) -> None:
        """Setup default model configurations."""
        ollama_host = get_settings().ollama_host
        default_models = [
            ModelConfig(
                model_id="llama3.2-8b",
                model_name="Llama 3.2 8B",
                endpoint=ollama_host,
                max_concurrent=5,
                weight=1.0,
                priority=1,
                cost_per_token=0.0001,
            ),
            ModelConfig(
                model_id="llama3.2-70b",
                model_name="Llama 3.2 70B",
                endpoint=ollama_host,
                max_concurrent=2,
                weight=1.5,
                priority=2,
                cost_per_token=0.0005,
            ),
            ModelConfig(
                model_id="mistral-7b",
                model_name="Mistral 7B",
                endpoint=ollama_host,
                max_concurrent=8,
                weight=0.8,
                priority=1,
                cost_per_token=0.00008,
            ),
        ]
        
        for config in default_models:
            manager = ModelManager(config)
            await manager.initialize()
            self.models[config.model_id] = manager
            self.load_balancer.add_model(manager)
            
    async def infer(
        self,
        request: InferenceRequest
    ) -> EnsembleResult:
        """Perform parallel inference."""
        self.total_requests += 1
        self.active_requests[request.request_id] = request
        request.started_at = time.time()
        
        try:
            # Select models for inference
            if request.model_ids:
                selected_models = [
                    self.models[mid] for mid in request.model_ids
                    if mid in self.models and self.models[mid].is_healthy()
                ]
            else:
                # Auto-select models based on strategy
                selected_models = await self._select_models_for_request(request)
                
            if not selected_models:
                raise ValueError("No healthy models available")
                
            # Execute inference based on strategy
            if request.strategy == InferenceStrategy.PARALLEL:
                results = await self._execute_parallel(request, selected_models)
            elif request.strategy == InferenceStrategy.SEQUENTIAL:
                results = await self._execute_sequential(request, selected_models)
            elif request.strategy == InferenceStrategy.CASCADE:
                results = await self._execute_cascade(request, selected_models)
            else:
                # Default to parallel
                results = await self._execute_parallel(request, selected_models)
                
            # Aggregate results
            ensemble_result = await self.aggregator.aggregate_results(request, results)
            
            self.completed_requests += 1
            return ensemble_result
            
        except Exception as exc:
            self.failed_requests += 1
            logger.error("Inference failed for request %s: %s", request.request_id, exc)
            
            # Return error result
            return EnsembleResult(
                request_id=request.request_id,
                strategy=request.strategy,
                success_rate=0.0,
            )
            
        finally:
            request.completed_at = time.time()
            self.active_requests.pop(request.request_id, None)
            
    async def _select_models_for_request(
        self,
        request: InferenceRequest
    ) -> List[ModelManager]:
        """Select models for the request."""
        # Select based on strategy and request characteristics
        if request.strategy == InferenceStrategy.ENSEMBLE:
            # Use multiple models for ensemble
            available_models = list(self.load_balancer.models.values())
            healthy_models = [m for m in available_models if m.is_healthy()]
            
            # Select top 3 models
            scored_models = []
            for model in healthy_models:
                score = model.config.weight
                scored_models.append((score, model))
                
            scored_models.sort(key=lambda x: x[0], reverse=True)
            return [model for _, model in scored_models[:3]]
        else:
            # Select single best model
            model = self.load_balancer.select_model(request, "best")
            return [model] if model else []
            
    async def _execute_parallel(
        self,
        request: InferenceRequest,
        models: List[ModelManager]
    ) -> List[InferenceResult]:
        """Execute inference in parallel."""
        tasks = []
        
        for model in models:
            task = asyncio.create_task(model.infer(request))
            tasks.append(task)
            
        # Wait for all tasks with timeout
        try:
            results = await asyncio.gather(*tasks, timeout=request.timeout)
            return results
        except asyncio.TimeoutError:
            # Cancel remaining tasks
            for task in tasks:
                task.cancel()
            return []
            
    async def _execute_sequential(
        self,
        request: InferenceRequest,
        models: List[ModelManager]
    ) -> List[InferenceResult]:
        """Execute inference sequentially."""
        results = []
        
        for model in models:
            try:
                result = await model.infer(request)
                results.append(result)
                
                # If we got a good result, stop (for cascade strategy)
                if request.strategy == InferenceStrategy.CASCADE and result.confidence > 0.8:
                    break
                    
            except Exception as exc:
                logger.error("Sequential inference error: %s", exc)
                continue
                
        return results
        
    async def _execute_cascade(
        self,
        request: InferenceRequest,
        models: List[ModelManager]
    ) -> List[InferenceResult]:
        """Execute inference in cascade (try models until success)."""
        return await self._execute_sequential(request, models)
        
    async def _request_processor(self) -> None:
        """Process queued requests."""
        while True:
            try:
                request = await self.request_queue.get()
                asyncio.create_task(self.infer(request))
            except Exception as exc:
                logger.error("Request processor error: %s", exc)
                await asyncio.sleep(1.0)
                
    async def batch_infer(
        self,
        requests: List[InferenceRequest]
    ) -> List[EnsembleResult]:
        """Perform batch inference."""
        tasks = []
        
        for request in requests:
            task = asyncio.create_task(self.infer(request))
            tasks.append(task)
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter exceptions
        valid_results = []
        for result in results:
            if isinstance(result, EnsembleResult):
                valid_results.append(result)
            else:
                logger.error("Batch inference error: %s", result)
                
        return valid_results
        
    def get_engine_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        model_stats = {}
        
        for model_id, manager in self.models.items():
            model_stats[model_id] = {
                "status": manager.status.value,
                "active_requests": len(manager.active_requests),
                "average_latency": manager.get_average_latency(),
                "error_count": manager.error_count,
                "is_healthy": manager.is_healthy(),
            }
            
        return {
            "total_requests": self.total_requests,
            "completed_requests": self.completed_requests,
            "failed_requests": self.failed_requests,
            "success_rate": self.completed_requests / self.total_requests if self.total_requests > 0 else 0.0,
            "active_requests": len(self.active_requests),
            "model_stats": model_stats,
        }
        
    async def shutdown(self) -> None:
        """Shutdown the inference engine."""
        logger.info("Shutting down Parallel Inference Engine")
        
        # Shutdown all models
        for manager in self.models.values():
            await manager.shutdown()
            
        # Shutdown executor
        self.executor.shutdown(wait=True)
        
        logger.info("Parallel Inference Engine shutdown complete")


# Global engine instance
parallel_engine: Optional[ParallelInferenceEngine] = None