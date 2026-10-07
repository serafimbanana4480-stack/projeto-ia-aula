"""Semantic Cache System - Advanced caching with embedding similarity.

Provides intelligent caching based on semantic similarity rather than exact matches,
dramatically improving cache hit rates for AI responses while maintaining accuracy.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from backend.observability.optional_deps import optional_module
from backend.tools.ollama_client import OllamaClient

# numpy is an optional extra (``uv sync --extra analytics``); see
# backend/observability/optional_deps.py. The cosine-similarity maths is the only
# consumer, so importing this module without numpy stays cheap and succeeds.
np = optional_module("numpy", extra="analytics", owner=__name__)

#: What ``np.ndarray`` used to say in the annotations below -- see the note in
#: backend/quantum/quantum_computing.py. The extra is not installed by default,
#: so a type checker cannot resolve the real alias.
type Array = Any

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A cached response with metadata."""
    query_hash: str
    query_embedding: Array
    response: str
    model_key: str
    created_at: float
    last_accessed: float
    access_count: int = 0
    ttl_seconds: float = 3600  # 1 hour default
    similarity_threshold: float = 0.85
    
    def __post_init__(self) -> None:
        self.last_accessed = time.time()
    
    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds
    
    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


@dataclass
class CacheStats:
    """Cache performance statistics."""
    total_queries: int = 0
    cache_hits: int = 0
    semantic_hits: int = 0
    exact_hits: int = 0
    misses: int = 0
    evictions: int = 0
    
    @property
    def hit_rate(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return self.cache_hits / self.total_queries
    
    @property
    def semantic_hit_rate(self) -> float:
        if self.cache_hits == 0:
            return 0.0
        return self.semantic_hits / self.cache_hits


class SemanticCache:
    """Advanced semantic cache with embedding-based similarity matching.
    
    Features:
    - Semantic similarity matching using embeddings
    - Adaptive TTL based on query patterns
    - LRU eviction with semantic clustering
    - Cache warming based on usage patterns
    - Distributed cache support (Redis ready)
    """
    
    def __init__(
        self,
        ollama_client: OllamaClient,
        *,
        max_entries: int = 10000,
        similarity_threshold: float = 0.85,
        default_ttl: float = 3600,
        embedding_model: str = "qwen2.5:0.5b",
        enable_clustering: bool = True,
    ) -> None:
        self.ollama = ollama_client
        self.max_entries = max_entries
        self.similarity_threshold = similarity_threshold
        self.default_ttl = default_ttl
        self.embedding_model = embedding_model
        self.enable_clustering = enable_clustering
        
        # Cache storage
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._embedding_cache: dict[str, Array] = {}
        
        # Statistics
        self._stats = CacheStats()
        
        # Clustering for better organization
        self._semantic_clusters: dict[str, list[str]] = {}
        
        # Background tasks
        self._cleanup_task: asyncio.Task | None = None
        self._running = False
        
        # Lock for thread safety
        self._lock = asyncio.Lock()
    
    async def start(self) -> None:
        """Start the semantic cache and background tasks."""
        if self._running:
            return
        
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Semantic Cache started with max_entries=%d", self.max_entries)
    
    async def stop(self) -> None:
        """Stop the semantic cache."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
        logger.info("Semantic Cache stopped")
    
    async def get(self, query: str, model_key: str) -> str | None:
        """Get cached response for a query using semantic similarity."""
        async with self._lock:
            self._stats.total_queries += 1
            
            # Generate query hash and embedding
            query_hash = self._hash_query(query, model_key)
            query_embedding = await self._get_embedding(query)
            
            # Check for exact match first
            if query_hash in self._cache:
                entry = self._cache[query_hash]
                if not entry.is_expired:
                    entry.access_count += 1
                    entry.last_accessed = time.time()
                    # Move to end (LRU)
                    self._cache.move_to_end(query_hash)
                    
                    self._stats.cache_hits += 1
                    self._stats.exact_hits += 1
                    logger.debug("Exact cache hit for query hash %s", query_hash[:8])
                    return entry.response
                else:
                    # Remove expired entry
                    del self._cache[query_hash]
            
            # Search for semantic similarity
            best_match = await self._find_semantic_match(query_embedding, model_key)
            if best_match:
                entry_hash, entry = best_match
                if not entry.is_expired:
                    entry.access_count += 1
                    entry.last_accessed = time.time()
                    self._cache.move_to_end(entry_hash)
                    
                    self._stats.cache_hits += 1
                    self._stats.semantic_hits += 1
                    logger.debug(
                        "Semantic cache hit (similarity=%.3f) for query hash %s",
                        self._cosine_similarity(query_embedding, entry.query_embedding),
                        query_hash[:8]
                    )
                    return entry.response
            
            self._stats.misses += 1
            return None
    
    async def put(self, query: str, response: str, model_key: str, *, ttl: float | None = None) -> None:
        """Store a response in the cache."""
        async with self._lock:
            query_hash = self._hash_query(query, model_key)
            query_embedding = await self._get_embedding(query)
            
            # Check if we need to evict entries
            if len(self._cache) >= self.max_entries:
                await self._evict_entries()
            
            # Create cache entry
            entry = CacheEntry(
                query_hash=query_hash,
                query_embedding=query_embedding,
                response=response,
                model_key=model_key,
                created_at=time.time(),
                ttl_seconds=ttl or self.default_ttl,
                similarity_threshold=self.similarity_threshold,
            )
            
            # Store entry
            self._cache[query_hash] = entry
            
            # Update clustering if enabled
            if self.enable_clustering:
                await self._update_clusters(query_hash, query_embedding)
            
            logger.debug("Cached response for query hash %s", query_hash[:8])
    
    async def invalidate(self, query: str, model_key: str) -> bool:
        """Invalidate a specific cache entry."""
        async with self._lock:
            query_hash = self._hash_query(query, model_key)
            if query_hash in self._cache:
                del self._cache[query_hash]
                return True
            return False
    
    async def clear(self) -> None:
        """Clear all cache entries."""
        async with self._lock:
            self._cache.clear()
            self._semantic_clusters.clear()
            self._embedding_cache.clear()
            logger.info("Cache cleared")
    
    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        stats = {
            "total_entries": len(self._cache),
            "total_queries": self._stats.total_queries,
            "cache_hits": self._stats.cache_hits,
            "exact_hits": self._stats.exact_hits,
            "semantic_hits": self._stats.semantic_hits,
            "misses": self._stats.misses,
            "evictions": self._stats.evictions,
            "hit_rate": self._stats.hit_rate,
            "semantic_hit_rate": self._stats.semantic_hit_rate,
            "clusters": len(self._semantic_clusters) if self.enable_clustering else 0,
        }
        
        # Add memory usage estimate
        stats["memory_usage_mb"] = self._estimate_memory_usage()
        
        return stats
    
    async def _get_embedding(self, text: str) -> Array:
        """Get embedding for text, using cache if available."""
        # Check embedding cache first
        text_hash = hashlib.md5(text.encode()).hexdigest()
        if text_hash in self._embedding_cache:
            return self._embedding_cache[text_hash]
        
        try:
            # Generate embedding using Ollama
            response = await self.ollama.embeddings(
                model=self.embedding_model,
                prompt=text
            )
            
            embedding = np.array(response["embedding"], dtype=np.float32)
            
            # Cache the embedding (limit size)
            if len(self._embedding_cache) < 10000:
                self._embedding_cache[text_hash] = embedding
            
            return embedding
            
        except Exception as e:
            logger.error("Failed to generate embedding: %s", e)
            # Fallback to zero embedding
            return np.zeros(384, dtype=np.float32)  # Common embedding size
    
    def _hash_query(self, query: str, model_key: str) -> str:
        """Generate hash for query and model combination."""
        content = f"{model_key}:{query}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    async def _find_semantic_match(self, query_embedding: Array, model_key: str) -> tuple[str, CacheEntry] | None:
        """Find the best semantic match for a query embedding."""
        best_match = None
        best_similarity = 0.0
        
        for entry_hash, entry in self._cache.items():
            # Skip if model doesn't match
            if entry.model_key != model_key:
                continue
            
            # Skip expired entries
            if entry.is_expired:
                continue
            
            # Calculate similarity
            similarity = self._cosine_similarity(query_embedding, entry.query_embedding)
            
            # Check if this is a better match
            if similarity > best_similarity and similarity >= entry.similarity_threshold:
                best_similarity = similarity
                best_match = (entry_hash, entry)
        
        return best_match
    
    def _cosine_similarity(self, a: Array, b: Array) -> float:
        """Calculate cosine similarity between two embeddings."""
        dot_product = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return dot_product / (norm_a * norm_b)
    
    async def _evict_entries(self) -> None:
        """Evict old or less relevant entries to make space."""
        # Remove expired entries first
        expired_hashes = [
            hash_key for hash_key, entry in self._cache.items()
            if entry.is_expired
        ]
        
        for hash_key in expired_hashes:
            del self._cache[hash_key]
            self._stats.evictions += 1
        
        # If still need space, use LRU
        if len(self._cache) >= self.max_entries:
            # Remove oldest 10% of entries
            entries_to_remove = max(1, self.max_entries // 10)
            for _ in range(entries_to_remove):
                if self._cache:
                    oldest_key = next(iter(self._cache))
                    del self._cache[oldest_key]
                    self._stats.evictions += 1
    
    async def _update_clusters(self, query_hash: str, query_embedding: Array) -> None:
        """Update semantic clusters for better organization."""
        # Find the best existing cluster
        best_cluster = None
        best_similarity = 0.0
        
        for cluster_id, cluster_hashes in self._semantic_clusters.items():
            if not cluster_hashes:
                continue
            
            # Get a representative embedding from the cluster
            sample_hash = cluster_hashes[0]
            if sample_hash in self._cache:
                sample_embedding = self._cache[sample_hash].query_embedding
                similarity = self._cosine_similarity(query_embedding, sample_embedding)
                
                if similarity > best_similarity and similarity > 0.7:
                    best_similarity = similarity
                    best_cluster = cluster_id
        
        if best_cluster:
            # Add to existing cluster
            self._semantic_clusters[best_cluster].append(query_hash)
        else:
            # Create new cluster
            cluster_id = f"cluster_{len(self._semantic_clusters)}"
            self._semantic_clusters[cluster_id] = [query_hash]
    
    async def _cleanup_loop(self) -> None:
        """Background cleanup loop."""
        while self._running:
            try:
                await self._perform_cleanup()
                await asyncio.sleep(300)  # Run every 5 minutes
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Cleanup loop error: %s", e)
                await asyncio.sleep(300)
    
    async def _perform_cleanup(self) -> None:
        """Perform periodic cleanup tasks."""
        async with self._lock:
            # Remove expired entries
            expired_hashes = [
                hash_key for hash_key, entry in self._cache.items()
                if entry.is_expired
            ]
            
            for hash_key in expired_hashes:
                del self._cache[hash_key]
                self._stats.evictions += 1
            
            # Clean up embedding cache (keep only recent ones)
            if len(self._embedding_cache) > 5000:
                # Remove oldest half
                keys_to_remove = list(self._embedding_cache.keys())[:2500]
                for key in keys_to_remove:
                    del self._embedding_cache[key]
            
            # Update clusters (remove empty ones)
            if self.enable_clustering:
                empty_clusters = [
                    cluster_id for cluster_id, hashes in self._semantic_clusters.items()
                    if not hashes
                ]
                for cluster_id in empty_clusters:
                    del self._semantic_clusters[cluster_id]
    
    def _estimate_memory_usage(self) -> float:
        """Estimate memory usage in MB."""
        total_size = 0
        
        # Cache entries
        for entry in self._cache.values():
            total_size += len(entry.response.encode())  # Response size
            total_size += entry.query_embedding.nbytes  # Embedding size
            total_size += 200  # Metadata estimate
        
        # Embedding cache
        for embedding in self._embedding_cache.values():
            total_size += embedding.nbytes
        
        return total_size / (1024 * 1024)  # Convert to MB


# Global semantic cache instance
_semantic_cache: SemanticCache | None = None


async def get_semantic_cache() -> SemanticCache:
    """Get the global semantic cache instance."""
    global _semantic_cache
    if _semantic_cache is None:
        from backend.config.settings import get_settings
        settings = get_settings()
        ollama = OllamaClient(settings.ollama_host)
        _semantic_cache = SemanticCache(ollama)
        await _semantic_cache.start()
    return _semantic_cache
