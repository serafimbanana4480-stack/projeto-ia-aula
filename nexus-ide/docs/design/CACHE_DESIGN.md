# Caching System Design for Nexus IDE

## 1. Overview
The caching system provides fast, temporary data storage with configurable expiration (TTL) and optional eviction strategies. It is used to reduce redundant computations, API calls, and file I/O across the IDE backend and frontend.

## 2. Core Components

### 2.1 `TTLCache` (already implemented in `cache.py`)
- **Key features**
  - Thread‑safe via `threading.RLock()`.
  - Stores `(value, expire_time)` tuples.
  - Automatic expiration: entries are removed on `get` when past TTL.
  - `set`, `get`, `delete`, `clear` operations.

### 2.2 `CacheInterface` (abstract base)
```python
from abc import ABC, abstractmethod
from typing import TypeVar, Generic

T = TypeVar("T")

class CacheInterface(Generic[T], ABC):
    @abstractmethod
    def get(self, key: str) -> T | None: ...
    @abstractmethod
    def set(self, key: str, value: T, ttl_seconds: int | None = None) -> None: ...
    @abstractmethod
    def delete(self, key: str) -> None: ...
    @abstractmethod
    def clear(self) -> None: ...
```

### 2.3 `LRUCache` (optional extension)
- Implements LRU eviction when a maximum size is reached.
- Can wrap any underlying store (e.g., `TTLCache`).
- Uses `collections.OrderedDict` for O(1) moves-to‑end.

### 2.4 `CacheManager` (singleton‑style registry)
- Maps logical cache names (e.g., `"api_responses"`, `"file_metadata"`) to concrete `CacheInterface` instances.
- Provides helper methods:
  - `get_or_compute(key, compute_fn, ttl)`: returns cached value or runs `compute_fn`, stores result.
  - `invalidate_pattern(pattern)`: removes keys matching a prefix/glob.
- Centralizes TTL defaults and eviction policies.

## 3. Usage Patterns

| Scenario | Recommended Cache | TTL Example |
|----------|-------------------|-------------|
| Remote API responses | `TTLCache` or `LRUCache` | 5 minutes |
| Parsed file metadata | `TTLCache` | 1 hour |
| Expensive computation results | `LRUCache` (size‑bounded) | depends on compute cost |
| Feature flags | `TTLCache` | 24 hours |

## 4. Implementation Details

### 4.1 Thread Safety
All cache classes use an `RLock` so multiple threads (e.g., IDE UI thread + background worker) can read/write without corruption.

### 4.2 Expiration Logic
- `TTLCache.get()` deletes the entry if `time.time() >= expire`.
- `LRUCache` optionally checks TTL on eviction.

### 4.3 Persistence (optional)
- Implement a `PersistentCache` that writes expired/evicted entries to disk (e.g., SQLite) and reloads them at startup.

### 4.4 Metrics
- Expose simple counters via a `CacheStats` object:
  - `hits`, `misses`, `evictions`, `sets`.
- Can be integrated with the IDE's telemetry system.

## 5. Configuration (example `config.yaml`)
```yaml
caches:
  api_responses:
    type: TTLCache
    default_ttl: 300   # seconds
  file_metadata:
    type: LRUCache
    max_size: 128
    default_ttl: 3600
```

## 6. Migration / Backward Compatibility
- The existing `TTLCache` in `cache.py` can be used directly or subclassed to implement the `CacheInterface`.
- New `CacheManager` adds no breaking changes; existing code can continue calling `ttl_cache.set/get`.

## 7. Roadmap
1. ✅ **Current** – `TTLCache` already in `cache.py`.
2. Add `CacheInterface` abstract class.
3. Implement `LRUCache` wrapper.
4. Create `CacheManager` singleton.
5. Add metrics and optional persistence.
6. Update all internal call sites to use the manager.

## 8. Code Example
```python
from cache import TTLCache
from typing import Optional

cache = TTLCache(ttl_seconds=300)

def fetch_user_profile(user_id: str) -> Optional[dict]:
    key = f"profile:{user_id}"
    data = cache.get(key)
    if data is None:
        # expensive I/O or compute
        data = {"id": user_id, "name": "…"}
        cache.set(key, data)
    return data
```

---
*Design version 1.0 – generated for Nexus IDE caching system.*