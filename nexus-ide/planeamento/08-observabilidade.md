# NEXUS IDE — Observabilidade Detalhada

## 1. Visão Geral da Observabilidade

Observabilidade em NEXUS IDE é implementada através de três pilares principais: métricas (Prometheus), tracing (OpenTelemetry), e logging (estruturado). Esta abordagem permite monitorizar o sistema, debugar problemas, e entender o comportamento dos agentes em tempo real.

### 1.1 Três Pilares da Observabilidade

```
┌─────────────────────────────────────────────────────────────┐
│                   Observabilidade NEXUS IDE                   │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Métricas    │  │   Tracing    │  │    Logs      │      │
│  │  (Prometheus)│  │(OpenTelemetry)│  │(Estruturados)│      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         │                  │                  │              │
│         ↓                  ↓                  ↓              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │            Grafana Dashboard (Visualização)          │   │
│  └─────────────────────────────────────────────────────┘   │
│         │                  │                  │              │
│         ↓                  ↓                  ↓              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         Alerting (Prometheus Alertmanager)           │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Por que Observabilidade?

**Alternativas:**
- **Sem observabilidade:** Debugging cego, sem visibilidade
- **Logs apenas:** Não tem métricas, não tem tracing
- **Apenas métricas:** Não tem contexto de logs/tracing

**Por que Três Pilares?**
- **Métricas:** Quantitativo (quantos, quanto tempo)
- **Tracing:** Qualitativo (por onde passou, quanto tempo em cada passo)
- **Logs:** Contexto (o que aconteceu, por que)

## 2. Métricas (Prometheus)

### 2.1 Por que Prometheus?

**Alternativas:**
- **Datadog:** Cloud-only (custo, privacidade)
- **New Relic:** Similar ao Datadog
- **InfluxDB:** Time-series database, mas menos ecossistema
- **CloudWatch:** AWS-specific (lock-in)

**Por que Prometheus?**
- **Padrão da indústria:** CNCF project, amplamente adotado
- **Pull-based:** Mais seguro que push (agent não precisa de credenciais)
- **Linguagem de query poderosa:** PromQL é expressivo
- **Alerting integrado:** Alertmanager nativo
- **Grafana dashboards:** Integração perfeita
- **Open-source:** Sem custo, privacidade total

### 2.2 Métricas Customizadas

**Implementação em `backend/observability/metrics.py`:**

```python
from prometheus_client import Counter, Histogram, Gauge, Summary

# Request metrics
requests_total = Counter(
    "nexus_requests_total",
    "Total requests received",
    ["agent", "model", "status"]
)

response_latency_seconds = Histogram(
    "nexus_response_latency_seconds",
    "Response latency in seconds",
    ["agent", "model"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60)
)

# Token metrics
tokens_generated_total = Counter(
    "nexus_tokens_generated_total",
    "Total tokens generated",
    ["agent", "model"]
)

tokens_per_second = Gauge(
    "nexus_tokens_per_second",
    "Tokens generated per second",
    ["agent", "model"]
)

# Agent pool metrics
agent_pool_active = Gauge(
    "nexus_agent_pool_active",
    "Number of active agents in pool",
    ["model"]
)

agent_pool_available = Gauge(
    "nexus_agent_pool_available",
    "Number of available agent slots",
    ["model"]
)

agent_pool_queue_depth = Gauge(
    "nexus_agent_pool_queue_depth",
    "Number of requests waiting in queue",
    ["model"]
)

# ReAct metrics
react_iterations_total = Counter(
    "nexus_react_iterations_total",
    "Total ReAct iterations executed",
    ["agent"]
)

react_iterations_per_request = Histogram(
    "nexus_react_iterations_per_request",
    "Number of ReAct iterations per request",
    ["agent"],
    buckets=(1, 2, 3, 4, 5, 6, 7)
)

react_tool_invocations_total = Counter(
    "nexus_react_tool_invocations_total",
    "Total tool invocations",
    ["tool", "agent"]
)

