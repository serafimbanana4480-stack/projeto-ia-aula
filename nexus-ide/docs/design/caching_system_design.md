# Caching System Design

## Overview
This document describes a scalable, high‑performance caching system suitable for web applications, APIs, or micro‑services. The design addresses correctness, security, performance, and maintainability, and includes concrete recommendations for implementation and operations.

## 1. Requirements
- **Low latency**: sub‑millisecond reads for hot data.
- **High throughput**: tens of thousands of operations per second per instance.
- **Horizontal scalability**: sharding + replication with minimal reshuffle on membership changes.
- **Optional persistence**: warm‑start capability via write‑behind to a durable store.
- **Eviction policies**: LRU, LFU, TTL (time‑to‑live).
- **Thread‑safety**: concurrent access without data races or deadlocks.
- **Security**: protection against injection, DoS, unauthorized access, and data leakage.
- **Observability**: metrics, logging, tracing, and health checks.
- **Operational simplicity**: container‑friendly, easy configuration, rolling upgrades.

## 2. Architecture

### 2.1 High‑Level Components
1. **API Layer** – thin wrapper exposing `GET /cache/{key}`, `POST /cache/{key}` (with optional TTL), `DELETE /cache/{key}`, `POST /cache/flush` (admin), `GET /stats`, `GET /health`.
2. **Routing / Sharding Layer** – consistent hashing ring with virtual nodes; maps keys to shard instances.
3. **Shard Instances** – each runs an in‑memory cache engine based on a concurrent hash map plus auxiliary structures for LRU/LFU and TTL.
4. **Persistence Layer (optional)** – write‑behind to SSD or remote store (e.g., Redis, Cassandra) for warm‑start.
5. **Monitoring & Control Plane** – Prometheus metrics endpoint, structured JSON logs, OpenTelemetry tracing, admin API for configuration and diagnostics.

### 2.2 Data Structures (per shard)
- **Primary Store**: `ConcurrentHashMap` (or equivalent lock‑striped hash table) mapping `key → entry`.
- **Entry**: `{value, expiryTime (optional), version}`.
- **LRU Auxiliary**: doubly‑linked list + hash map for O(1) move‑to‑front.
- **LFU Auxiliary**: frequency buckets + minimum frequency tracking.
- **TTL Wheel**: hashed timer wheel (bucket array) enabling O(1) expiry insertion and batch removal.

### 2.3 Sharding & Replication
- **Consistent Hashing** with virtual nodes (e.g., 100 vnodes per physical node) ensures < 1 % key movement when nodes join/leave.
- **Replication Factor N** (default 2): each logical shard has N‑1 replicas for fault tolerance.
- **Write Path**: write to primary, then asynchronously propagate to replicas (or use synchronous quorum for strong consistency if required).
- **Read Path**: read from primary; on failure or latency SLA breach, fallback to replica (read‑repair on success).
- **Failure Detection**: gossip‑based membership or heartbeat; suspected nodes are temporarily excluded from the ring.

### 2.4 Eviction & Expiry
- **TTL**: each entry stores absolute expiry time; TTL wheel triggers batch removal when bucket time passes.
- **Size‑Based Eviction**: when shard memory usage > high‑watermark (e.g., 80 % of allocated heap), run LRU/LFU eviction until low‑watermark (e.g., 60 %).
- **Lazy Expiry**: on `GET`, check expiry and remove if stale; also piggyback on eviction cycles.
- **Eviction Granularity**: per‑shard background worker; avoids global stop‑the‑world pauses.

### 2.5 Concurrency Control
- **Lock Striping**: array of 16–64 locks (power of two) striping the hash table; reduces contention.
- **Read‑Copy‑Update (RCU)** for hot reads: readers access a snapshot version without acquiring locks; writers update and release old version after a grace period.
- **Write Path**: acquire stripe lock, update primary map and auxiliary structures, release; then enqueue replication message.
- **Auxiliary Structures**: LRU/LFU updates performed under same stripe lock to maintain consistency.

