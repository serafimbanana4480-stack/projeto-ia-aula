# NEXUS IDE — Escalabilidade Detalhada

## 1. Visão Geral da Escalabilidade

Escalabilidade em NEXUS IDE é desenhada para suportar desde um único utilizador (local) até múltiplos utilizadores simultâneos (production). A arquitetura suporta escalabilidade vertical (mais recursos por máquina) e horizontal (mais máquinas), com estratégias específicas para cada componente.

### 1.1 Dimensões de Escalabilidade

```
┌─────────────────────────────────────────────────────────────┐
│                   Scalability Dimensions                      │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Vertical   │  │  Horizontal  │  │   Geographic │      │
│  │   Scale      │  │   Scale      │  │   Scale      │      │
│  │              │  │              │  │              │      │
│  │ Mais CPU/RAM │  │ Mais máquinas│  │ Mais regiões │      │
│  │ Mais GPU VRAM│  │ Load balancer│  │ CDN, Edge    │      │
│  │ Mais storage │  │ Kubernetes   │  │ Multi-cloud  │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Objetivos de Escalabilidade

- **Single User (Local):** 1 utilizador, 1 máquina (RTX 3060 12GB)
- **Small Team (Staging):** 5-10 utilizadores, 1 máquina (RTX 4070 12GB)
- **Medium Organization (Production):** 50-100 utilizadores, 3 máquinas (RTX 4090 24GB)
- **Large Organization (Enterprise):** 500+ utilizadores, 10+ máquinas (A100 40GB)

## 2. Escalabilidade Vertical

### 2.1 Hardware Requirements por Scale

| Scale | CPU | RAM | GPU | Storage | Utilizadores |
|-------|-----|-----|-----|---------|--------------|
| Local | 4 cores | 16GB | RTX 3060 12GB | 500GB SSD | 1 |
| Small | 8 cores | 32GB | RTX 4070 12GB | 1TB SSD | 5-10 |
| Medium | 16 cores | 64GB | RTX 4090 24GB | 2TB SSD | 50-100 |
| Large | 32 cores | 128GB | A100 40GB | 4TB SSD | 500+ |

### 2.2 Ollama Vertical Scaling

**Estratégia:**

```bash
# Usar GPU com mais VRAM para rodar modelos maiores
# RTX 3060 12GB → EXPERT (32b) com quantização 4-bit
# RTX 4090 24GB → EXPERT (32b) com quantização 8-bit ou FP16
# A100 40GB → EXPERT (32b) FP16 + outros modelos simultâneos

# Ajustar context window baseado em VRAM
# 12GB VRAM → 16k context window
# 24GB VRAM → 32k context window
# 40GB VRAM → 64k context window
```

**Por que Context Window por VRAM?**
- Context window usa VRAM linearmente
- Mais VRAM = mais context window
- Maior context window = melhor compreensão

### 2.3 Backend Vertical Scaling

**Estratégia:**

```python
# Ajustar workers baseado em CPU
# 4 cores → 4 workers
# 8 cores → 8 workers
# 16 cores → 16 workers

# uvicorn command
uvicorn orchestrator.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers ${CPU_CORES} \
  --worker-class uvicorn.workers.UvicornWorker \
  --loop uvloop \
  --limit-concurrency ${WORKERS * 25}
```

**Por que Workers por Core?**
- 1 worker por core é o sweet spot
- Mais workers que cores = context switching overhead
- Menos workers que cores = subutilização de CPU

### 2.4 Redis Vertical Scaling

**Estratégia:**

```bash
# Ajustar maxmemory baseado em RAM
# 16GB RAM → 8GB maxmemory
# 32GB RAM → 16GB maxmemory
# 64GB RAM → 32GB maxmemory

# redis.conf
maxmemory ${RAM / 2}gb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
save 60 10000
```

**Por que maxmemory = RAM / 2?**
- Redis precisa de RAM para operações
- Deixar espaço para OS e outros processos
- Previne OOM (out-of-memory)

## 3. Escalabilidade Horizontal

### 3.1 Kubernetes Horizontal Pod Autoscaler

**Configuração HPA:**

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: nexus-backend-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: nexus-backend
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15
```