react_tool_duration_seconds = Histogram(
    "nexus_react_tool_duration_seconds",
    "Tool execution duration",
    ["tool", "agent"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30)
)

# Error metrics
errors_total = Counter(
    "nexus_errors_total",
    "Total errors",
    ["agent", "model", "error_type"]
)

error_rate = Gauge(
    "nexus_error_rate",
    "Error rate (errors per request)",
    ["agent", "model"]
)

# Ollama metrics
ollama_requests_total = Counter(
    "nexus_ollama_requests_total",
    "Total Ollama requests",
    ["model"]
)

ollama_latency_seconds = Histogram(
    "nexus_ollama_latency_seconds",
    "Ollama request latency",
    ["model"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30)
)

ollama_queue_depth = Gauge(
    "nexus_ollama_queue_depth",
    "Ollama request queue depth",
    ["model"]
)

# Web search metrics
web_search_total = Counter(
    "nexus_web_search_total",
    "Total web searches",
    ["provider"]
)

web_search_latency_seconds = Histogram(
    "nexus_web_search_latency_seconds",
    "Web search latency",
    ["provider"],
    buckets=(0.5, 1, 2, 5, 10)
)

# Code execution metrics
code_execution_total = Counter(
    "nexus_code_execution_total",
    "Total code executions",
    ["language"]
)

code_execution_duration_seconds = Histogram(
    "nexus_code_execution_duration_seconds",
    "Code execution duration",
    ["language"],
    buckets=(1, 5, 10, 20, 30)
)

code_execution_success_total = Counter(
    "nexus_code_execution_success_total",
    "Successful code executions",
    ["language"]
)

code_execution_failure_total = Counter(
    "nexus_code_execution_failure_total",
    "Failed code executions",
    ["language", "error_type"]
)

# Dashboard metrics
dashboard_queries_total = Counter(
    "nexus_dashboard_queries_total",
    "Total dashboard queries"
)

dashboard_anomalies_total = Counter(
    "nexus_dashboard_anomalies_total",
    "Total anomalies detected by dashboard",
    ["severity"]
)
```

### 2.3 Por que estas Métricas?

**requests_total:**
- Monitoriza volume de requests
- Detecta spikes (possível ataque ou bug)
- Permite capacity planning

**response_latency_seconds:**
- Monitoriza performance
- Detecta degradação
- Buckets permitem ver distribuição (p50, p95, p99)

**tokens_generated_total:**
- Monitoriza custo (tokens = tempo GPU)
- Permite billing interno (se necessário)
- Permite otimização de prompts

**agent_pool_*:**
- Monitoriza utilização de recursos
- Detecta resource exhaustion
- Permite tuning de concurrency limits

**react_*:**
- Monitoriza eficiência do ReAct loop
- Detecta loops ineficientes
- Permite tuning de max_iterations

**errors_total:**
- Monitoriza taxa de erros
- Detecta regressões
- Permite debugging rápido

**ollama_*:**
- Monitoriza saúde do Ollama
- Detecta timeouts, OOM
- Permite tuning de Ollama config

### 2.4 Exposição de Métricas

```python
from fastapi import FastAPI
from prometheus_client import make_asgi_app

app = FastAPI()

# Add prometheus asgi middleware
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

**Endpoint:**
- `GET /metrics` - Expose métricas em formato Prometheus

**Por que /metrics?**
- Padrão Prometheus (todos os exporters usam)
- Prometheus scrape este endpoint periodicamente
- Pull-based (mais seguro que push)

### 2.5 Configuração Prometheus

```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'nexus-ide'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 10s
```

**Por que 15s scrape_interval?**
- Balance entre granularidade e overhead
- 15s é suficiente para detetar problemas
- Menos overhead que 5s (mais requests)

## 3. Tracing (OpenTelemetry)

### 3.1 Por que OpenTelemetry?

**Alternativas:**
- **Jaeger SDK:** Vendor-specific (Jaeger)
- **Zipkin SDK:** Vendor-specific (Zipkin)
- **Datadog APM:** Cloud-only

