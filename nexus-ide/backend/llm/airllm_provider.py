"""AirLLM provider — layer-sharded local LLM inference with async wrapper.

Replaces Ollama with AirLLM, which loads models layer-by-layer from disk,
allowing massive models (70B+) to run on limited VRAM (4GB+) without
quantization during inference.

Architecture:
- Model weights are split into per-layer shards on disk (one-time setup).
- During forward pass only ONE layer resides in GPU/CPU memory at a time.
- All calls are wrapped in asyncio.to_thread() to avoid blocking the event loop.
- Streaming is simulated by generating the full response then yielding tokens
  with small delays — AirLLM's forward() is too expensive to run per-token.
- Embeddings are served via a lightweight HuggingFace sentence-transformer
  model kept in memory separately from the generation model.

Windows notes:
- torch.compile is disabled (not fully supported on Windows).
- malloc_trim Linux call in AirLLM silently fails; gc.collect() still runs.
- Prefetching requires CUDA; CPU inference is slower but functional.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import os
import re
import sys
import threading
import time
import warnings
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

# Lazy imports for torch/transformers to avoid loading heavy frameworks at import time
# and to work around Python 3.14 compatibility issues with some transformers versions.

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional AirLLM import with graceful fallback
# ---------------------------------------------------------------------------
try:
    from airllm import AutoModel as AirAutoModel  # type: ignore[import-untyped]

    AIRLLM_AVAILABLE = True
except Exception as _airllm_exc:  # noqa: BLE001
    logger.warning("AirLLM not available: %s", _airllm_exc)
    AirAutoModel = None  # type: ignore[misc,assignment]
    AIRLLM_AVAILABLE = False

# Optional sentence-transformers for embeddings
try:
    from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except Exception as _st_exc:  # noqa: BLE001
    logger.warning("sentence-transformers not available: %s", _st_exc)
    SentenceTransformer = None  # type: ignore[misc,assignment]
    SENTENCE_TRANSFORMERS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Compatibility dataclass (replaces ChatMessage from ollama_client)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatMessage:
    """A single turn in a chat exchange."""

    role: str  # "system" | "user" | "assistant"
    content: str
    timestamp: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content, "timestamp": self.timestamp}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LocalLLMError(RuntimeError):
    """Raised when the local LLM engine returns an error."""

    pass


class LocalLLMConnectionError(LocalLLMError):
    """Raised when the local LLM model cannot be loaded."""

    pass


class LocalLLMModelError(LocalLLMError):
    """Raised when a requested model is not available."""

    pass


# ---------------------------------------------------------------------------
# Circuit breaker (kept for resilience parity with old OllamaProvider)
# ---------------------------------------------------------------------------

from enum import Enum


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Simple circuit breaker for local LLM resilience."""

    def __init__(self, failure_threshold: int = 5, reset_timeout: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self._lock = threading.Lock()

    def record_success(self) -> None:
        with self._lock:
            self.failure_count = 0
            if self.state != CircuitState.CLOSED:
                self.state = CircuitState.CLOSED
                logger.info("Circuit breaker closed")

    def record_failure(self) -> None:
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                if self.state != CircuitState.OPEN:
                    self.state = CircuitState.OPEN
                    logger.error(
                        "Circuit breaker opened after %d consecutive failures",
                        self.failure_count,
                    )

    def can_execute(self) -> bool:
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time >= self.reset_timeout:
                    self.state = CircuitState.HALF_OPEN
                    logger.info("Circuit breaker entering half-open state")
                    return True
                return False
            return True


# ---------------------------------------------------------------------------
# Model registry & cache
# ---------------------------------------------------------------------------

# On Windows, the default HF hub cache uses symlinks which require admin
# privileges. ``scripts/install-models.py`` populates this directory with
# COPIES (no symlinks) so the airllm provider can load models without
# symlink issues. The default location can be overridden via the
# ``NEXUS_AIRLLM_MODELS_DIR`` environment variable.
_LOCAL_MODELS_DIR: str = os.environ.get(
    "NEXUS_AIRLLM_MODELS_DIR",
    str(Path.home() / ".cache" / "huggingface" / "local-models"),
)


def _resolve_local_path(model_id: str) -> str | None:
    """Return the absolute local path of a model directory if it exists.

    Lookup order:
      1. ``_LOCAL_MODELS_DIR/<model_id>/`` — populated by
         ``scripts/install-models.py`` (no symlinks, safe on Windows).
      2. ``~/.cache/huggingface/hub/models--<model_id>/snapshots/<rev>/`` —
         the default HF hub cache (uses symlinks; works on Linux/Mac,
         requires admin on Windows).

    Returns the absolute path if either contains model weights, else None.
    """
    # 1. local-models/<model_id>/ (preferred — copies, no symlinks)
    candidate = Path(_LOCAL_MODELS_DIR) / model_id
    if candidate.is_dir():
        for f in candidate.iterdir():
            if f.suffix in (".safetensors", ".bin") and f.stat().st_size > 1024:
                return str(candidate)

    # 2. HF hub cache (works on Linux/Mac; on Windows only if symlinks succeeded)
    safe_id = model_id.replace("/", "--")
    hub_dir = Path.home() / ".cache" / "huggingface" / "hub" / f"models--{safe_id}"
    if hub_dir.is_dir():
        snapshots_dir = hub_dir / "snapshots"
        if snapshots_dir.is_dir():
            for rev in snapshots_dir.iterdir():
                if rev.is_dir():
                    for f in rev.iterdir():
                        # On Windows, f may be a broken symlink — check both
                        # the link itself and its target.
                        size = 0
                        try:
                            size = f.stat().st_size
                            if size == 0 and f.is_symlink():
                                target = f.resolve()
                                if target.exists():
                                    size = target.stat().st_size
                        except OSError:
                            size = 0
                        if (
                            f.suffix in (".safetensors", ".bin")
                            and size > 1024
                        ):
                            return str(rev)
    return None


# Map friendly Nexus model IDs → HuggingFace repo IDs (or local paths)
DEFAULT_MODEL_REGISTRY: dict[str, str] = {
    # ─── Modern aliases (preferred) ────────────────────────────────────
    # Small/fast models (CPU-friendly)
    "qwen3.5:2b": "Qwen/Qwen2.5-0.5B-Instruct",
    "qwen3.5:4b": "Qwen/Qwen2.5-1.5B-Instruct",
    "qwen3.5:9b": "Qwen/Qwen2.5-7B-Instruct",
    "qwen3.5:27b": "Qwen/Qwen2.5-14B-Instruct",
    "qwen3-coder:7b": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "qwen3-coder:30b": "Qwen/Qwen2.5-Coder-32B-Instruct",
    "deepseek-r1:8b": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
    "mistral-small:latest": "mistralai/Mistral-7B-Instruct-v0.3",
    "qwen3-vl:7b": "Qwen/Qwen2-VL-7B-Instruct",
    # Embedding models
    "qwen3-embedding:4b": "sentence-transformers/all-MiniLM-L6-v2",
    "nomic-embed-text": "sentence-transformers/all-MiniLM-L6-v2",
    # ─── Legacy aliases (backwards-compat with models.yaml) ────────────
    # The original `config/models.yaml` still uses Ollama tag names.
    # Map them to the corresponding HuggingFace repo IDs so agent tests
    # and runtime calls work without modifying models.yaml.
    "qwen2.5:0.5b": "Qwen/Qwen2.5-0.5B-Instruct",
    "qwen2.5:1.5b": "Qwen/Qwen2.5-1.5B-Instruct",
    "qwen2.5:3b": "Qwen/Qwen2.5-3B-Instruct",
    "qwen2.5:7b": "Qwen/Qwen2.5-7B-Instruct",
    "qwen2.5:14b": "Qwen/Qwen2.5-14B-Instruct",
    "qwen2.5:32b": "Qwen/Qwen2.5-32B-Instruct",
    "qwen2.5-coder:1.5b": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
    "qwen2.5-coder:3b": "Qwen/Qwen2.5-Coder-3B-Instruct",
    "qwen2.5-coder:7b": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "qwen2.5-coder:32b": "Qwen/Qwen2.5-Coder-32B-Instruct",
    "deepseek-r1:1.5b": "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
    "deepseek-r1:3b": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
    "deepseek-r1:7b": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
    # ─── Semantic aliases (used by agent registry) ─────────────────────
    "nano": "Qwen/Qwen2.5-0.5B-Instruct",
    "small": "Qwen/Qwen2.5-7B-Instruct",
    "medium": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "large": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
    "expert": "Qwen/Qwen2.5-Coder-32B-Instruct",
    "vision": "Qwen/Qwen2-VL-7B-Instruct",
    "embed": "sentence-transformers/all-MiniLM-L6-v2",
    "dashboard": "Qwen/Qwen2.5-1.5B-Instruct",
    "micro": "Qwen/Qwen2.5-0.5B-Instruct",
    "fast": "Qwen/Qwen2.5-7B-Instruct",
    "coder": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "reasoning": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
    "deep": "Qwen/Qwen2.5-14B-Instruct",
    # Quantized 3B — recommended on 8GB VRAM GPUs (4-bit fits in ~3GB).
    # Use compression='4bit' in AirLLMProvider to enable bitsandbytes NF4.
    "q3b-4bit": "Qwen/Qwen2.5-3B-Instruct",
    "coder3b-4bit": "Qwen/Qwen2.5-Coder-3B-Instruct",
}

# LRU cache with TTL: model_id -> (model, last_used_timestamp)
_model_cache: dict[str, Any] = {}
_model_cache_times: dict[str, float] = {}
_model_lock = threading.RLock()
_MAX_CACHED_MODELS = 3
_MODEL_CACHE_TTL_SECONDS = 3600  # 1 hour

# Embedding model cache
_embedding_model_cache: dict[str, Any] = {}

def _detect_device() -> str:
    try:
        import torch
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"

_DEFAULT_DEVICE = _detect_device()
logger.info("AirLLM default device: %s", _DEFAULT_DEVICE)


def _resolve_model_id(model: str, registry: dict[str, str] | None = None) -> str:
    """Resolve a Nexus model alias to a HuggingFace repo ID or local path.

    Lookup order:
      1. If the input already looks like a local path → return as-is.
      2. Look in the ``DEFAULT_MODEL_REGISTRY`` for an alias.
      3. Try the on-disk ``_LOCAL_MODELS_DIR`` (where install-models.py
         writes copies). If the resolved repo ID has a local copy,
         return its absolute path so the loader can use it directly
         without needing Hub access.
      4. Otherwise return the registry value (Hub repo ID).
    """
    # Already a local path?
    if model.startswith((".", "/", "\\", "C:", "D:")) and Path(model).exists():
        return model

    reg = registry or DEFAULT_MODEL_REGISTRY
    resolved = reg.get(model, model)

    # Check if the resolved ID (or the original model id) has a local copy
    for candidate in (resolved, model):
        local = _resolve_local_path(candidate)
        if local:
            return local

    return resolved


def _get_dtype(device: str) -> Any:
    """Pick appropriate dtype for the device."""
    import torch
    if device.startswith("cuda"):
        return torch.float16
    return torch.float32


# ---------------------------------------------------------------------------
# AirLLM model loader
# ---------------------------------------------------------------------------

class _DirectHFModel:
    """Wrapper for direct HuggingFace transformers loading (no layer sharding).

    Used as fallback when AirLLM fails because the model is not sharded
    (missing model.safetensors.index.json). Also supports bitsandbytes
    4-bit / 8-bit quantization via the ``compression`` parameter.
    """

    def __init__(
        self,
        model_path: str,
        device: str = "cpu",
        compression: str | None = None,
    ) -> None:
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import torch
        self.device = device
        self.compression = (compression or "").lower() or None
        is_cuda = device.startswith("cuda")

        if is_cuda:
            self.dtype = torch.float16
        else:
            self.dtype = torch.float32

        # Determine quantization kwargs
        quant_kwargs: dict[str, Any] = {}
        if self.compression in ("4bit", "8bit"):
            if not is_cuda:
                logger.warning(
                    "Compression=%s requested but device=%s is CPU. "
                    "bitsandbytes quantization requires CUDA — falling back to %s.",
                    self.compression, device, self.dtype,
                )
            else:
                try:
                    import bitsandbytes  # noqa: F401

                    if self.compression == "4bit":
                        quant_kwargs = {
                            "load_in_4bit": True,
                            "bnb_4bit_compute_dtype": torch.float16,
                            "bnb_4bit_quant_type": "nf4",
                            "bnb_4bit_use_double_quant": True,
                        }
                    else:  # 8bit
                        quant_kwargs = {"load_in_8bit": True}
                    logger.info(
                        "Loading model with bitsandbytes %s quantization",
                        self.compression,
                    )
                except ImportError:
                    logger.warning(
                        "bitsandbytes not installed — cannot use %s compression. "
                        "Falling back to %s.",
                        self.compression, self.dtype,
                    )

        logger.info(
            "Loading model directly via transformers: %s (device=%s, dtype=%s, compression=%s)",
            model_path, device, self.dtype, self.compression or "none",
        )
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_path, trust_remote_code=True
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=self.dtype,
            trust_remote_code=True,
            device_map="auto" if is_cuda else None,
            **quant_kwargs,
        )
        if not is_cuda and not quant_kwargs:
            self.model = self.model.to(device)
        self.model.eval()
        logger.info("Direct model loaded: %s", model_path)

    def generate(self, input_ids, **kwargs):
        import torch
        input_ids = input_ids.to(self.device)
        with torch.inference_mode():
            return self.model.generate(input_ids, **kwargs)