**Por que 70% CPU, 80% Memory?**
- **70% CPU:** Permite headroom para spikes
- **80% Memory:** Redis é memory-heavy, permite mais utilização
- **Stabilization window:** Previne flapping (scale up/down rápido)

### 3.2 Load Balancing

**Nginx Load Balancer:**

```nginx
upstream nexus_backend {
    least_conn;
    server backend-1:8000 max_fails=3 fail_timeout=30s;
    server backend-2:8000 max_fails=3 fail_timeout=30s;
    server backend-3:8000 max_fails=3 fail_timeout=30s;
}

server {
    location /api/ {
        proxy_pass http://nexus_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding off;
    }
}
```

**Por que least_conn?**
- **Least connections:** Balanceia carga baseado em conexões ativas
- **Melhor que round-robin:** Considera carga real de cada servidor
- **Melhor que IP hash:** Não causa sticky session (que não é necessário)

### 3.3 Redis Cluster

**Configuração Redis Cluster:**

```yaml
# redis-cluster.yml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis-cluster
spec:
  serviceName: redis-cluster
  replicas: 6
  template:
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        command:
        - redis-server
        - --cluster-enabled yes
        - --cluster-config-file nodes.conf
        - --cluster-node-timeout 5000
        - --appendonly yes
        - --port 6379
        ports:
        - containerPort: 6379
        volumeMounts:
        - name: data
          mountPath: /data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ "ReadWriteOnce" ]
      resources:
        requests:
          storage: 10Gi
```

**Por que Redis Cluster?**
- **Escalabilidade horizontal:** Distribui dados em múltiplos nós
- **Alta disponibilidade:** Se um nó falha, outros continuam
- **Performance:** Múltiplos nós = mais throughput

**Por que 6 replicas?**
- **3 masters:** 3 shards para distribuir dados
- **3 replicas:** Cada master tem 1 replica (redundância)
- **Quorum:** 3 masters + 3 replicas = quorum de 4 (maioria)

### 3.4 Ollama Horizontal Scaling

**Estratégia:**

```yaml
# ollama-cluster.yml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: ollama
        image: ollama/ollama:latest
        resources:
          limits:
            nvidia.com/gpu: 1
        volumeMounts:
        - name: models
          mountPath: /root/.ollama
      nodeSelector:
        gpu: "true"
```

**Por que 3 replicas?**
- **3 GPUs:** 3 GPUs para balancear carga
- **Redundância:** Se uma GPU falha, outras continuam
- **Throughput:** 3 GPUs = 3x throughput

**Desafio:** Ollama não suporta cluster nativo
- **Solução:** Load balancer em frente de Ollama
- **Limitação:** Cada instância tem modelos independentes (não compartilha estado)

## 4. Escalabilidade por Componente

### 4.1 Backend Scaling

**Estratégia:**

```
┌──────────────┐
│  Nginx LB    │
└──────┬───────┘
       │
       ├─→ Backend Pod 1 (CPU: 2, RAM: 4GB)
       ├─→ Backend Pod 2 (CPU: 2, RAM: 4GB)
       └─→ Backend Pod 3 (CPU: 2, RAM: 4GB)
```

**Métricas:**
- **Requests per second:** 100 req/s por pod
- **3 pods = 300 req/s total**
- **Scale up:** Se > 210 req/s (70% utilização)
- **Scale down:** Se < 90 req/s (30% utilização)

**Session Management:**
- **Stateless:** Backend é stateless (JWT tokens)
- **Redis:** Sessões armazenadas em Redis (compartilhado)
- **Sticky session:** Não necessário (stateless)

### 4.2 Frontend Scaling

**Estratégia:**

```
┌──────────────┐
│  Nginx LB    │
└──────┬───────┘
       │
       ├─→ Frontend Pod 1 (CPU: 0.5, RAM: 1GB)
       ├─→ Frontend Pod 2 (CPU: 0.5, RAM: 1GB)
       └─→ Frontend Pod 3 (CPU: 0.5, RAM: 1GB)
```