**Por que OpenTelemetry?**
- **Vendor-neutral:** Pode exportar para Jaeger, Zipkin, Datadog, etc.
- **Padrão da indústria:** CNCF project
- **Multi-linguagem:** Python, JavaScript, Go, etc.
- **Unified:** Traces, metrics, logs em um framework
- **Extensível:** Custom spans, attributes

### 3.2 Implementação

```python
# backend/observability/tracing.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME

# Configure tracing
resource = Resource(attributes={
    SERVICE_NAME: "nexus-ide-backend"
})

provider = TracerProvider(resource=resource)
jaeger_exporter = JaegerExporter(
    agent_host_name="localhost",
    agent_port=6831,
)
processor = BatchSpanProcessor(jaeger_exporter)
provider.add_span_processor(processor)

trace.set_tracer_provider(provider)

tracer = trace.get_tracer(__name__)
```

### 3.3 Spans

```python
async def process_request(request: Request):
    with tracer.start_as_current_span("process_request") as span:
        span.set_attribute("session_id", request.session_id)
        span.set_attribute("query", request.query)
        
        with tracer.start_as_current_span("routing") as routing_span:
            decision = await route_with_model(request.query)
            routing_span.set_attribute("routed_agent", decision.primary_agent)
            routing_span.set_attribute("confidence", decision.routing_confidence)
        
        with tracer.start_as_current_span("agent_execution") as agent_span:
            agent_span.set_attribute("agent", decision.primary_agent)
            agent_span.set_attribute("model", get_model_for_agent(decision.primary_agent))
            
            async for chunk in agent.run(request):
                yield chunk
```

### 3.4 Por que Tracing?

**Debugging Distribuído:**
- Rastreia request através de múltiplos componentes
- Mostra onde tempo é gasto
- Mostra dependências entre componentes

**Performance Profiling:**
- Identifica bottlenecks
- Mostra distribuição de latência
- Permite otimização

**Root Cause Analysis:**
- Mostra o caminho completo de um erro
- Mostra quais componentes falharam
- Permite debugging rápido

### 3.5 Jaeger

**Por que Jaeger?**
- **Open-source:** Sem custo
- **UI rica:** Visualização de traces
- **Search:** Busca por traces
- **Integration:** Integração perfeita com OpenTelemetry

**Alternativas:**
- **Zipkin:** UI menos rica
- **Tempo:** Mais complexo
- **Grafana Tempo:** Excelente, mas Jaeger é mais maduro

## 4. Logging

### 4.1 Estrutura de Logs

**Formato JSON:**

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "INFO",
  "message": "Agent execution started",
  "context": {
    "session_id": "abc-123",
    "agent": "CODER",
    "model": "expert",
    "query": "Implement REST API"
  },
  "span_id": "1234",
  "trace_id": "5678"
}
```

**Por que JSON?**
- **Estruturado:** Fácil de parse
- **Queryable:** Pode buscar por campos específicos
- **Machine-readable:** Ferramentas podem processar automaticamente
- **Consistente:** Sempre mesmo formato

### 4.2 Níveis de Log

| Nível | Quando Usar | Exemplo |
|-------|-------------|---------|
| DEBUG | Informação detalhada para debugging | "Agent acquired semaphore" |
| INFO | Informação normal de operação | "Request received from session abc-123" |
| WARNING | Algo inesperado, mas não erro | "Fallback activated: EXPERT → LARGE" |
| ERROR | Erro que não para execução | "Tool execution failed: timeout" |
| CRITICAL | Erro que para execução | "Ollama connection lost" |

### 4.3 Implementação

```python
import structlog
import logging