### 2.6 Persistence (Optional)
- **Write‑Behind**: each shard buffers mutations in a queue; a background flush thread writes batches to the durable store every `flush_interval` (default 1 s) or when buffer size > threshold.
- **Read‑Through**: on cache miss, optionally load from persistent store and populate cache (configurable per namespace).
- **Warm‑Start**: on node restart, replay persisted entries to rebuild in‑memory state.
- **Consistency**: write‑behind acknowledges after durable store persistence; optional sync flush on shutdown.

### 2.7 Security Measures
- **Input Validation**: limit key length (e.g., ≤ 256 bytes) and value size (configurable max, default 1 MB); reject oversized payloads early.
- **Authentication/Authorization**: API layer validates JWT/OAuth2 tokens; admin endpoints (`/flush`, `/stats`, `/health` writes) require role‑based access (e.g., `cache-admin`).
- **Rate Limiting**: token bucket per client IP or API key to mitigate abuse and DoS.
- **Encryption**: TLS 1.3 for all network traffic; optional at‑rest encryption for persistence layer (e.g., encrypted disk or store‑side encryption).
- **Injection Safety**: treat keys and values as opaque byte arrays; no interpretation as SQL, command, or script.
- **Security Headers**: HTTP responses include `Content‑Security‑Policy`, `X‑Content‑Type‑Options: nosniff`, etc.
- **Audit Logging**: security‑relevant events (auth failures, admin actions) logged with user ID, timestamp, and source IP.

### 2.8 Observability
- **Metrics (Prometheus)**: 
  - `cache_get_total`, `cache_hit_total`, `cache_miss_total`
  - `cache_set_total`, `cache_delete_total`
  - `cache_latency_seconds` buckets (GET, SET, DELETE)
  - `cache_memory_bytes_used`, `cache_evictions_total`
  - `cache_replication_lag_seconds`, `cache_flush_duration_seconds`
  - `process_cpu_seconds_total`, `process_resident_memory_bytes`
- **Logging**: structured JSON logs with fields `timestamp`, `level`, `service`, `trace_id`, `span_id`, `message`, and optional `error`.
- **Tracing**: OpenTelemetry instrumentation; each API request creates a root span; cache operations are child spans.
- **Health Checks**: `/health` returns 200 if (a) shard memory < critical threshold (e.g., 90 %), (b) replication lag < threshold (e.g., 200 ms), and (c) no recent OOM or crash events.
- **Alerting**: rules for high eviction rate, high latency p99, memory pressure, replication lag spikes, authentication failures.

## 3. API Specification (REST‑like)

| Method | Endpoint               | Description                                                   |
|--------|------------------------|---------------------------------------------------------------|
| GET    | `/cache/{key}`         | Retrieve value; returns 200 + value or 404 if missing.       |
| POST   | `/cache/{key}`         | Set value; optional JSON body `{ "ttl_seconds": 300 }`.    |
| DELETE | `/cache/{key}`         | Remove entry; returns 204 on success.                        |
| POST   | `/cache/flush`         | Flush all shards (admin only).                               |
| GET    | `/stats`               | Prometheus metrics endpoint.                                 |
| GET    | `/health`              | Liveness/readiness check.                                    |
| GET    | `/config`              | Retrieve current configuration (admin).                      |
| PUT    | `/config`              | Update configuration (admin).                                |

## 4. Deployment & Operations

- **Containerization**: Docker image using multi‑stage build; base `distroless` or `scratch` for minimal attack surface.
- **Orchestration**: Kubernetes Deployment with Horizontal Pod Autoscaler (HPA) based on CPU utilization or custom metric `cache_get_latency_seconds_p99`.
- **Configuration**: ConfigMap for shard count, replication factor, eviction policy, TTL wheel size, persistence settings, rate‑limit quotas.
- **Service Discovery**: Kubernetes internal DNS or Consul; clients retrieve the list of cache nodes via a headless service.
- **Backup / Snapshot**: Periodic snapshotting of the persistence store; restore by replaying into a new cluster.
- **Upgrade Strategy**: Rolling update; protocol version compatibility ensures zero‑downtime.
- **Chaos Testing**: Periodic pod kills, network latency injection, and clock skew tests using LitmusChaos or Gremlin to verify eventual consistency and no data loss.

