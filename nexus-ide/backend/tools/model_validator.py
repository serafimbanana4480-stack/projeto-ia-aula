"""Model validator for checking Ollama model availability at startup.

Validates that required models from config/models.yaml are available on the
Ollama server, with automatic fallback detection.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.config.settings import load_models_config
from backend.tools.ollama_client import OllamaClient, OllamaError

logger = logging.getLogger(__name__)


@dataclass
class ModelStatus:
    """Status of a single model."""
    model_id: str
    available: bool
    fallback_available: bool = False
    fallback_model: str | None = None
    error: str | None = None


@dataclass
class ValidationResult:
    """Result of model validation."""
    healthy: bool
    models: list[ModelStatus] = field(default_factory=list)
    missing_models: list[str] = field(default_factory=list)
    available_models: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "models": [
                {
                    "model_id": m.model_id,
                    "available": m.available,
                    "fallback_available": m.fallback_available,
                    "fallback_model": m.fallback_model,
                    "error": m.error,
                }
                for m in self.models
            ],
            "missing_models": self.missing_models,
            "available_models": self.available_models,
            "warnings": self.warnings,
        }


class ModelValidator:
    """Validates Ollama model availability at startup.
    
    Usage:
        validator = ModelValidator(ollama_client)
        result = await validator.validate_all()
        if not result.healthy:
            logger.warning("Some models are missing: %s", result.missing_models)
    """
    
    def __init__(self, client: OllamaClient, config: dict[str, Any] | None = None):
        self._client = client
        self._config = config or load_models_config()
        self._cached_available_models: list[str] | None = None
    
    async def get_available_models(self, use_cache: bool = True) -> list[str]:
        """Get list of available models from Ollama server.
        
        Args:
            use_cache: If True, use cached result from previous call.
            
        Returns:
            List of model names available on server.
        """
        if use_cache and self._cached_available_models is not None:
            return self._cached_available_models
        
        try:
            models = await self._client.list_models()
            self._cached_available_models = models
            return models
        except OllamaError as e:
            logger.error("Failed to list models from Ollama: %s", e)
            return []
    
    async def check_model(self, model_id: str, fallback_id: str | None = None) -> ModelStatus:
        """Check if a specific model is available.
        
        Args:
            model_id: Primary model ID to check.
            fallback_id: Optional fallback model ID.
            
        Returns:
            ModelStatus with availability information.
        """
        available_models = await self.get_available_models()
        
        # Check primary model
        primary_available = self._model_in_list(model_id, available_models)
        
        # Check fallback if primary not available
        fallback_available = False
        if not primary_available and fallback_id:
            fallback_available = self._model_in_list(fallback_id, available_models)
        
        return ModelStatus(
            model_id=model_id,
            available=primary_available,
            fallback_available=fallback_available,
            fallback_model=fallback_id if fallback_available else None,
            error=None if primary_available or fallback_available else "Model not found",
        )
    
    def _model_in_list(self, model_id: str, available_models: list[str]) -> bool:
        """Check if model is in available list (with base name matching)."""
        if model_id in available_models:
            return True
        # Also match base name (e.g., 'qwen3.5' matches 'qwen3.5:latest')
        base_name = model_id.split(":")[0]
        return any(m.startswith(base_name + ":") or m == base_name for m in available_models)
    
    async def validate_all(self) -> ValidationResult:
        """Validate all models from config.
        
        Returns:
            ValidationResult with status of all models.
        """
        models_config = self._config.get("models", {})
        result = ValidationResult(healthy=True)
        
        # First, check if Ollama is reachable
        if not await self._client.ping():
            result.healthy = False
            result.warnings.append("Ollama server is not reachable")
            return result
        
        # Check each model
        for _model_key, model_cfg in models_config.items():
            model_id = model_cfg.get("id", "")
            fallback_id = model_cfg.get("fallback_id")
            
            if not model_id:
                continue
            
            status = await self.check_model(model_id, fallback_id)
            status.model_id = model_id  # Use actual model_id, not key
            result.models.append(status)
            
            if status.available:
                result.available_models.append(model_id)
            elif status.fallback_available:
                result.available_models.append(fallback_id)
                result.warnings.append(
                    f"Model '{model_id}' not available, using fallback '{fallback_id}'"
                )
            else:
                result.missing_models.append(model_id)
                result.healthy = False
                result.warnings.append(
                    f"Model '{model_id}' and fallback '{fallback_id}' both unavailable"
                )
        
        return result
    
    async def get_recommended_model(self, model_key: str) -> str | None:
        """Get the recommended available model for a given model key.
        
        Args:
            model_key: Key from config/models.yaml (e.g., 'coder', 'fast').
            
        Returns:
            Available model ID (primary or fallback), or None if neither available.
        """
        models_config = self._config.get("models", {})
        model_cfg = models_config.get(model_key, {})
        
        model_id = model_cfg.get("id")
        fallback_id = model_cfg.get("fallback_id")
        
        if not model_id:
            return None
        
        available_models = await self.get_available_models()
        
        if self._model_in_list(model_id, available_models):
            return model_id
        if fallback_id and self._model_in_list(fallback_id, available_models):
            return fallback_id
        
        return None
    
    def clear_cache(self) -> None:
        """Clear cached model list."""
        self._cached_available_models = None


async def validate_models_on_startup(client: OllamaClient) -> ValidationResult:
    """Convenience function to validate models at startup.
    
    Logs warnings for missing models but does not raise exceptions.
    
    Args:
        client: OllamaClient instance.
        
    Returns:
        ValidationResult with model status.
    """
    validator = ModelValidator(client)
    result = await validator.validate_all()
    
    if result.warnings:
        for warning in result.warnings:
            logger.warning("Model validation: %s", warning)
    
    if result.missing_models:
        logger.error(
            "Missing models: %s. Some features may not work.",
            ", ".join(result.missing_models)
        )
    else:
        logger.info(
            "Model validation complete. %d models available.",
            len(result.available_models)
        )
    
    return result
