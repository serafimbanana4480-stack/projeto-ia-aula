# Caching System Design

## 1. Problem Decomposition
- **Core requirement**: Provide fast, scalable access to frequently read data with eventual consistency.
- **Non-functional requirements**:
  - Low latency (sub-millisecond for cache hits)
  - High availability (fault tolerance)
  - Horizontal scalability
  - Configurable TTL and eviction policies
  - Observability (metrics, logging)
- **Constraints**:
  - Existing tech stack: likely Java/Kotlin microservices, but design should be language-agnostic.
  - Team size: small to medium; prefer managed solutions or well-known open-source.
  - Budget: moderate; avoid excessive licensing.
- **Out of scope**:
  - Persistent storage layer (assume backing store exists)
  - Transactional guarantees across cache and DB (use patterns like Cache-Aside or Write-Through)
  - Security hardening beyond basic auth/TLS (delegated to platform)

## 2. Alternative Exploration

### Approach A: Obvious Solution – Centralized Redis Cluster
- **Description**: Deploy a Redis cluster (managed or self-hosted) as the sole caching layer.
- **Advantages**: Mature, rich data structures, pub/sub, built-in replication, easy client libraries.
- **Disadvantages**: Single point of failure if not properly clustered; network hop adds latency; operational overhead.
- **When to use**: When you need advanced features (sorted sets, streams) and can manage Redis ops.
- **When NOT to use**: Ultra-low latency requirements where network hop is prohibitive; extremely high read volumes that exceed Redis throughput.

### Approach B: Minimal Solution – Local In‑Process Cache (e.g., Caffeine/Guava Cache)
- **Description**: Each service instance maintains its own bounded cache (LRU, TTL) in heap.
- **Advantages**: Zero network latency, simplest to deploy, no external dependencies.
- **Disadvantages**: Cache duplication across instances leads to stale data; memory usage scales with number of instances; no central eviction coordination.
- **When to use**: Read‑mostly data with low staleness tolerance, small dataset, or as a L1 cache in front of a remote cache.
- **When NOT to use**: When data is frequently updated across instances or dataset is large.

### Approach C: Robust Solution – Multi‑Tiered Cache (L1 Local + L2 Remote)
- **Description**: Combine a local in‑process cache (L1) with a centralized Redis cluster (L2). Use cache‑aside or read‑through patterns; propagate invalidations via Redis pub/sub or a lightweight invalidation service.
- **Advantages**: Best of both worlds – low latency L1 hits, fallback to L2, reduced network traffic, consistency via invalidation.
- **Disadvantages**: More complex to implement and tune; need invalidation mechanism; two layers to monitor.
- **When to use**: High‑traffic services where read latency is critical and data updates are moderate.
- **When NOT to use**: Simpler apps where added complexity outweighs benefits; teams lacking DevOps capacity.

## 3. Recommendation
**Chosen Approach**: **Multi‑Tiered Cache (L1 Local + L2 Remote)**.

**Justification**:
- The system expects high read volume with moderate writes; L1 reduces latency for hot keys.
- Using Redis as L2 provides persistence, replication, and easy horizontal scaling.
- Invalidation via Redis pub/sub keeps L1 reasonably consistent without heavy coordination.
- This pattern is well‑known (read‑through with cache‑aside) and supported by libraries (e.g., Spring Cache with Caffeine + Redis).
- It scales with instance count while keeping network traffic lower than a pure L2 solution.

## 4. Specification

### 4.1 Components
1. **Application Service** – Business logic that interacts with the cache via a CacheFacade.
2. **CacheFacade** – Abstracts L1/L2 interactions:
   - `get(key)`: tries L1, on miss delegates to L2; on L2 hit, populates L1.
   - `put(key, value, ttl)`: writes to L2 (write‑through) and updates L1.
   - `invalidate(key)`: removes from L1 and publishes invalidation event to L2 topic.
3. **L1 Cache** – In‑process cache (e.g., Caffeine) with LRU eviction, max size, TTL.
4. **L2 Cache** – Redis cluster (AWS Elasticache, Azure Redis, or self‑hosted) with replication.
5. **Invalidation Listener** – Subscribes to Redis `__keyevent@0__:expired` and custom channels; evicts matching keys from L1.
6. **Metrics & Monitoring** – Export cache hit/miss ratios, latency, eviction counts (via Micrometer/Prometheus).
7. **Configuration Service** – Centralized config (e.g., Consul, Spring Cloud Config) for TTL, size limits, Redis endpoints.

### 4.2 Data Flow
```
Application --> CacheFacade.get(key)
   |
   |-- L1 hit? ---------------------> return value
   |
   |-- L1 miss --> L2.get(key)
                |
                |-- L2 hit --> populate L1, return value
                |
                |-- L2 miss --> fetch from DB, L2.put(key, value), L1.put(key, value), return value
```
Invalidation flow:
```
Service updates DB --> CacheFacade.put(...) --> L2.write --> publish "invalidate:key" --> Listener --> L1.evict(key)
```

### 4.3 API Contracts (Pseudocode)
```java
public interface CacheFacade {
    <V> V get(String key, Callable<V> loader, long ttlSeconds);
    void put(String key, Object value, long ttlSeconds);
    void invalidate(String key);
    void invalidateAll(Collection<String> keys);
}
```
Loader is used for cache‑aside on miss.

### 4.4 Redis Schema (Key Design)
- **Data keys**: `app:{service}:{entity}:{id}` (string or hash depending on value complexity)
- **Invalidation channel**: `app:{service}:invalidate`
- **Expired key notifications**: enabled via `notify-keyspace-events Ex`

### 4.5 Failure Modes & Mitigations
| Failure Mode                | Impact                     | Mitigation |
|-----------------------------|----------------------------|------------|
| L2 Redis node down          | Increased latency, possible L1 stale reads | Redis cluster with automatic failover; circuit breaker in CacheFacade to fallback to DB directly |
| Network partition           | L2 unreachable             | Local L1 continues serving hits; misses go to DB; metrics alert |
| L1 memory pressure          | Evictions, increased L2 load | Size‑based eviction; monitor eviction rate; scale L1 heap or reduce TTL |
| Invalidation message loss   | Temporary stale L1 entries | Use Redis persistence for channels; rely on TTL as safety net; periodic refresh via read‑through |
| Cache stampede on miss      | Sudden DB load             | Use loader locking (e.g., Caffeine’s `AsyncLoadingCache` or Redis `SETNX` lock) |

### 4.6 Security Considerations
- Encrypt Redis traffic (TLS).
- Authenticate clients via Redis ACLs or IAM (for managed services).
- Restrict invalidation channel permissions to service accounts only.
- Audit logs for cache admin operations (size changes, flushes).

### 4.7 What This Design Does NOT Handle
- Strong consistency guarantees across cache and DB (requires transactional outbox or saga).
- Geo‑distributed active‑active caching (would need a global Redis or multi‑region replication).
- Complex query caching (e.g., result‑set caching) – assumes key‑based access.

## 5. Next Steps
1. **Prototype** – Implement CacheFacade with Caffeine + Jedis/Lettuce in a non‑critical service.
2. **Benchmark** – Measure latency and hit‑rate under load; tune L1 size and TTL.
3. **Observability** – Add Micrometer timers for get/put and publish to Prometheus.
4. **Documentation** – Write operational guide (scaling Redis, alerting on eviction rates).
5. **Rollout** – Deploy to staging, monitor invalidation lag, then promote to production.

---
*Design completed: 2025-08-27*