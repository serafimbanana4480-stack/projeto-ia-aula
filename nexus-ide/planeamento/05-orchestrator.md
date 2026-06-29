# NEXUS IDE — Orchestrator e Routing Detalhados

## 1. Visão Geral do Orchestrator

O Orchestrator é o componente central do backend NEXUS IDE. Ele é responsável por:
- Receber requests do frontend via FastAPI
- Routing inteligente de queries para agentes apropriados
- Gerir pool de agentes com semáforos
- Coordenar o ciclo ReAct
- Gerir contexto de sessão
- Emitir eventos para observabilidade
- Implementar fallback chains

O Orchestrator é implementado como um serviço FastAPI em `backend/orchestrator/main.py` com módulos auxiliares para routing, agent pool, fallback, e context management.

### 1.1 Responsabilidades do Orchestrator

```
┌─────────────────────────────────────────────────────────────┐
│                    Orchestrator (FastAPI)                    │
│                                                              │
│  1. API Layer                                               │
│     ├── POST /api/chat (SSE stream)                         │
│     ├── GET /api/sessions/{id}/history                      │
│     ├── GET /api/models/status                               │
│     ├── POST /api/models/reload/{model_id}                  │
│     ├── GET /api/metrics/current                            │
│     ├── GET /api/dashboard/stream (SSE)                      │
│     └── File/Code endpoints                                 │
│                                                              │
│  2. Routing Layer                                           │
│     ├── Fast route (deterministic)                           │
│     ├── Route with model (ROUTER agent)                      │
│     └── Fallback chain                                       │
│                                                              │
│  3. Agent Pool                                              │
│     ├── Semaphores per model                                │
│     ├── Queue management                                     │
│     └── Resource limits                                     │
│                                                              │
│  4. ReAct Coordinator                                       │
│     ├── Loop management (max 7 iterations)                   │
│     ├── Tool invocation                                      │
│     └── Scratchpad management                               │
│                                                              │
│  5. Context Manager                                         │
│     ├── Session context (Redis)                              │
│     ├── Scratchpad per agent                                │
│     └── TTL management                                      │
│                                                              │
│  6. Event Bus                                               │
│     ├── Redis Pub/Sub                                        │
│     └── Event emission                                      │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Por que Orchestrator Separado?

**Alternativas Consideradas:**
- **Monolithic:** Todos os agentes no mesmo módulo
  - Con: Difícil de manter, acoplamento alto
- **Microservices:** Cada agente como serviço separado
  - Con: Overhead de rede, complexidade de deployment
- **Orchestrator Central:** Coordenação centralizada
  - Pro: Balance entre simplicidade e flexibilidade

**Decisão:** Orchestrator central com agentes como módulos:
- Simples de debug (single process)
- Fácil de testar (mockable)
- Flexível (pode evoluir para microservices se necessário)
- Performance baixo latência (no network overhead)

## 2. Routing Detalhado

### 2.1 Três Níveis de Routing

O routing em NEXUS IDE é implementado em três níveis, do mais rápido ao mais inteligente:

```
Query do Utilizador
        ↓
┌───────────────────────┐
│  Nível 1: Fast Route  │  ← Determinístico, zero custo
│  (Regras baseadas em  │
│   keywords)           │
└───────────┬───────────┘
            │ Se match → Agente direto
            │ Se não match ↓
┌───────────────────────┐
│  Nível 2: ROUTER     │  ← Modelo NANO (0.5b)
│  Agent               │  ← JSON decision
└───────────┬───────────┘
            │ Se sucesso → Agente
            │ Se timeout/error ↓
┌───────────────────────┐
│  Nível 3: Fallback    │  ← Chain de fallback
│  Chain               │  ← EXPERT → LARGE → SMALL → MICRO
└───────────┬───────────┘
            ↓
        Agente