def _load_airllm_model(model_path: str, device: str = _DEFAULT_DEVICE, compression: str | None = None) -> Any:
    """Synchronous model loader used inside asyncio.to_thread().

    Tries AirLLM first, falls back to direct transformers loading if the model
    is not sharded (missing model.safetensors.index.json).
    """
    if not AIRLLM_AVAILABLE or AirAutoModel is None:
        raise LocalLLMConnectionError(
            "AirLLM is not installed. Run: pip install airllm"
        )

    dtype = _get_dtype(device)
    logger.info("Loading AirLLM model: %s (device=%s, dtype=%s, compression=%s)", model_path, device, dtype, compression)

    kwargs: dict[str, Any] = {
        "device": device,
        "dtype": dtype,
        "max_seq_len": 4096,
        "profiling_mode": False,
        "prefetching": str(device).startswith("cuda"),
        "delete_original": False,
    }
    if compression:
        kwargs["compression"] = compression

    # Check whether the model is already on disk (preferred — bypasses
    # AirLLM's sharding which has Windows path / disk-space issues).
    local_path = _resolve_local_path(model_path)
    if local_path and Path(local_path).is_dir():
        # Model exists on disk as a local directory. AirLLM's
        # ``from_pretrained`` only accepts Hub repo IDs and breaks on
        # Windows paths (e.g. ``C:\...``). When we have a verified local
        # copy, we skip the sharding path entirely and use the direct
        # transformers loader — the trade-off is no layer-by-layer memory
        # saving, but the model loads reliably and is fast on CPU.
        logger.info(
            "Local model found at %s. Using direct transformers loader "
            "(bypasses AirLLM sharding for Windows-path compat).",
            local_path,
        )
        return _DirectHFModel(local_path, device=device, compression=compression)

    # No local copy — try AirLLM (which will shard for low-RAM systems).
    # Fall back to direct HF if AirLLM fails (sharded-model errors,
    # insufficient disk space, OOM during shard split, Windows path issues).
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = AirAutoModel.from_pretrained(model_path, **kwargs)
        logger.info("AirLLM model loaded: %s", model_path)
        return model
    except Exception as exc:
        err_msg = (str(exc) + " " + type(exc).__name__).lower()
        if any(
            k in err_msg
            for k in (
                "safetensors",
                "index.json",
                "_is_stateful",
                "list index out of range",
                "shard",
                "notenoughspace",
                "not enough space",
                "out of memory",
                "compression",
                "alphanumeric chars",
                "hfvalidationerror",
                "repo id must use",
            )
        ):
            logger.warning(
                "AirLLM failed for %s (%s). Falling back to direct transformers loading.",
                model_path, type(exc).__name__,
            )
            return _DirectHFModel(model_path, device=device, compression=compression)
        raise