**Métricas:**
- **Concurrent users:** 100 users por pod
- **3 pods = 300 users total**
- **Scale up:** Se > 210 users (70% utilização)
- **Static assets:** Servidos via CDN (Cloudflare)

**CDN Strategy:**
- **Static assets:** JavaScript, CSS, images
- **Cache:** Cache de 1 ano com hash de versão
- **Edge:** Distribuído globalmente (menos latência)

### 4.3 Ollama Scaling

**Estratégia:**

```
┌──────────────┐
│  Ollama LB   │
└──────┬───────┘
       │
       ├─→ Ollama Pod 1 (GPU: RTX 4090 24GB)
       ├─→ Ollama Pod 2 (GPU: RTX 4090 24GB)
       └─→ Ollama Pod 3 (GPU: RTX 4090 24GB)
```

**Métricas:**
- **Requests per second:** 10 req/s por pod
- **3 pods = 30 req/s total**
- **Model loading:** Cada pod carrega modelos independentemente
- **VRAM:** 24GB por pod (EXPERT 32b com quantização 8-bit)

**Challenges:**
- **Cold start:** Se pod não tem modelo carregado, precisa carregar
- **Mitigação:** Pre-load modelos em startup, keep-alive

### 4.4 Redis Scaling

**Estratégia:**

```
┌──────────────┐
│  Redis       │
│  Cluster     │
└──────┬───────┘
       │
       ├─→ Master 1 (Shard 1)
       ├─→ Master 2 (Shard 2)
       ├─→ Master 3 (Shard 3)
       ├─→ Replica 1 (Shard 1)
       ├─→ Replica 2 (Shard 2)
       └─→ Replica 3 (Shard 3)
```

**Métricas:**
- **Operations per second:** 100k ops/s por cluster
- **Memory:** 10GB per shard (30GB total)
- **Persistence:** RDB + AOF (backup + real-time)

**Sharding Strategy:**
- **Hash tags:** Keys com hash tags vão para mesmo shard
- **Session affinity:** Sessões de mesmo utilizador vão para mesmo shard (opcional)

### 4.5 ChromaDB Scaling

**Estratégia:**

```
┌──────────────┐
│  ChromaDB    │
│  (Single)    │
└──────────────┘
```

**Métricas:**
- **Documents:** 100k documentos
- **Memory:** 2GB RAM
- **Storage:** 10GB SSD

**Scaling:**
- **Phase 1:** Single instance (suficiente para MVP)
- **Phase 2:** ChromaDB Server (se necessário)
- **Phase 3:** ChromaDB Cluster (se necessário)

**Por que Single Instance?**
- ChromaDB single instance é suficiente para MVP
- ChromaDB Server/Cluster é mais complexo
- Pode migrar depois se necessário

## 5. Geographic Scaling

### 5.1 Multi-Region Deployment

**Estratégia:**

```
┌─────────────────────────────────────────────────────────────┐
│                    Multi-Region Deployment                   │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Region A   │  │   Region B   │  │   Region C   │      │
│  │  (US East)   │  │ (US West)    │  │ (Europe)     │      │
│  │              │  │              │  │              │      │
│  │ Backend x3   │  │ Backend x3   │  │ Backend x3   │      │
│  │ Frontend x2  │  │ Frontend x2  │  │ Frontend x2  │      │
│  │ Ollama x2    │  │ Ollama x2    │  │ Ollama x2    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         │                  │                  │              │
│         └──────────────────┴──────────────────┘              │
│                            │                                 │
│                    ┌───────▼────────┐                         │
│                    │  Global DNS    │                         │
│                    │  (Route53)    │                         │
│                    └────────────────┘                         │
└─────────────────────────────────────────────────────────────┘
```

**Por que Multi-Region?**
- **Latência:** Utilizadores acessam região mais próxima
- **Redundância:** Se uma região falha, outras continuam
- **Compliance:** Dados podem ser armazenados em regiões específicas (GDPR)

**Challenges:**
- **Custo:** Multi-region é mais caro
- **Complexidade:** Gerenciar múltiplas regiões
- **Data sync:** Sincronizar dados entre regiões