```

### 2.2 Nível 1: Fast Route (Determinístico)

**Implementação em `backend/orchestrator/router.py`:**

```python
def fast_route(query: str) -> Optional[str]:
    """Level 1 — deterministic pre-routing.
    
    Returns an agent/model id when the query is trivially classifiable,
    otherwise None to delegate to the ROUTER model.
    """
    query_lower = query.lower()
    
    # Debugging keywords
    if any(kw in query_lower for kw in ["debug", "error", "bug", "not working"]):
        return "DEBUGGER"
    
    # Architecture keywords
    if any(kw in query_lower for kw in ["architecture", "design", "system"]):
        return "ARCHITECT"
    
    # Code generation keywords
    if any(kw in query_lower for kw in ["implement", "write code", "create function"]):
        return "CODER"
    
    # Research keywords
    if any(kw in query_lower for kw in ["search", "documentation", "how to"]):
        return "RESEARCHER"
    
    # Documentation keywords
    if any(kw in query_lower for kw in ["document", "write docs", "readme"]):
        return "DOCUMENTER"
    
    # Optimization keywords
    if any(kw in query_lower for kw in ["optimize", "slow", "performance"]):
        return "OPTIMIZER"
    
    # Review keywords
    if any(kw in query_lower for kw in ["review", "analyze", "assess"]):
        return "ANALYZER"
    
    # If no match, delegate to ROUTER model
    return None
```

**Por que Fast Route?**
- **Zero custo:** Não invoca modelo, apenas string matching
- **Determinístico:** Mesma query → mesmo agente sempre
- **Rápido:** <1ms para classificar
- **Reduz carga:** Menos chamadas ao ROUTER model

**Por que não apenas Fast Route?**
- Fast route não cobre todos os casos
- Algumas queries são ambíguas
- Fast route não pode considerar contexto
- ROUTER model é mais inteligente para casos complexos

**Por que keywords e não ML?**
- Keywords são determinísticos (zero false positives)
- ML pode ter false positives/negativos
- Keywords são mais rápidos
- Keywords são auditáveis e fáceis de manter

**Limitações do Fast Route:**
- Não considera contexto da sessão
- Não pode lidar com queries ambíguas
- Não pode aprender com feedback
- Requer manutenção manual de keywords

### 2.3 Nível 2: Route with Model (ROUTER Agent)

**Implementação em `backend/orchestrator/router.py`:**

```python
async def route_with_model(query: str) -> RoutingDecision:
    """Level 2 — invoke the ROUTER (qwen2.5:0.5b) and parse its JSON output."""
    # Load ROUTER prompt
    prompt = load_prompt("router")
    
    # Call Ollama with query
    try:
        response = await ollama_client.chat(
            model="qwen2.5:0.5b",
            messages=[{"role": "system", "content": prompt}],
            prompt=query,
            format="json",  # Force JSON output
            temperature=0.1,  # Low temperature for determinism
            timeout=10,  # 10 second timeout
        )
        
        # Parse JSON
        decision = RoutingDecision.parse_obj(response)
        
        # Validate decision
        if decision.primary_agent not in VALID_AGENTS:
            raise ValueError(f"Invalid agent: {decision.primary_agent}")
        
        return decision
        
    except (TimeoutError, JSONDecodeError, ValidationError) as e:
        # If ROUTER fails, fallback to default
        log_error(f"ROUTER agent failed: {e}")
        return RoutingDecision(
            primary_agent="CODER",  # Default to CODER
            secondary_agents=[],
            requires_web_search=False,
            thinking_mode=False,
            estimated_complexity=5,
            task_type="unknown",
            context_needed="medium",
            routing_confidence=0.5,
            routing_reason="ROUTER agent failed, using default",
        )
```

**RoutingDecision Dataclass:**

```python
@dataclass(frozen=True)
class RoutingDecision:
    primary_agent: str  # "CODER", "ARCHITECT", etc.
    secondary_agents: list[str]  # ["ANALYZER"] for code review
    requires_web_search: bool  # True if RESEARCHER needed
    thinking_mode: Literal["fast", "deep", "iterative"]  # Thinking mode
    estimated_complexity: int  # 1-10 scale
    task_type: str  # "code_generation", "debugging", etc.
    context_needed: Literal["low", "medium", "high"]  # Context required
    routing_confidence: float  # 0.0-1.0
    routing_reason: str  # Explanation of decision
```

**Por que RoutingDecision Estruturado?**
- **Parsing determinístico:** Pydantic validation
- **Logging fácil:** Todos os campos são explícitos
- **Debugging:** Pode ver exatamente por que routing escolheu certo agente
- **Extensível:** Fácil adicionar novos campos
- **Type-safe:** TypeScript/Python types

**Por que JSON e não texto livre?**
- JSON é estruturado (parsing fácil)
- JSON é validável (Pydantic)
- JSON é serializável (pode ser guardado em logs)
- Texto livre seria ambíguo (difícil de parse)

**Timeout de 10s:**
- ROUTER model é pequeno (0.5b), deve ser rápido
- 10s é generoso (normalmente <1s)
- Se timeout, fallback para default (CODER)
- Previne hanging requests

### 2.4 Nível 3: Fallback Chain

**Configuração em `config/models.yaml`:**

```yaml
fallback:
  EXPERT:  [LARGE, SMALL, MICRO]
  LARGE:   [SMALL, MEDIUM, MICRO]
  CODER:   [MEDIUM, SMALL, NANO]
  RESEARCHER: [SMALL, MICRO, NANO]