def _unload_model(model_id: str) -> None:
    """Remove a model from the cache and free memory."""
    with _model_lock:
        entry = _model_cache.pop(model_id, None)
        _model_cache_times.pop(model_id, None)
    if entry is not None:
        try:
            del entry
        except Exception:
            pass
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        logger.info("Unloaded model: %s", model_id)


def _get_cached_model(model_id: str, device: str = _DEFAULT_DEVICE, compression: str | None = None) -> Any:
    """Get or create a cached AirLLM model with LRU eviction."""
    cache_key = f"{model_id}:{device}:{compression or 'none'}"
    now = time.time()

    with _model_lock:
        # Evict expired entries
        expired = [
            k for k, t in _model_cache_times.items()
            if now - t > _MODEL_CACHE_TTL_SECONDS
        ]
        for k in expired:
            _model_cache.pop(k, None)
            _model_cache_times.pop(k, None)

        # Evict oldest if over limit
        while len(_model_cache) >= _MAX_CACHED_MODELS:
            oldest_key = min(_model_cache_times, key=_model_cache_times.get)
            _model_cache.pop(oldest_key, None)
            _model_cache_times.pop(oldest_key, None)
            logger.info("Evicted oldest model from cache: %s", oldest_key)

        model = _model_cache.get(cache_key)
        if model is not None:
            _model_cache_times[cache_key] = now
            return model

    # Load outside the lock to avoid blocking other threads
    model = _load_airllm_model(model_id, device=device, compression=compression)
    with _model_lock:
        _model_cache[cache_key] = model
        _model_cache_times[cache_key] = now
    return model