## 5. Performance Considerations

- **Read Path**: O(1) hash map lookup + optional TTL check; latency dominated by network and lock‑striping overhead (target < 1 ms p99).
- **Write Path**: O(1) update + background replication; write‑behind decouples durability latency from client‑visible latency.
- **Memory Efficiency**: slab allocation or jemalloc to reduce fragmentation; optional value compression (Snappy/LZ4) for large payloads.
- **Network**: UDP‑based memcached‑style binary protocol for low‑latency LAN; TCP with keepalive as fallback for cross‑AZ or internet.
- **Benchmarks**: Target > 500 k GET/sec per instance with < 1 ms p99 latency on modest hardware (8 vCPU, 32 GB RAM).
- **Hot‑Key Mitigation**: per‑key rate limiting and automatic sharding of heavily accessed keys (split‑hot‑key technique).

## 6. Failure Modes & Mitigations

| Failure Mode               | Impact                              | Mitigation                                                    |
|----------------------------|-------------------------------------|---------------------------------------------------------------|
| Node crash                 | Potential data loss if N=1          | Replication factor ≥ 2; read‑repair on replica sync.          |
| Network partition          | Split‑brain                         | Quorum writes (require acknowledgment from majority); reject writes if minority. |
| Memory exhaustion          | OOM kills                           | Eviction watermarks; HPA scales pods; OOM killer logs.        |
| Hot‑key overload           | Queue buildup, increased latency    | Per‑key rate limiting; automatic hot‑key sharding.            |
| Persistent store lag       | Stale cache on restart              | Write‑behind acknowledgment; sync flush on graceful shutdown. |
| Malicious large payload    | DoS / memory exhaustion             | Input size limits; rate limiting; early rejection.            |
| Clock skew                 | Incorrect TTL expiry                | Use monotonic timers for TTL; sync clocks via NTP; reject extreme skew. |

## 7. Testing Strategy

- **Unit Tests**: data‑structure correctness under concurrency (using JCStress, loom, or stress‑test harness).
- **Integration Tests**: end‑to‑end API behavior with mocked persistence; verify replication, eviction, and TTL.
- **Chaos Engineering**: inject pod kills, network latency, packet loss, clock skew; verify eventual consistency and no data corruption.
- **Performance Tests**: load generator (wrk, k6, or vegeta) to validate latency/throughput targets under varying load.
- **Security Scan**: static analysis (Bandit, SonarQube, SpotBugs), dependency check (OWASP Dependency‑Check), and container image scanning (Trivy).
- **Fault Injection**: simulate persistence store failures, network partitions, and OOM conditions.

## 8. Positive Observations (What’s Done Well)

- Clear separation of concerns (API, routing, storage, observability).
- Use of proven techniques: consistent hashing, lock striping, TTL wheel, LRU/LFU.
- Emphasis on observability from the outset (metrics, logging, tracing, health).
- Security considerations integrated (input validation, auth, rate limiting, encryption).
- Designed for cloud‑native deployment (containers, K8s, HPA).

## 9. Recommended Priority Order for Fixes / Enhancements

1. Implement core shard with concurrent hash map + LRU eviction + TTL wheel.
2. Add consistent hashing routing layer with virtual nodes.
3. Build API layer with basic GET/SET/DELETE and admin endpoints.
4. Introduce asynchronous replication and health‑check endpoints.
5. Add persistence write‑behind (optional) and warm‑start logic.
6. Implement metrics (Prometheus), structured logging, and OpenTelemetry tracing.
7. Harden security: input validation, JWT auth, rate limiting, TLS.
8. Performance tuning: slab allocation, value compression, benchmarking.
9. Operational tooling: Helm charts, Kubernetes manifests, CI/CD pipeline.
10. Chaos testing and production readiness review.

---
*Design by NEXUS‑ANALYZER – ready for implementation.*