```

**Implementação em `backend/orchestrator/fallback.py`:**

```python
async def invoke_with_fallback(
    agent_name: str,
    request: AgentRequest,
) -> AsyncIterator[str]:
    """Execute agent with fallback chain on failure."""
    fallback_chain = get_fallback_chain(agent_name)
    
    for fallback_agent in fallback_chain:
        try:
            # Acquire agent from pool
            await agent_pool.acquire(fallback_agent, request.session_id)
            
            # Execute agent
            async for chunk in execute_agent(fallback_agent, request):
                yield chunk
            
            # If successful, release and return
            await agent_pool.release(request.session_id)
            return
            
        except (TimeoutError, OOMError, ModelError) as e:
            # Log fallback
            log_fallback(agent_name, fallback_agent, e)
            
            # Release agent
            await agent_pool.release(request.session_id)
            
            # Continue to next fallback
            continue
    
    # If all fallbacks fail, raise error
    raise ExecutionFailed("All fallbacks exhausted")
```

**Por que Fallback Chain?**
- **Resiliência:** Se primary agent falha, sistema ainda funciona
- **Quality degradation gradual:** EXPERT → LARGE → SMALL (qualidade diminui, mas sistema continua)
- **User experience:** Melhor dar resposta de menor qualidade do que falhar completamente
- **Debugging:** Log de fallbacks ajuda a identificar problemas

**Por que estas Chains Específicas?**

**EXPERT → LARGE → SMALL → MICRO:**
- EXPERT é o melhor (32b coder)
- LARGE é bom para arquitetura (14b)
- SMALL é bom para tarefas gerais (7b)
- MICRO é último recurso (3b)
- NÃO inclui NANO (muito pequeno para código complexo)

**LARGE → SMALL → MEDIUM → MICRO:**
- LARGE é primary (14b)
- SMALL é backup (7b)
- MEDIUM é coder-specific (7b coder)
- MICRO é último recurso

**CODER → MEDIUM → SMALL → NANO:**
- CODER é primary (32b coder)
- MEDIUM é coder backup (7b coder)
- SMALL é generalista (7b)
- NANO é último recurso (0.5b)

**Por que não incluir todos os modelos em todas as chains?**
- Overhead (mais tentativas = mais tempo)
- Nem todos os modelos são apropriados (NANO não pode gerar código complexo)
- Chains são otimizadas para o domínio do agente

**Timeout por Nível:**

```yaml
routing:
  fallback_timeout_seconds: 45
  queue_timeout_seconds: 30
```

- **Fallback timeout:** 45s total para tentar todos os fallbacks
- **Queue timeout:** 30s para adquirir semáforo
- **Por que 45s?** EXPERT pode levar até 30s, 15s para fallbacks
- **Por que 30s para queue?** Se fila está cheia, não esperar para sempre

## 3. Agent Pool Detalhado

### 3.1 Semáforos por Modelo

**Configuração em `config/models.yaml`:**

```yaml
concurrency:
  NANO: 5
  MICRO: 3
  SMALL: 2
  MEDIUM: 2
  LARGE: 1
  EXPERT: 1
  VISION: 1
  DASHBOARD: 1