# ---------------------------------------------------------------------------
# Embedding model loader
# ---------------------------------------------------------------------------

def _load_embedding_model(model_path: str, device: str = _DEFAULT_DEVICE) -> Any:
    """Load a sentence-transformers model for embeddings."""
    if SENTENCE_TRANSFORMERS_AVAILABLE and SentenceTransformer is not None:
        # sentence-transformers handles device internally
        return SentenceTransformer(model_path, device=device)

    # Fallback: use HuggingFace AutoModel directly
    from transformers import AutoModel as HFAutoModel, AutoTokenizer as HFAutoTokenizer
    tokenizer = HFAutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    model = HFAutoModel.from_pretrained(model_path, trust_remote_code=True)
    import torch
    model.to(device)
    model.eval()
    return {"model": model, "tokenizer": tokenizer, "device": device}


def _get_cached_embedding_model(model_id: str, device: str = _DEFAULT_DEVICE) -> Any:
    """Get or create a cached embedding model."""
    cache_key = f"emb:{model_id}:{device}"
    model = _embedding_model_cache.get(cache_key)
    if model is not None:
        return model
    model = _load_embedding_model(model_id, device=device)
    _embedding_model_cache[cache_key] = model
    return model


# ---------------------------------------------------------------------------
# Generation helpers (sync, run inside thread)
# ---------------------------------------------------------------------------