# Configure structlog
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Usage
logger.info(
    "Agent execution started",
    session_id="abc-123",
    agent="CODER",
    model="expert",
    query="Implement REST API"
)
```

**Por que structlog?**
- **Estruturado:** Logs são dicts, não strings
- **Context:** Adiciona contexto automaticamente
- **Performance:** Rápido (compilado)
- **Flexível:** Múltiplos formatters (JSON, console)

### 4.4 Log Aggregation

**Para produção:**
- **Loki:** Grafana Loki (lightweight, Prometheus-like)
- **ELK Stack:** Elasticsearch, Logstash, Kibana (mais pesado)
- **CloudWatch:** AWS (se usando AWS)

**Para desenvolvimento:**
- **Stdout:** Logs para console
- **File:** Logs para ficheiro (rotating)

## 5. Event Bus (Redis Pub/Sub)

### 5.1 Responsabilidade

O Event Bus emite eventos para observabilidade em tempo real. É usado pelo DASHBOARD AGENT para monitorizar o sistema.

### 5.2 Implementação

```python
# backend/observability/events.py
from dataclasses import dataclass
from enum import Enum
from typing import Any
import json
import redis

class EventType(str, Enum):
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    TOOL_INVOKE = "tool_invoke"
    TOOL_ERROR = "tool_error"
    ROUTING_DECISION = "routing_decision"
    FALLBACK = "fallback"
    ANOMALY = "anomaly"

@dataclass
class Event:
    type: EventType
    session_id: str
    agent: str | None = None
    model: str | None = None
    data: dict[str, Any] = None
    timestamp: str = None

class EventBus:
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis = redis.from_url(redis_url)
        self.channel = "nexus_events"
    
    async def publish(self, event: Event) -> None:
        """Publish event to Redis Pub/Sub."""
        event_dict = {
            "type": event.type.value,
            "session_id": event.session_id,
            "agent": event.agent,
            "model": event.model,
            "data": event.data,
            "timestamp": event.timestamp or datetime.utcnow().isoformat(),
        }
        await self.redis.publish(self.channel, json.dumps(event_dict))
    
    async def subscribe(self, pattern: str = "#") -> AsyncIterator[Event]:
        """Subscribe to events matching pattern."""
        pubsub = self.redis.pubsub()
        await pubsub.psubscribe(pattern)
        
        async for message in pubsub.listen():
            if message["type"] == "pmessage":
                event_dict = json.loads(message["data"])
                yield Event(**event_dict)