```

**Implementação em `backend/orchestrator/agent_pool.py`:**

```python
class AgentPool:
    """Manages concurrent agent execution with semaphores."""
    
    def __init__(self):
        # Semaphores per model (from config)
        self.semaphores = {
            "nano": asyncio.Semaphore(5),
            "micro": asyncio.Semaphore(3),
            "small": asyncio.Semaphore(2),
            "medium": asyncio.Semaphore(2),
            "large": asyncio.Semaphore(1),
            "expert": asyncio.Semaphore(1),
            "vision": asyncio.Semaphore(1),
            "dashboard": asyncio.Semaphore(1),
        }
        
        # Active agents (session_id → agent_name)
        self.active_agents: dict[str, str] = {}
        
        # Waiting queue (for overflow)
        self.waiting_queue: asyncio.Queue = asyncio.Queue()
        
        # Metrics
        self.metrics = {
            "acquire_count": defaultdict(int),
            "release_count": defaultdict(int),
            "queue_depth": defaultdict(int),
        }
    
    async def acquire(self, agent_name: str, session_id: str) -> None:
        """Acquire agent from pool, block if semaphore full."""
        model = get_model_for_agent(agent_name)
        sem = self.semaphores[model]
        
        # Try to acquire semaphore (with timeout)
        try:
            await asyncio.wait_for(sem.acquire(), timeout=30)
        except asyncio.TimeoutError:
            # If timeout, add to queue
            await self.waiting_queue.put((agent_name, session_id))
            self.metrics["queue_depth"][model] += 1
            raise QueueFull(f"{model} agent queue is full")
        
        # Mark as active
        self.active_agents[session_id] = agent_name
        self.metrics["acquire_count"][model] += 1
    
    async def release(self, session_id: str) -> None:
        """Release agent back to pool."""
        if session_id not in self.active_agents:
            return  # Already released or never acquired
        
        agent_name = self.active_agents.pop(session_id)
        model = get_model_for_agent(agent_name)
        
        # Release semaphore
        self.semaphores[model].release()
        self.metrics["release_count"][model] += 1
        
        # Check if anyone is waiting in queue
        if not self.waiting_queue.empty():
            # Dequeue next request
            next_agent, next_session = await self.waiting_queue.get()
            self.metrics["queue_depth"][model] -= 1
            
            # Acquire for dequeued request
            await self.acquire(next_agent, next_session)
```

**Por que Semáforos?**
- **Previne OOM:** Garante que não executamos mais instâncias do que VRAM permite
- **Fair scheduling:** FIFO implícito (quem chega primeiro é atendido)
- **Simples:** Fácil de implementar e entender
- **Configurável:** Limits podem ser ajustados em models.yaml

**Por que não Queue (FIFO)?**
- Queue adiciona latência (pode crescer infinitamente)
- Semáforos são mais simples (menos código)
- Queue seria necessário apenas se tivéssemos overflow massivo
- Semáforos com timeout é suficiente para a maioria dos casos

**Por que estes Limits Específicos?**

**Cálculo de VRAM (assumindo GPU 12GB):**
- NANO (0.4GB × 5) = 2GB
- MICRO (2GB × 3) = 6GB
- SMALL (4.7GB × 2) = 9.4GB
- MEDIUM (4.7GB × 2) = 9.4GB
- LARGE (9GB × 1) = 9GB
- EXPERT (20GB × 1) = 20GB (requer GPU dedicada)

**Estratégia:**
- NANO, MICRO podem rodar simultaneamente com outros
- SMALL, MEDIUM alternam (não podem rodar ao mesmo tempo)
- LARGE, EXPERT requerem GPU dedicada ou CPU

**Por que EXPERT = 1?**
- EXPERT usa 20GB VRAM (mais que GPUs comuns)
- Se tentar rodar 2 instâncias, OOM quase garantido
- 1 instância é seguro
- Se mais throughput necessário, usar fallback para LARGE

**Por que NANO = 5?**
- NANO é extremamente pequeno (400MB)
- 5 instâncias = 2GB total
- Pode rodar simultaneamente com outros modelos
- Routing é frequente, alta concorrência benéfica

### 3.2 Overflow Queue

**Implementação:**

```python
async def acquire_with_queue(self, agent_name: str, session_id: str) -> None:
    """Acquire agent with queue for overflow."""
    model = get_model_for_agent(agent_name)
    sem = self.semaphores[model]
    
    # Try to acquire immediately
    if sem.locked():
        # If semaphore is locked, add to queue
        await self.waiting_queue.put((agent_name, session_id))
        self.metrics["queue_depth"][model] += 1
        
        # Wait for notification (when semaphore is released)
        await self.wait_for_release(model)
    else:
        # Acquire immediately
        await sem.acquire()
        self.active_agents[session_id] = agent_name