def _sync_chat_complete(
    model: Any,
    messages: list[dict[str, str]],
    max_new_tokens: int = 512,
    temperature: float = 0.7,
    top_p: float = 0.9,
    **kwargs: Any,
) -> str:
    """Synchronous chat completion using AirLLM."""
    # Format messages into a single prompt string
    prompt_parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            prompt_parts.append(f"System: {content}")
        elif role == "user":
            prompt_parts.append(f"User: {content}")
        elif role == "assistant":
            prompt_parts.append(f"Assistant: {content}")
    prompt_parts.append("Assistant:")
    prompt = "\n".join(prompt_parts)

    # Tokenize
    tokenizer = model.tokenizer
    input_tokens = tokenizer(
        prompt,
        return_tensors="pt",
        return_attention_mask=False,
        truncation=True,
        max_length=4096,
        padding=False,
    )

    input_ids = input_tokens["input_ids"]
    import torch
    if hasattr(model, "running_device") and str(model.running_device).startswith("cuda"):
        input_ids = input_ids.cuda()
    else:
        target_device = getattr(model, "device", None) or "cpu"
        input_ids = input_ids.to(target_device)

    # Generation kwargs
    gen_kwargs: dict[str, Any] = {
        "max_new_tokens": max_new_tokens,
        "do_sample": temperature > 0.0,
        "temperature": temperature,
        "top_p": top_p,
        "use_cache": True,
        "return_dict_in_generate": True,
    }
    if not gen_kwargs["do_sample"]:
        gen_kwargs.pop("temperature")
        gen_kwargs.pop("top_p")

    # Generate
    import torch
    try:
        with torch.inference_mode():
            generation_output = model.generate(input_ids, **gen_kwargs)
    except AttributeError as exc:
        if "_is_stateful" in str(exc):
            logger.warning(
                "AirLLM generate failed for %s (%s). Falling back to direct transformers.",
                getattr(model, "model_local_path", "unknown"), exc,
            )
            # Create direct model and retry generation
            direct = _DirectHFModel(
                getattr(model, "model_local_path", ""),
                device=str(input_ids.device),
                compression=compression,
            )
            with torch.inference_mode():
                generation_output = direct.model.generate(input_ids, **gen_kwargs)
            tokenizer = direct.tokenizer
        else:
            raise

    output_ids = generation_output.sequences[0]
    # Remove prompt tokens from output
    prompt_len = input_ids.shape[1]
    output_ids = output_ids[prompt_len:]
    result = tokenizer.decode(output_ids, skip_special_tokens=True)
    return result.strip()