**Mitigação:**
- **Phase 1:** Single region (suficiente para MVP)
- **Phase 2:** 2 regions (US East + Europe)
- **Phase 3:** 3+ regions (global)

### 5.2 CDN Strategy

**Estratégia:**

```
┌──────────────┐
│  Cloudflare  │
│     CDN      │
└──────┬───────┘
       │
       ├─→ Edge Location 1 (US East)
       ├─→ Edge Location 2 (US West)
       ├─→ Edge Location 3 (Europe)
       └─→ Edge Location 4 (Asia)
```

**O que Cache via CDN?**
- **Static assets:** JavaScript, CSS, images
- **API responses:** Cache de GET requests (se apropriado)
- **Pages:** Cache de páginas estáticas (se apropriado)

**Cache Rules:**
- **Static assets:** Cache 1 ano (com hash de versão)
- **API responses:** Cache 1 minuto (se idempotent)
- **Pages:** Cache 5 minutos (se estático)

## 6. Performance Optimization

### 6.1 Caching Strategy

**Multi-Level Caching:**

```
┌──────────────┐
│  Browser     │ ← Cache 1 (Browser cache)
└──────┬───────┘
       │
┌──────▼───────┐
│  CDN         │ ← Cache 2 (CDN cache)
└──────┬───────┘
       │
┌──────▼───────┐
│  Backend     │ ← Cache 3 (Redis cache)
└──────┬───────┘
       │
┌──────▼───────┐
│  Ollama      │ ← Cache 4 (Model cache)
└──────────────┘
```

**Cache Keys:**
- **Session context:** `session:{session_id}` (TTL: 1h)
- **Routing decision:** `routing:{query_hash}` (TTL: 24h)
- **Embeddings:** `embed:{content_hash}` (TTL: 7d)
- **API responses:** `api:{endpoint}:{params_hash}` (TTL: 1m)

### 6.2 Connection Pooling

**Redis Connection Pool:**

```python
# Redis connection pool
redis_pool = redis.ConnectionPool(
    host='localhost',
    port=6379,
    db=0,
    max_connections=50,
    socket_timeout=5,
    socket_connect_timeout=5,
)

redis_client = redis.Redis(connection_pool=redis_pool)
```

**Por que Connection Pooling?**
- **Performance:** Reutiliza conexões (menos overhead)
- **Escalabilidade:** Limite de conexões previne overload
- **Stability:** Timeout previne hanging

### 6.3 Async I/O

**Por que Async I/O?**
- **Concorrência:** Múltiplas requests podem ser processadas simultaneamente
- **Escalabilidade:** Async escala melhor que sync/threads
- **I/O-bound:** Backend é I/O-bound (LLM, Redis, HTTP)

**Exemplo:**

```python
# Sync (bloqueia thread)
def sync_request():
    response = requests.get("http://ollama:11434/api/generate")
    return response

# Async (não bloqueia thread)
async def async_request():
    async with httpx.AsyncClient() as client:
        response = await client.get("http://ollama:11434/api/generate")
        return response
```

### 6.4 Batch Processing

**Por que Batch Processing?**
- **Efficiency:** Múltiplas requests em uma chamada
- **Latency:** Menos round-trips
- **Throughput:** Mais requests por segundo

**Exemplo:**

```python
# Single request (inefficiente)
for query in queries:
    response = await ollama.generate(query)

# Batch request (efficient)
responses = await ollama.generate_batch(queries)
```

**Limitação:** Ollama não suporta batch nativo
- **Mitigação:** Usar asyncio.gather para requests paralelos

## 7. Monitoring Autoscaling

### 7.1 Prometheus Metrics for Autoscaling

**Métricas:**

```python
# Requests per second
requests_per_second = rate(nexus_requests_total[1m])

# CPU utilization
cpu_utilization = rate(process_cpu_seconds_total[5m])

# Memory utilization
memory_utilization = process_resident_memory_bytes / total_memory

# Queue depth
queue_depth = nexus_agent_pool_queue_depth

# Response latency
response_latency_p95 = histogram_quantile(0.95, nexus_response_latency_seconds)
```