```

**Por que Queue?**
- **Fairness:** Requests não são rejeitados, apenas enfileirados
- **Throughput:** Melhor que rejeitar requests
- **UX:** Utilizador recebe resposta eventualmente (melhor que erro)

**Por que Queue não é padrão?**
- Queue adiciona complexidade
- Queue pode crescer infinitamente (memory leak)
- Para MVP, semáforos com timeout são suficientes
- Queue será implementado em fases posteriores se necessário

## 4. ReAct Coordinator

### 4.1 Ciclo ReAct

```
┌─────────────────────────────────────────────────────────────┐
│                      ReAct Loop                              │
│                                                              │
│  1. REASON                                                    │
│     ├── Agente analisa query                                  │
│     ├── Determina próxima ação                               │
│     └── Emite ação em formato JSON                            │
│                                                              │
│  2. ACT                                                       │
│     ├── Tool executor invoca ação                            │
│     ├── Executa (web search, read file, etc.)                │
│     └── Retorna resultado                                    │
│                                                              │
│  3. OBSERVE                                                   │
│     ├── Agente recebe resultado                              │
│     ├── Atualiza scratchpad                                  │
│     └── Determina se precisa de mais iterações              │
│                                                              │
│  4. REPEAT até:                                              │
│     ├── Task completada                                       │
│     ├── Max iterações (7)                                    │
│     └── Erro irrecoverável                                   │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Implementação do Loop

```python
async def react_loop(
    agent: AgentBase,
    request: AgentRequest,
    max_iterations: int = 7,
) -> AsyncIterator[str]:
    """Execute ReAct loop with max iterations."""
    # Initialize scratchpad
    scratchpad = AgentScratchpad(
        session_id=request.session_id,
        agent_id=agent.name,
        max_iterations=max_iterations,
    )
    
    for iteration in range(max_iterations):
        scratchpad.iteration = iteration
        
        # REASON: Agent determines next action
        action_decision = await agent.reason(request, scratchpad)
        
        # Emit reasoning to user
        yield f"[Thinking] {action_decision.reasoning}"
        
        # Check if done
        if action_decision.done:
            yield action_decision.response
            break
        
        # ACT: Execute action
        try:
            result = await execute_tool(
                action_decision.tool,
                action_decision.params,
            )
        except ToolError as e:
            scratchpad.failed_approaches.append(str(e))
            yield f"[Error] Tool failed: {e}"
            continue
        
        # OBSERVE: Update scratchpad
        scratchpad.observations.append(result)
        scratchpad.tokens_used += result.tokens_used
        
        # Emit observation to user
        yield f"[Observation] {result.summary}"
    
    # Save scratchpad to Redis
    await context_manager.save(scratchpad)
```

**Por que Max 7 Iterações?**
- **Previnir loops infinitos:** Agente pode entrar em ciclo
- **Balance:** 7 é suficiente para tarefas complexas, mas não excessivo
- **UX:** 7 iterações = ~2-3 minutos (aceitável)
- **Custo:** Mais iterações = mais tokens = mais tempo

**Por que não 5 ou 10?**
- 5 pode ser insuficiente para tarefas muito complexas
- 10 pode ser excessivo (latência alta)
- 7 é o sweet spot (baseado em research ReAct)

**Timeout por Iteração:**
```yaml
routing:
  max_react_iterations: 7
  iteration_timeout_seconds: 30
```

- **30s por iteração:** Suficiente para web search, code execution
- **Total timeout:** 7 × 30s = 210s (3.5 minutos)
- **Se timeout:** Fallback para modelo menor ou abortar

### 4.3 Scratchpad Management

**AgentScratchpad Dataclass:**

```python
@dataclass
class AgentScratchpad:
    session_id: str
    agent_id: str
    
    # Short-term memory (this session)
    observations: list[str] = field(default_factory=list)
    failed_approaches: list[str] = field(default_factory=list)
    confirmed_facts: list[str] = field(default_factory=list)
    pending_questions: list[str] = field(default_factory=list)
    
    # Current loop state
    iteration: int = 0
    max_iterations: int = 7
    current_plan: str = ""
    
    # Dashboard metrics
    tokens_used: int = 0
    web_searches: int = 0
    agent_consultations: int = 0
    start_time: datetime = field(default_factory=datetime.utcnow)
```

**Por que Scratchpad?**
- **Persistência:** Contexto preservado entre iterações
- **Learning:** Agente evita repetir erros (failed_approaches)
- **Debugging:** Pode ver raciocínio do agente
- **Métricas:** Tokens, web searches, etc. para dashboard
- **Transparência:** Utilizador pode ver o que agente está a pensar