# ---------------------------------------------------------------------------
# AirLLMProvider
# ---------------------------------------------------------------------------

class AirLLMProvider:
    """Provider for local AirLLM inference with circuit breaker protection.

    This replaces OllamaProvider.  Models are referenced by HuggingFace repo ID
    or local path.  The first time a model is used it is downloaded/split into
    layer shards (this may take several minutes and requires disk space).
    """

    def __init__(
        self,
        base_url: str = "",
        device: str | None = None,
        compression: str | None = None,
        model_registry: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the AirLLM provider.

        Args:
            base_url: Ignored (kept for interface compatibility).
            device: torch device, e.g. "cuda:0" or "cpu".  Auto-detected if None.
            compression: Optional "4bit" or "8bit" compression.
            model_registry: Override the default model alias registry.
            **kwargs: Additional kwargs passed to AirLLM.from_pretrained().
        """
        self._device = device or _DEFAULT_DEVICE
        self._compression = compression
        self._registry = model_registry or DEFAULT_MODEL_REGISTRY
        self._extra_kwargs = kwargs
        # Higher threshold because model download/split failures are common on first use
        self._circuit = CircuitBreaker(failure_threshold=10, reset_timeout=300.0)
        self._embed_fallback_dim = 384  # dimension for fallback zero embeddings

    async def aclose(self) -> None:
        """Unload all cached models and free memory."""
        with _model_lock:
            keys = list(_model_cache.keys())
        for key in keys:
            await asyncio.to_thread(_unload_model, key)
        _embedding_model_cache.clear()
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    # -- internal helpers ---------------------------------------------------

    async def _check_circuit(self) -> None:
        if not self._circuit.can_execute():
            raise RuntimeError(
                "Local LLM is temporarily unavailable. The circuit breaker is open. "
                "Please wait a moment and try again, or switch to a cloud provider."
            )

    def _resolve(self, model: str) -> str:
        return _resolve_model_id(model, self._registry)

    def _inject_thinking_disable(self, model: str, options: dict[str, Any] | None) -> dict[str, Any] | None:
        """Auto-disable thinking mode for qwen models to prevent JSON routing failures."""
        if options is None:
            options = {}
        if "qwen" in model.lower() and "thinking" not in options:
            options = {**options, "thinking": False}
        return options

    def _extract_gen_params(self, options: dict[str, Any] | None) -> dict[str, Any]:
        """Extract generation parameters from options dict."""
        params: dict[str, Any] = {}
        if options:
            if "temperature" in options:
                params["temperature"] = float(options["temperature"])
            if "max_tokens" in options:
                params["max_new_tokens"] = int(options["max_tokens"])
            if "top_p" in options:
                params["top_p"] = float(options["top_p"])
        return params

    # -- health check -------------------------------------------------------

    async def health_check(self) -> bool:
        """Check whether AirLLM is importable and CUDA (if requested) works."""
        if not AIRLLM_AVAILABLE:
            return False
        try:
            if str(self._device).startswith("cuda"):
                import torch
                return torch.cuda.is_available()
            return True
        except Exception:
            return False

    # -- chat streaming -----------------------------------------------------

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]] | list[ChatMessage],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream chat completion from AirLLM.

        AirLLM does not support true per-token streaming because each forward
        pass reloads all layers from disk.  We generate the full response in a
        background thread and then yield words with a small delay to simulate
        streaming.
        """
        await self._check_circuit()
        options = self._inject_thinking_disable(model, options)

        # Normalize messages
        dict_messages = [
            m if isinstance(m, dict) else {"role": m.role, "content": m.content}
            for m in messages
        ]

        resolved = self._resolve(model)
        gen_params = self._extract_gen_params(options)

        timeout = options.get("timeout_seconds", 300) if options else 300
        try:
            # Load model (may trigger download + layer split on first use)
            air_model = await asyncio.wait_for(
                asyncio.to_thread(
                    _get_cached_model,
                    resolved,
                    self._device,
                    self._compression,
                ),
                timeout=timeout,
            )

            # Generate in background thread
            text = await asyncio.wait_for(
                asyncio.to_thread(
                    _sync_chat_complete,
                    air_model,
                    dict_messages,
                    **gen_params,
                ),
                timeout=timeout,
            )

            self._circuit.record_success()
        except asyncio.TimeoutError:
            self._circuit.record_failure()
            logger.error("AirLLM stream timed out after %ds for model %s", timeout, model)
            raise LocalLLMError(
                f"AirLLM generation timed out after {timeout}s. "
                "The model may be too large for your hardware."
            )
        except Exception as exc:
            self._circuit.record_failure()
            logger.exception("AirLLM generation failed for model %s", model)
            raise LocalLLMError(f"AirLLM generation failed: {exc}") from exc

        # Simulate streaming by yielding word-by-word
        words = re.split(r"(\s+)", text)
        for word in words:
            if word:
                yield word
            # Small delay to simulate typing (~30 wpm)
            await asyncio.sleep(0.01)

    # -- chat complete ------------------------------------------------------

    async def chat_complete(
        self,
        model: str,
        messages: list[dict[str, str]] | list[ChatMessage],
        *,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Non-streaming chat completion with timeout."""
        await self._check_circuit()
        options = self._inject_thinking_disable(model, options)

        dict_messages = [
            m if isinstance(m, dict) else {"role": m.role, "content": m.content}
            for m in messages
        ]

        resolved = self._resolve(model)
        gen_params = self._extract_gen_params(options)
        timeout = options.get("timeout_seconds", 300) if options else 300

        try:
            air_model = await asyncio.wait_for(
                asyncio.to_thread(
                    _get_cached_model,
                    resolved,
                    self._device,
                    self._compression,
                ),
                timeout=timeout,
            )
            text = await asyncio.wait_for(
                asyncio.to_thread(
                    _sync_chat_complete,
                    air_model,
                    dict_messages,
                    **gen_params,
                ),
                timeout=timeout,
            )
            self._circuit.record_success()
            return text
        except asyncio.TimeoutError:
            self._circuit.record_failure()
            logger.error("AirLLM completion timed out after %ds for model %s", timeout, model)
            raise LocalLLMError(
                f"AirLLM completion timed out after {timeout}s. "
                "The model may be too large for your hardware. "
                "Try a smaller model or increase timeout."
            )
        except Exception as exc:
            self._circuit.record_failure()
            logger.exception("AirLLM completion failed for model %s", model)
            raise LocalLLMError(f"AirLLM completion failed: {exc}") from exc

    # -- embeddings ---------------------------------------------------------

    async def embed(
        self,
        texts: list[str],
        model: str,
        **kwargs: Any,
    ) -> list[list[float]]:
        """Get embeddings for a list of texts.

        Uses sentence-transformers when available, otherwise falls back to
        a lightweight HuggingFace model.
        """
        await self._check_circuit()
        resolved = self._resolve(model)

        try:
            emb_model = await asyncio.to_thread(
                _get_cached_embedding_model,
                resolved,
                self._device,
            )

            if SENTENCE_TRANSFORMERS_AVAILABLE and hasattr(emb_model, "encode"):
                embeddings = await asyncio.to_thread(
                    emb_model.encode,
                    texts,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
                return [emb.tolist() for emb in embeddings]

            # Fallback: manual HF embedding extraction
            import torch

            tokenizer = emb_model["tokenizer"]
            hf_model = emb_model["model"]
            device = emb_model["device"]
            results: list[list[float]] = []
            for text in texts:
                inputs = tokenizer(
                    text,
                    return_tensors="pt",
                    truncation=True,
                    max_length=512,
                    padding=True,
                )
                inputs = {k: v.to(device) for k, v in inputs.items()}
                with torch.inference_mode():
                    outputs = hf_model(**inputs)
                # Mean pool the last hidden state
                hidden = outputs.last_hidden_state
                mask = inputs["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
                summed = torch.sum(hidden * mask, 1)
                denom = torch.clamp(mask.sum(1), min=1e-9)
                vec = (summed / denom).squeeze().cpu().tolist()
                results.append(vec)

            self._circuit.record_success()
            return results
        except Exception as exc:
            self._circuit.record_failure()
            logger.exception("AirLLM embedding failed for model %s", model)
            # Return deterministic hash-based embeddings as fallback
            return [self._hash_embed(t) for t in texts]

    def _hash_embed(self, text: str) -> list[float]:
        """Deterministic fallback embedding using SHA-256 hash."""
        import hashlib
        import math
        h = hashlib.sha256(text.encode()).digest()
        # Use multiple rounds of the hash to fill the dimension
        vec = []
        round_num = 0
        while len(vec) < self._embed_fallback_dim:
            round_hash = hashlib.sha256(h + round_num.to_bytes(4, "big")).digest()
            vec.extend(((b / 255.0) - 0.5) * 2.0 for b in round_hash)
            round_num += 1
        # Normalize to unit sphere for cosine similarity
        vec = vec[:self._embed_fallback_dim]
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec
