"""
Semantic Cache — cache de respostas LLM baseado em similaridade de embeddings.

Fluxo:
1. Gera embedding da query atual
2. Busca entradas no Redis com mesmo (model, system_prompt_hash)
3. Calcula cosine_similarity com cada entrada
4. Se max_similarity > threshold: retorna resposta cacheada (hit)
5. Caso contrário: executa LLM, armazena resultado (miss)

Threshold recomendado:
- 0.95 para queries factuais/idênticas
- 0.90 para respostas de código (pequenas variações)
- 0.85 para geração criativa (apenas semântica muito próxima)
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    query_hash: str
    query_embedding: list[float]
    response: str
    model: str
    system_prompt_hash: str
    timestamp: float = field(default_factory=time.time)
    hit_count: int = 0

    def to_dict(self) -> dict:
        return {
            "query_hash": self.query_hash,
            "query_embedding": self.query_embedding,
            "response": self.response,
            "model": self.model,
            "system_prompt_hash": self.system_prompt_hash,
            "timestamp": self.timestamp,
            "hit_count": self.hit_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CacheEntry:
        return cls(**data)


class SemanticCache:
    """Cache semântico de respostas LLM com suporte a Redis."""

    def __init__(
        self,
        similarity_threshold: float = 0.92,
        ttl_seconds: int = 3600,
        max_entries: int = 10000,
        embed_fn: Callable | None = None,
    ):
        self.similarity_threshold = similarity_threshold
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._embed_fn = embed_fn

        # In-memory store (fallback quando Redis não está disponível)
        self._entries: dict[str, list[CacheEntry]] = {}  # namespace -> entries

        # Metrics
        self._hits = 0
        self._misses = 0
        self._stores = 0

    def _make_namespace(self, model: str, system_prompt: str) -> str:
        sys_hash = hashlib.md5(system_prompt.encode("utf-8")).hexdigest()[:8]
        return f"{model}:{sys_hash}"

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b):
            return 0.0
        dot = sum(ax * bx for ax, bx in zip(a, b, strict=False))
        norm_a = math.sqrt(sum(ax * ax for ax in a))
        norm_b = math.sqrt(sum(bx * bx for bx in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def get(
        self,
        query: str,
        model: str,
        system_prompt: str,
        embed_fn: Callable | None = None,
    ) -> str | None:
        """Return cached response if semantically similar query exists."""
        fn = embed_fn or self._embed_fn
        if fn is None:
            self._misses += 1
            return None

        try:
            namespace = self._make_namespace(model, system_prompt)
            entries = self._entries.get(namespace, [])
            if not entries:
                self._misses += 1
                return None

            query_embedding = fn(query)
            if query_embedding is None:
                self._misses += 1
                return None

            best_similarity = 0.0
            best_response = None
            best_entry = None

            for entry in entries:
                sim = self._cosine_similarity(query_embedding, entry.query_embedding)
                if sim > best_similarity:
                    best_similarity = sim
                    best_response = entry.response
                    best_entry = entry

            if best_similarity >= self.similarity_threshold and best_response:
                self._hits += 1
                if best_entry:
                    best_entry.hit_count += 1
                logger.debug(
                    "[SEMANTIC CACHE HIT] similarity=%.3f threshold=%.3f model=%s",
                    best_similarity,
                    self.similarity_threshold,
                    model,
                )
                return best_response

            self._misses += 1
            return None

        except Exception as e:
            logger.warning("[SEMANTIC CACHE] get() failed: %s", e)
            self._misses += 1
            return None

    def store(
        self,
        query: str,
        response: str,
        model: str,
        system_prompt: str,
        embed_fn: Callable | None = None,
    ) -> bool:
        """Store LLM response in semantic cache."""
        fn = embed_fn or self._embed_fn
        if fn is None:
            return False

        try:
            namespace = self._make_namespace(model, system_prompt)
            query_embedding = fn(query)
            if query_embedding is None:
                return False

            entry = CacheEntry(
                query_hash=hashlib.md5(query.encode("utf-8")).hexdigest(),
                query_embedding=query_embedding,
                response=response,
                model=model,
                system_prompt_hash=hashlib.md5(system_prompt.encode("utf-8")).hexdigest(),
            )

            if namespace not in self._entries:
                self._entries[namespace] = []
            self._entries[namespace].append(entry)

            # Eviction: keep only max_entries per namespace
            if len(self._entries[namespace]) > self.max_entries:
                # Remove oldest entries (by hit_count, then timestamp)
                self._entries[namespace].sort(key=lambda e: (e.hit_count, e.timestamp))
                self._entries[namespace] = self._entries[namespace][-self.max_entries :]

            self._stores += 1
            return True

        except Exception as e:
            logger.warning("[SEMANTIC CACHE] store() failed: %s", e)
            return False

    def clear(self, model: str | None = None, system_prompt: str | None = None) -> None:
        """Clear cache entries. If model+system_prompt specified, clear only that namespace."""
        if model and system_prompt:
            namespace = self._make_namespace(model, system_prompt)
            self._entries.pop(namespace, None)
        else:
            self._entries.clear()

    def get_metrics(self) -> dict:
        total = self._hits + self._misses
        total_entries = sum(len(v) for v in self._entries.values())
        return {
            "semantic_cache_hits_total": self._hits,
            "semantic_cache_misses_total": self._misses,
            "semantic_cache_stores_total": self._stores,
            "semantic_cache_hit_rate": self._hits / max(1, total),
            "semantic_cache_namespaces": len(self._entries),
            "semantic_cache_total_entries": total_entries,
        }


# Global singleton
_semantic_cache: SemanticCache | None = None


def get_semantic_cache() -> SemanticCache:
    global _semantic_cache
    if _semantic_cache is None:
        _semantic_cache = SemanticCache()
    return _semantic_cache