**Por que não apenas Context Window?**
- Context window é caro (tokens = dinheiro/VRAM)
- Scratchpad é estruturado (não apenas texto)
- Scratchpad permite filtering (ex: apenas confirmed_facts)
- Scratchpad é mais eficiente (não precisa de re-enviar tudo)

**Persistência em Redis:**

```python
class ContextStore:
    """Redis-backed store for session scratchpads."""
    
    async def save(self, scratchpad: AgentScratchpad) -> None:
        """Save scratchpad to Redis with TTL."""
        key = f"scratchpad:{scratchpad.session_id}:{scratchpad.agent_id}"
        value = scratchpad.model_dump_json()
        await redis.set(key, value, ex=3600)  # 1 hour TTL
    
    async def load(self, session_id: str, agent_id: str) -> AgentScratchpad:
        """Load scratchpad from Redis."""
        key = f"scratchpad:{session_id}:{agent_id}"
        value = await redis.get(key)
        if value is None:
            # Create new scratchpad
            return AgentScratchpad(session_id=session_id, agent_id=agent_id)
        return AgentScratchpad.model_validate_json(value)
```

**Por que Redis?**
- **In-memory:** Extremamente rápido
- **TTL:** Expiração automática (não precisa de cleanup manual)
- **Pub/Sub:** Pode emitir eventos quando scratchpad é atualizado
- **Persistência:** Opcional (RDB/AOF)

**TTL de 1 hora:**
- Sessões típicas duram < 1 hora
- Previne memory leak (scratchpads antigos são limpos)
- Se sessão for mais longa, scratchpad é recriado

## 5. Context Manager

### 5.1 Responsabilidades

O Context Manager é responsável por:
- Gerir contexto de sessão (histórico de chat)
- Gerir scratchpad por agente
- Gerir TTL de contexto
- Fornecer contexto para agentes

### 5.2 Implementação

```python
class ContextManager:
    """Manages session context and agent scratchpads."""
    
    def __init__(self):
        self.redis = Redis()
        self.context_ttl = 3600  # 1 hour
        self.scratchpad_ttl = 3600  # 1 hour
    
    async def get_session_context(self, session_id: str) -> SessionContext:
        """Get session context from Redis."""
        key = f"session:{session_id}"
        value = await self.redis.get(key)
        if value is None:
            # Create new session
            return SessionContext(session_id=session_id)
        return SessionContext.model_validate_json(value)
    
    async def update_session_context(self, context: SessionContext) -> None:
        """Update session context in Redis."""
        key = f"session:{context.session_id}"
        value = context.model_dump_json()
        await self.redis.set(key, value, ex=self.context_ttl)
    
    async def add_message(
        self,
        session_id: str,
        role: Literal["user", "assistant", "system"],
        content: str,
        agent: str | None = None,
    ) -> None:
        """Add message to session history."""
        context = await self.get_session_context(session_id)
        context.messages.append(
            Message(role=role, content=content, agent=agent)
        )
        await self.update_session_context(context)
```

**SessionContext Dataclass:**

```python
@dataclass
class SessionContext:
    session_id: str
    messages: list[Message] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class Message:
    role: Literal["user", "assistant", "system"]
    content: str
    agent: str | None = None  # Which agent generated this
    timestamp: datetime = field(default_factory=datetime.utcnow)
    tokens: int = 0
    latency_seconds: float = 0.0
```

**Por que Context Manager Separado?**
- **Separação de responsabilidades:** Context é lógica diferente de routing
- **Testabilidade:** Fácil de mock context manager
- **Extensibilidade:** Pode adicionar features (context compression, etc.)
- **Performance:** Redis é otimizado para este tipo de dado

## 6. Event Bus

### 6.1 Responsabilidades

O Event Bus é responsável por:
- Emitir eventos para observabilidade
- Publicar eventos via Redis Pub/Sub
- Agregar eventos para dashboard

### 6.2 Implementação

```python
class EventBus:
    """Event bus for observability and dashboard."""
    
    def __init__(self):
        self.redis = Redis()
        self.channel = "nexus_events"
    
    async def publish(self, event: Event) -> None:
        """Publish event to Redis Pub/Sub."""
        await self.redis.publish(
            self.channel,
            event.model_dump_json()
        )
    
    async def subscribe(self, pattern: str = "#") -> AsyncIterator[Event]:
        """Subscribe to events matching pattern."""
        pubsub = self.redis.pubsub()
        await pubsub.psubscribe(pattern)
        
        async for message in pubsub.listen():
            if message["type"] == "pmessage":
                event = Event.model_validate_json(message["data"])
                yield event
```