### 7.2 Autoscaling Rules

**Scale Up Conditions:**
- CPU utilization > 70% por 5 minutos
- Memory utilization > 80% por 5 minutos
- Queue depth > 10 por 2 minutos
- Response latency p95 > 5s por 5 minutos

**Scale Down Conditions:**
- CPU utilization < 30% por 15 minutos
- Memory utilization < 40% por 15 minutos
- Queue depth = 0 por 10 minutos

**Por que estas thresholds?**
- **Scale up:** Previne overload antes de ser crítico
- **Scale down:** Economiza recursos, mas não flapping

## 8. Disaster Recovery for Scalability

### 8.1 High Availability

**Estratégia:**

```
┌─────────────────────────────────────────────────────────────┐
│                    High Availability Setup                    │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Primary AZ │  │  Secondary AZ │  │  Tertiary AZ │      │
│  │  (us-east-1) │  │  (us-west-2) │  │  (eu-west-1) │      │
│  │              │  │              │  │              │      │
│  │ Backend x3   │  │ Backend x3   │  │ Backend x3   │      │
│  │ Frontend x2  │  │ Frontend x2  │  │ Frontend x2  │      │
│  │ Ollama x2    │  │ Ollama x2    │  │ Ollama x2    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         │                  │                  │              │
│         └──────────────────┴──────────────────┘              │
│                            │                                 │
│                    ┌───────▼────────┐                         │
│                    │  Global Load   │                         │
│                    │  Balancer      │                         │
│                    │  (Route53)    │                         │
│                    └────────────────┘                         │
└─────────────────────────────────────────────────────────────┘
```

**Failover Strategy:**
- **Health checks:** Health checks a cada 10 segundos
- **Automatic failover:** Se primary AZ falha, traffic redirecionado
- **Data sync:** Redis replication entre AZs

### 8.2 Backup Strategy

**Backup Frequency:**
- **Code:** Continuous (Git)
- **Config:** Diário (automated)
- **Data:** Diário (automated)
- **Logs:** Semanal (retention 30 dias)

**Backup Storage:**
- **Local:** Backup local (rápido restore)
- **Remote:** S3 (cross-region backup)
- **Cold:** Glacier (long-term retention)

## 9. Cost Optimization

### 9.1 Cost per Scale

| Scale | Monthly Cost (AWS) | Breakdown |
|-------|-------------------|-----------|
| Local | $0 | Hardware próprio |
| Small | $200 | VPS ($150) + Storage ($50) |
| Medium | $800 | 3x VPS ($450) + Storage ($100) + Bandwidth ($250) |
| Large | $3000 | 10x VPS ($1500) + Storage ($300) + Bandwidth ($1200) |

### 9.2 Cost Optimization Strategies

**Spot Instances:**
- **Ollama pods:** Usar spot instances (até 90% discount)
- **Risk:** Pod pode ser preempted
- **Mitigação:** Re-launch automaticamente, usar multiple AZs

**Reserved Instances:**
- **Backend pods:** Usar reserved instances (até 40% discount)
- **Commit:** 1 ou 3 anos
- **Risk:** Commit de longo prazo

**Autoscaling:**
- **Scale down:** Reduz pods quando não em uso
- **Schedule:** Scale down durante horários de baixa atividade
- **Cost saving:** Reduz custo em ~30%

## 10. Conclusão

Escalabilidade de NEXUS IDE é desenhada para suportar:
- **Vertical scaling:** Mais recursos por máquina
- **Horizontal scaling:** Mais máquinas (Kubernetes HPA)
- **Geographic scaling:** Multi-region deployment
- **Performance optimization:** Caching, connection pooling, async I/O
- **High availability:** Multi-AZ, failover, backups
- **Cost optimization:** Spot instances, reserved instances, autoscaling

A escolha de estratégia depende do scale:
- **Local:** Vertical scaling (mais GPU VRAM)
- **Staging:** Horizontal scaling (Docker Compose)
- **Production:** Horizontal + geographic scaling (Kubernetes)
