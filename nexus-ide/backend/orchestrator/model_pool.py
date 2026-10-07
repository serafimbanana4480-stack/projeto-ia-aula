"""Model Pool Manager - Intelligent model preloading and resource management.

Eliminates cold starts by maintaining a warm pool of frequently used models,
with dynamic scaling based on usage patterns and resource constraints.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from backend.config.settings import get_model_config
from backend.tools.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class ModelStatus(str, Enum):
    COLD = "cold"          # Not loaded
    LOADING = "loading"    # Currently loading
    WARM = "warm"          # Loaded and ready
    IDLE = "idle"          # Loaded but not used recently
    UNLOADING = "unloading"  # Being unloaded to free resources


@dataclass
class ModelMetrics:
    """Usage metrics for a specific model."""
    load_count: int = 0
    total_requests: int = 0
    avg_response_time_ms: float = 0.0
    last_used: float = 0.0
    load_time_ms: float = 0.0
    memory_usage_mb: float = 0.0
    error_rate: float = 0.0


@dataclass
class PooledModel:
    """A model instance managed by the pool."""
    model_id: str
    model_key: str
    status: ModelStatus = ModelStatus.COLD
    metrics: ModelMetrics = field(default_factory=ModelMetrics)
    load_task: asyncio.Task | None = None
    last_access: float = field(default_factory=time.time)
    reference_count: int = 0
    
    def __post_init__(self) -> None:
        self.last_access = time.time()


class ModelPool:
    """Intelligent model pool with preloading and lifecycle management.
    
    Features:
    - Proactive preloading based on usage patterns
    - Dynamic resource allocation
    - Automatic cold start elimination
    - Memory pressure handling
    - Usage pattern learning
    """
    
    def __init__(
        self,
        ollama_client: OllamaClient,
        *,
        max_memory_mb: int = 16384,  # 16GB default
        max_concurrent_loads: int = 3,
        idle_timeout_seconds: int = 300,  # 5 minutes
        preload_threshold: float = 0.7,  # Preload if usage probability > 70%
    ) -> None:
        self.ollama = ollama_client
        self.max_memory_mb = max_memory_mb
        self.max_concurrent_loads = max_concurrent_loads
        self.idle_timeout_seconds = idle_timeout_seconds
        self.preload_threshold = preload_threshold
        
        # Model registry
        self._models: dict[str, PooledModel] = {}
        self._loading_tasks: set[asyncio.Task] = set()
        self._memory_used_mb = 0.0
        
        # Usage tracking
        self._usage_history: deque = deque(maxlen=1000)
        self._hourly_patterns: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        
        # Background tasks
        self._maintenance_task: asyncio.Task | None = None
        self._running = False
        
        # Load model configurations
        self._model_configs = get_model_config()
        
    async def start(self) -> None:
        """Start the model pool and background maintenance."""
        if self._running:
            return
            
        self._running = True
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())
        
        # Initialize model registry
        await self._initialize_models()
        
        # Preload high-priority models
        await self._preload_critical_models()
        
        logger.info("Model Pool started with %d models", len(self._models))
    
    async def stop(self) -> None:
        """Stop the model pool and cleanup resources."""
        self._running = False
        
        if self._maintenance_task:
            self._maintenance_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._maintenance_task
        
        # Cancel all loading tasks
        for task in self._loading_tasks:
            task.cancel()
        
        # Wait for loading tasks to complete
        if self._loading_tasks:
            await asyncio.gather(*self._loading_tasks, return_exceptions=True)
        
        logger.info("Model Pool stopped")
    
    async def get_model(self, model_key: str) -> str | None:
        """Get a warmed-up model by key, loading if necessary."""
        if model_key not in self._models:
            logger.warning("Model key %s not found in registry", model_key)
            return None
        
        model = self._models[model_key]
        model.reference_count += 1
        model.last_access = time.time()
        
        # Track usage
        self._track_usage(model_key)
        
        # If model is cold, start loading
        if model.status == ModelStatus.COLD:
            await self._load_model(model)
        
        # Wait for model to be ready
        if model.status == ModelStatus.LOADING and model.load_task:
            await model.load_task
        
        # Update metrics
        model.metrics.total_requests += 1
        model.metrics.last_used = time.time()
        
        return model.model_id if model.status == ModelStatus.WARM else None
    
    async def release_model(self, model_key: str) -> None:
        """Release a model reference."""
        if model_key in self._models:
            self._models[model_key].reference_count = max(
                0, self._models[model_key].reference_count - 1
            )
    
    async def _initialize_models(self) -> None:
        """Initialize the model registry from configurations."""
        for model_key, config in self._model_configs.items():
            if isinstance(config, dict) and "id" in config:
                model = PooledModel(
                    model_id=config["id"],
                    model_key=model_key,
                )
                self._models[model_key] = model
                
                # Estimate memory usage based on model size
                if "7b" in config["id"].lower():
                    model.metrics.memory_usage_mb = 5200
                elif "14b" in config["id"].lower():
                    model.metrics.memory_usage_mb = 10400
                elif "27b" in config["id"].lower():
                    model.metrics.memory_usage_mb = 20000
                elif "32b" in config["id"].lower():
                    model.metrics.memory_usage_mb = 24000
                else:
                    model.metrics.memory_usage_mb = 3000  # Default for smaller models
    
    async def _preload_critical_models(self) -> None:
        """Preload models based on usage patterns and priority."""
        # Always keep MICRO and FAST models warm (high frequency)
        critical_models = ["micro", "fast"]
        
        for model_key in critical_models:
            if model_key in self._models:
                model = self._models[model_key]
                if model.status == ModelStatus.COLD:
                    await self._load_model(model)
    
    async def _load_model(self, model: PooledModel) -> None:
        """Load a model into the pool."""
        if model.status != ModelStatus.COLD:
            return
        
        # Check memory constraints
        if not self._can_allocate_memory(model.metrics.memory_usage_mb):
            # Free up memory by unloading idle models
            await self._free_idle_memory(model.metrics.memory_usage_mb)
        
        # Check concurrent loading limit
        if len(self._loading_tasks) >= self.max_concurrent_loads:
            logger.info("Max concurrent loads reached, queuing %s", model.model_key)
            # Wait for a loading slot
            await self._wait_for_load_slot()
        
        model.status = ModelStatus.LOADING
        start_time = time.time()
        
        async def load_task():
            try:
                # Preload by making a minimal request
                await self.ollama.chat_complete(
                    model=model.model_id,
                    messages=[{"role": "user", "content": "test"}],
                    options={"num_predict": 1}
                )
                
                load_time = (time.time() - start_time) * 1000
                model.metrics.load_time_ms = load_time
                model.metrics.load_count += 1
                model.status = ModelStatus.WARM
                model.last_access = time.time()
                
                self._memory_used_mb += model.metrics.memory_usage_mb
                
                logger.info(
                    "Model %s loaded in %.0fms (memory: %.0fMB)",
                    model.model_key, load_time, model.metrics.memory_usage_mb
                )
                
            except Exception as e:
                logger.error("Failed to load model %s: %s", model.model_key, e)
                model.status = ModelStatus.COLD
                model.metrics.error_rate += 1
            finally:
                self._loading_tasks.discard(asyncio.current_task())
        
        task = asyncio.create_task(load_task())
        model.load_task = task
        self._loading_tasks.add(task)
    
    def _can_allocate_memory(self, required_mb: float) -> bool:
        """Check if we have enough memory for a model."""
        return (self._memory_used_mb + required_mb) <= self.max_memory_mb
    
    async def _free_idle_memory(self, required_mb: float) -> None:
        """Free up memory by unloading idle models."""
        # Sort models by last access time (oldest first)
        idle_models = [
            (model_key, model) for model_key, model in self._models.items()
            if model.status == ModelStatus.WARM and model.reference_count == 0
        ]
        idle_models.sort(key=lambda x: x[1].last_access)
        
        freed_mb = 0.0
        for model_key, model in idle_models:
            if freed_mb >= required_mb:
                break
            
            await self._unload_model(model)
            freed_mb += model.metrics.memory_usage_mb
            logger.info("Unloaded idle model %s (freed %.0fMB)", model_key, model.metrics.memory_usage_mb)
    
    async def _unload_model(self, model: PooledModel) -> None:
        """Unload a model from memory."""
        if model.status == ModelStatus.WARM:
            model.status = ModelStatus.UNLOADING
            # Note: Ollama doesn't have explicit unload, but we track it internally
            self._memory_used_mb -= model.metrics.memory_usage_mb
            model.status = ModelStatus.COLD
    
    async def _wait_for_load_slot(self) -> None:
        """Wait for an available loading slot."""
        while len(self._loading_tasks) >= self.max_concurrent_loads:
            await asyncio.sleep(0.1)
    
    def _track_usage(self, model_key: str) -> None:
        """Track model usage for pattern analysis."""
        current_hour = time.localtime().tm_hour
        self._hourly_patterns[current_hour][model_key] += 1
        self._usage_history.append((time.time(), model_key))
    
    async def _maintenance_loop(self) -> None:
        """Background maintenance loop."""
        while self._running:
            try:
                await self._perform_maintenance()
                await asyncio.sleep(60)  # Run every minute
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Maintenance loop error: %s", e)
                await asyncio.sleep(60)
    
    async def _perform_maintenance(self) -> None:
        """Perform periodic maintenance tasks."""
        current_time = time.time()
        
        # Check for idle models
        for model_key, model in self._models.items():
            if (model.status == ModelStatus.WARM and 
                model.reference_count == 0 and
                (current_time - model.last_access) > self.idle_timeout_seconds):
                
                # Don't unload critical models
                if model_key not in ["micro", "fast"]:
                    await self._unload_model(model)
                    model.status = ModelStatus.IDLE
                    logger.info("Model %s marked as idle", model_key)
        
        # Predictive preloading based on time patterns
        await self._predictive_preload()
    
    async def _predictive_preload(self) -> None:
        """Preload models based on usage patterns."""
        current_hour = time.localtime().tm_hour
        
        # Calculate usage probability for each model
        for model_key, model in self._models.items():
            if model.status != ModelStatus.COLD:
                continue
            
            # Get historical usage for this hour
            hourly_usage = self._hourly_patterns.get(current_hour, {})
            total_usage = sum(hourly_usage.values())
            
            if total_usage > 0:
                usage_probability = hourly_usage.get(model_key, 0) / total_usage
                
                if usage_probability > self.preload_threshold:
                    logger.info(
                        "Predictive preloading %s (probability: %.2f)",
                        model_key, usage_probability
                    )
                    await self._load_model(model)
    
    def get_stats(self) -> dict[str, Any]:
        """Get pool statistics."""
        stats = {
            "total_models": len(self._models),
            "warm_models": sum(1 for m in self._models.values() if m.status == ModelStatus.WARM),
            "cold_models": sum(1 for m in self._models.values() if m.status == ModelStatus.COLD),
            "loading_models": sum(1 for m in self._models.values() if m.status == ModelStatus.LOADING),
            "memory_used_mb": self._memory_used_mb,
            "memory_available_mb": self.max_memory_mb - self._memory_used_mb,
            "active_loading_tasks": len(self._loading_tasks),
        }
        
        # Add per-model stats
        stats["models"] = {}
        for model_key, model in self._models.items():
            stats["models"][model_key] = {
                "status": model.status.value,
                "memory_mb": model.metrics.memory_usage_mb,
                "total_requests": model.metrics.total_requests,
                "load_count": model.metrics.load_count,
                "avg_load_time_ms": model.metrics.load_time_ms,
                "reference_count": model.reference_count,
            }
        
        return stats


# Global model pool instance
_model_pool: ModelPool | None = None


async def get_model_pool() -> ModelPool:
    """Get the global model pool instance."""
    global _model_pool
    if _model_pool is None:
        from backend.config.settings import get_settings
        settings = get_settings()
        ollama = OllamaClient(settings.ollama_host)
        _model_pool = ModelPool(ollama)
        await _model_pool.start()
    return _model_pool