**Event Dataclass:**

```python
@dataclass
class Event:
    type: Literal[
        "agent_start",
        "agent_end",
        "tool_invoke",
        "tool_error",
        "routing_decision",
        "fallback",
        "anomaly",
    ]
    session_id: str
    agent: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
```

**Por que Redis Pub/Sub?**
- **Real-time:** Eventos são entregues instantaneamente
- **Multi-consumer:** Dashboard, logging, metrics podem subscrever
- **Lightweight:** Não precisa de message broker pesado (Kafka, RabbitMQ)
- **Built-in:** Redis já é usado para cache/queue

**Por que não Kafka?**
- Kafka é overkill para este caso de uso
- Kafka é mais complexo de configurar
- Kafka é mais pesado (requer Zookeeper)
- Redis Pub/Sub é suficiente

**Eventos Emitidos:**

| Evento | Quando | Dados |
|--------|--------|-------|
| agent_start | Agente começa a executar | agent, model, query |
| agent_end | Agente termina | agent, model, tokens, latency |
| tool_invoke | Tool é invocada | tool, params, agent |
| tool_error | Tool falha | tool, error, agent |
| routing_decision | Routing é feito | primary_agent, confidence |
| fallback | Fallback é ativado | from_agent, to_agent, reason |
| anomaly | Anomalia detetada | metric, threshold, value |

## 7. API Endpoints

### 7.1 POST /api/chat (SSE Stream)

**Request:**
```json
{
  "session_id": "abc-123",
  "query": "Implement a REST API for user management",
  "context": {
    "language": "python",
    "framework": "fastapi"
  }
}
```

**Response (SSE Stream):**
```
data: {"type": "routing", "agent": "CODER", "confidence": 0.95}

data: {"type": "thinking", "content": "Analyzing requirements..."}

data: {"type": "action", "tool": "READ_FILE", "params": {"path": "models.py"}}

data: {"type": "observation", "content": "Read models.py successfully"}

data: {"type": "chunk", "content": "```python\nclass User(BaseModel):\n"}

data: {"type": "chunk", "content": "    id: int\n    name: str\n```"}

data: {"type": "done", "agent": "CODER", "tokens": 1500, "latency": 5.2}
```

**Por que SSE?**
- **Streaming:** Utilizador vê progresso em tempo real
- **Unidirectional:** Server → client (suficiente para chat)
- **HTTP padrão:** Menos firewall issues que WebSocket
- **Reconnection automática:** EventSource nativo

### 7.2 GET /api/sessions/{id}/history

**Response:**
```json
{
  "session_id": "abc-123",
  "messages": [
    {"role": "user", "content": "Implement a REST API", "timestamp": "..."},
    {"role": "assistant", "content": "Here's the implementation...", "agent": "CODER", "timestamp": "..."}
  ]
}
```

### 7.3 GET /api/models/status

**Response:**
```json
{
  "models": {
    "nano": {"loaded": true, "memory_mb": 400, "requests_per_minute": 120},
    "micro": {"loaded": true, "memory_mb": 2000, "requests_per_minute": 45},
    "expert": {"loaded": false, "memory_mb": 0, "requests_per_minute": 0}
  }
}
```

### 7.4 GET /api/dashboard/stream (SSE)

**Response (SSE Stream):**
```
data: {"type": "metric", "name": "latency_p95", "value": 2.3, "unit": "s"}

data: {"type": "anomaly", "metric": "error_rate", "threshold": 0.05, "value": 0.12}

data: {"type": "alert", "severity": "warning", "message": "Queue depth for EXPERT is critical"}
```

## 8. Conclusão

O Orchestrator é o coração de NEXUS IDE, responsável por:
- **Routing inteligente:** 3 níveis (fast → model → fallback)
- **Gestão de recursos:** Semáforos, queues, limits
- **Coordenação ReAct:** Loop com scratchpad
- **Gestão de contexto:** Sessões, histórico, TTL
- **Observabilidade:** Event bus, métricas, tracing

A arquitetura é desenhada para ser:
- **Resiliente:** Fallback chains, timeouts
- **Escalável:** Concurrency limits, horizontal scaling
- **Observável:** Eventos, métricas, tracing
- **Performante:** Async/await, caching, streaming