```

### 5.3 Eventos Emitidos

**agent_start:**
```json
{
  "type": "agent_start",
  "session_id": "abc-123",
  "agent": "CODER",
  "model": "expert",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**agent_end:**
```json
{
  "type": "agent_end",
  "session_id": "abc-123",
  "agent": "CODER",
  "model": "expert",
  "data": {
    "tokens": 1500,
    "latency_seconds": 5.2,
    "iterations": 3
  },
  "timestamp": "2024-01-15T10:30:05Z"
}
```

**tool_invoke:**
```json
{
  "type": "tool_invoke",
  "session_id": "abc-123",
  "agent": "CODER",
  "data": {
    "tool": "READ_FILE",
    "params": {"path": "models.py"}
  },
  "timestamp": "2024-01-15T10:30:01Z"
}
```

**fallback:**
```json
{
  "type": "fallback",
  "session_id": "abc-123",
  "data": {
    "from_agent": "EXPERT",
    "to_agent": "LARGE",
    "reason": "Timeout"
  },
  "timestamp": "2024-01-15T10:30:10Z"
}
```

**anomaly:**
```json
{
  "type": "anomaly",
  "data": {
    "metric": "latency_p95",
    "threshold": 5.0,
    "value": 12.3,
    "severity": "warning"
  },
  "timestamp": "2024-01-15T10:35:00Z"
}
```

### 5.4 Por que Redis Pub/Sub?

**Alternativas:**
- **Kafka:** Overkill para este caso de uso
- **RabbitMQ:** Mais complexo
- **HTTP polling:** Ineficiente

**Por que Redis Pub/Sub?**
- **Já usado:** Redis já é usado para cache/queue
- **Real-time:** Eventos entregues instantaneamente
- **Multi-consumer:** Dashboard, logging, metrics podem subscrever
- **Lightweight:** Não precisa de message broker pesado

## 6. Dashboard de Observabilidade

### 6.1 Grafana Dashboards

**Dashboard Principal:**

**Panel 1: Requests por Segundo**
- Query: `rate(nexus_requests_total[1m])`
- Type: Graph
- Visualization: Line chart

**Panel 2: Latência p95**
- Query: `histogram_quantile(0.95, rate(nexus_response_latency_seconds_bucket[5m]))`
- Type: Graph
- Visualization: Line chart

**Panel 3: Taxa de Erros**
- Query: `rate(nexus_errors_total[5m]) / rate(nexus_requests_total[5m])`
- Type: Graph
- Visualization: Line chart

**Panel 4: Agent Pool Utilização**
- Query: `nexus_agent_pool_active`
- Type: Stat
- Visualization: Gauge

**Panel 5: Tokens por Segundo**
- Query: `rate(nexus_tokens_generated_total[1m])`
- Type: Graph
- Visualization: Line chart

**Panel 6: ReAct Iterações por Request**
- Query: `histogram_quantile(0.95, nexus_react_iterations_per_request)`
- Type: Graph
- Visualization: Line chart

### 6.2 Por que Grafana?

**Alternativas:**
- **Prometheus UI:** Básico, não customizável
- **Kibana:** Focado em logs, não métricas
- **Datadog:** Cloud-only

**Por que Grafana?**
- **Padrão da indústria:** Amplamente usado com Prometheus
- **Customizável:** Dashboards altamente customizáveis
- **Rich plugins:** Múltiplos plugins (heatmap, pie chart, etc.)
- **Open-source:** Sem custo
- **Alerting:** Alerting integrado

## 7. Alerting

### 7.1 Prometheus Alertmanager

**Configuração:**

```yaml
# alertmanager.yml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'severity']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 12h
  receiver: 'default'
  
  routes:
  - match:
      severity: critical
    receiver: 'pagerduty'
  - match:
      severity: warning
    receiver: 'slack'

receivers:
- name: 'default'
  webhook_configs:
  - url: 'http://localhost:5000/webhook'

- name: 'pagerduty'
  pagerduty_configs:
  - service_key: 'PAGERDUTY_SERVICE_KEY'

- name: 'slack'
  slack_configs:
  - api_url: 'SLACK_WEBHOOK_URL'
    channel: '#alerts'
```

### 7.2 Regras de Alerta

```yaml
# alerts.yml
groups:
- name: nexus_ide_alerts
  rules:
  # High error rate
  - alert: HighErrorRate
    expr: rate(nexus_errors_total[5m]) / rate(nexus_requests_total[5m]) > 0.1
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "High error rate detected"
      description: "Error rate is {{ $value | humanizePercentage }}"

  # High latency
  - alert: HighLatency
    expr: histogram_quantile(0.95, rate(nexus_response_latency_seconds_bucket[5m])) > 10
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High latency detected"
      description: "P95 latency is {{ $value }}s"

  # Agent pool exhaustion
  - alert: AgentPoolExhaustion
    expr: nexus_agent_pool_available == 0
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "Agent pool exhausted"
      description: "No available agent slots for model {{ $labels.model }}"

  # Ollama connection lost
  - alert: OllamaConnectionLost
    expr: rate(nexus_ollama_requests_total[5m]) == 0
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "Ollama connection lost"
      description: "No Ollama requests in last 5 minutes"

  # Code execution failures
  - alert: CodeExecutionFailures
    expr: rate(nexus_code_execution_failure_total[5m]) / rate(nexus_code_execution_total[5m]) > 0.5
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High code execution failure rate"
      description: "Code execution failure rate is {{ $value | humanizePercentage }}"
```

### 7.3 Por que estas Regras?

**HighErrorRate (>10%):**
- 10% de erros é crítico (indica problema sério)
- 5m for: Previne falsos positivos (spikes temporários)
- Critical: Requer ação imediata

**HighLatency (>10s p95):**
- 10s p95 é lento (normal deve ser <5s)
- 5m for: Previne falsos positivos
- Warning: Não crítico, mas precisa de atenção

**AgentPoolExhaustion (0 available):**
- 0 available significa fila está cheia
- 2m for: Previne falsos positivos
- Critical: Sistema está sobrecarregado

**OllamaConnectionLost (0 requests in 5m):**
- 0 requests em 5m indica Ollama down
- 2m for: Previne falsos positivos (períodos de baixa atividade)
- Critical: Sistema não funciona sem Ollama

**CodeExecutionFailures (>50%):**
- 50% de falhas é muito alto
- 5m for: Previne falsos positivos
- Warning: Pode indicar problema com sandbox

## 8. Dashboard Agent (Observabilidade Ativa)

### 8.1 Responsabilidade

O DASHBOARD AGENT monitoriza métricas continuamente, deteta anomalias, e responde a perguntas em linguagem natural sobre o estado do sistema.

### 8.2 Loop de Monitorização

```python
async def monitor_loop(self) -> None:
    """Background loop - runs continuously."""
    while True:
        # Scrape metrics from Prometheus
        metrics = await scrape_prometheus_metrics()
        
        # Detect anomalies
        anomalies = detect_anomalies(metrics)
        
        # Emit events if anomalies detected
        for anomaly in anomalies:
            await event_bus.publish(Event(
                type=EventType.ANOMALY,
                data=anomaly,
            ))
        
        # Sleep 10 seconds
        await asyncio.sleep(10)
```

### 8.3 Detecção de Anomalias

```python
def detect_anomalies(metrics: dict) -> list[Anomaly]:
    """Detect anomalies in metrics."""
    anomalies = []
    
    # Latency anomaly
    latency_p95 = metrics.get("latency_p95", 0)
    if latency_p95 > 10.0:
        anomalies.append({
            "metric": "latency_p95",
            "threshold": 10.0,
            "value": latency_p95,
            "severity": "warning",
        })
    
    # Error rate anomaly
    error_rate = metrics.get("error_rate", 0)
    if error_rate > 0.1:
        anomalies.append({
            "metric": "error_rate",
            "threshold": 0.1,
            "value": error_rate,
            "severity": "critical",
        })
    
    # Queue depth anomaly
    queue_depth = metrics.get("agent_pool_queue_depth_expert", 0)
    if queue_depth > 5:
        anomalies.append({
            "metric": "agent_pool_queue_depth_expert",
            "threshold": 5,
            "value": queue_depth,
            "severity": "warning",
        })
    
    return anomalies
```

### 8.4 Q&A de Métricas

**Exemplo:**

```
User: "Why is latency high?"
Dashboard Agent:
1. Query Prometheus for latency_p95
2. Identify spike at specific time
3. Correlate with agent usage (EXPERT was overloaded)
4. Generate response:
   "Latency increased from 2.3s to 12.3s at 10:30 AM.
    Correlation: EXPERT agent was at 100% capacity during this period.
    Recommendation: Consider routing similar queries to LARGE agent."
```

**Por que Observabilidade Ativa?**
- **Interpretação:** Não apenas mostrar dados, mas interpretar
- **Contexto:** Correlacionar múltiplas métricas
- **Ação:** Recomendar ações, não apenas alertar
- **Natural Language:** Acessível para não-especialistas

## 9. Conclusão

A observabilidade em NEXUS IDE é implementada através de:
- **Métricas:** Prometheus para monitorização quantitativa
- **Tracing:** OpenTelemetry para debugging distribuído
- **Logging:** Structlog para logs estruturados
- **Event Bus:** Redis Pub/Sub para eventos em tempo real
- **Dashboard:** Grafana para visualização
- **Alerting:** Prometheus Alertmanager para alertas
- **Observabilidade Ativa:** DASHBOARD AGENT para interpretação

Esta abordagem permite:
- **Debugging rápido:** Tracing mostra onde problemas ocorrem
- **Monitorização proativa:** Alertas antes de problemas críticos
- **Optimização:** Métricas mostram onde otimizar
- **Compreensão:** Dashboard Agent interpreta dados em linguagem natural
