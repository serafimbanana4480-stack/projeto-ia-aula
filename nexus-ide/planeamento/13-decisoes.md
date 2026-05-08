# NEXUS IDE — Decisões Arquiteturais Detalhadas

## 1. Introdução às Decisões Arquiteturais

Este documento documenta as decisões arquiteturais tomadas durante o desenvolvimento de NEXUS IDE, incluindo o porquê de cada escolha, alternativas consideradas, trade-offs aceitos, e lições aprendidas. O objetivo é fornecer transparência sobre o raciocínio por trás da arquitetura e servir como referência para futuras decisões.

### 1.1 Categorias de Decisões

- **Backend:** Framework, linguagem, bibliotecas
- **Frontend:** Framework, bibliotecas, componentes
- **LLM:** Modelos, quantização, routing
- **Infraestrutura:** Docker, Kubernetes, observabilidade
- **Segurança:** Sanitização, sandbox, autenticação
- **Performance:** Caching, otimização, escalabilidade

## 2. Decisões de Backend

### 2.1 Python 3.12 vs Outras Versões

**Decisão:** Usar Python 3.12

**Alternativas Consideradas:**
- Python 3.11: Performance similar, menos features
- Python 3.10: Menos performance, mais estável
- Python 3.13: Mais features, mas menos estável

**Por que Python 3.12?**
- **Performance:** 10-20% mais rápido que 3.11
- **Features:** Type hints melhorados, pattern matching (PEP 634)
- **Suporte:** LTS (Long Term Support) por 5 anos
- **Ecossistema:** Bibliotecas suportam 3.12

**Trade-offs:**
- **Contra:** Algumas bibliotecas podem não suportar 3.12 imediatamente
- **Mitigação:** Verificar suporte antes de adicionar dependências

**Lição Aprendida:** Versões LTS são mais seguras para produção, mas versões mais recentes podem ter features úteis.

### 2.2 FastAPI vs Outros Frameworks

**Decisão:** Usar FastAPI

**Alternativas Consideradas:**
- Django: Muito pesado, ORM desnecessário, menos performante
- Flask: Menos features, precisa de mais boilerplate, sem async nativo
- Starlette: Muito minimalista, faltam features
- Tornado: Mais antigo, menos mantido

**Por que FastAPI?**
- **Performance:** Similar a Go/Node.js (Starlette + Uvicorn)
- **Async nativo:** Suporte para async/await
- **OpenAPI/Swagger:** Documentação automática
- **Validação:** Pydantic integrado
- **WebSocket/SSE:** Suporte nativo
- **Ativamente mantido:** Pela equipa original do Starlette

**Trade-offs:**
- **Contra:** Menos maduro que Django/Flask (menos comunidade)
- **Mitigação:** Framework é estável, comunidade está crescendo

**Lição Aprendida:** Frameworks modernos (async-first) são superiores para I/O-bound workloads.

### 2.3 Uvicorn vs Gunicorn

**Decisão:** Usar Uvicorn

**Alternativas Consideradas:**
- Gunicorn: Process-based, não async nativo
- Hypercorn: Mais rápido, mas menos maduro
- Daphne: Django-specific

**Por que Uvicorn?**
- **Async nativo:** Desenhado para ASGI
- **Performance:** Extremamente rápido (uvloop)
- **Simples:** Configuração mínima
- **Compatível:** Funciona com FastAPI

**Trade-offs:**
- **Contra:** Uvicorn não tem process management (necessário Gunicorn + Uvicorn workers em prod)
- **Mitigação:** Usar Gunicorn + Uvicorn workers em production

**Lição Aprendida:** Para development, Uvicorn é suficiente. Para production, Gunicorn + Uvicorn workers é melhor.

### 2.4 Redis vs Memcached

**Decisão:** Usar Redis

**Alternativas Consideradas:**
- Memcached: Mais rápido, mas sem persistência, sem Pub/Sub
- PostgreSQL: Pode ser usado para cache, mas overkill
- Etcd: Distributed key-value, mas overkill

**Por que Redis?**
- **In-memory:** Extremamente rápido
- **Persistência:** RDB/AOF (necessário para context/sessions)
- **Pub/Sub:** Event bus nativo
- **TTL:** Expiração automática
- **Cluster:** Suporte para cluster mode (escalabilidade)

**Trade-offs:**
- **Contra:** Redis usa mais RAM que Memcached
- **Mitigação:** Configurar maxmemory e eviction policy

**Lição Aprendida:** Features adicionais (Pub/Sub, TTL) justificam o overhead de RAM.

### 2.5 ChromaDB vs Pinecone vs Milvus

**Decisão:** Usar ChromaDB

**Alternativas Consideradas:**
- Pinecone: Cloud-only (viola privacidade), custo por query
- Milvus: Muito complexo para uso local, mais pesado
- Qdrant: Excelente, mas ChromaDB é mais simples
- FAISS: Apenas índice, sem API, sem persistência

**Por que ChromaDB?**
- **Python nativo:** Fácil integração
- **Leve:** Não requer servidor separado
- **Open-source:** Licença permissiva
- **API simples:** Fácil de usar
- **Persistência:** SQLite integrado

**Trade-offs:**
- **Contra:** Menos features que Pinecone (não tem cloud managed)
- **Mitigação:** Para MVP, local é suficiente. Cloud pode ser adicionado depois.

**Lição Aprendida:** Para MVP, simplicidade é mais importante que features avançadas.

## 3. Decisões de Frontend

### 3.1 Next.js 15 vs Next.js 14

**Decisão:** Usar Next.js 15 (App Router)

**Alternativas Consideradas:**
- Next.js 14: App Router disponível, mas menos features
- Next.js 13: Pages Router (legado)
- Remix: Full-stack framework, mas menos familiar

**Por que Next.js 15?**
- **App Router:** Nova arquitetura, mais flexível
- **Server Components:** Renderização no servidor (performance)
- **Streaming:** Suporte nativo para streaming (SSE)
- **React 19:** Última versão do React
- **Futuro:** App Router é o futuro do Next.js

**Trade-offs:**
- **Contra:** App Router é mais novo, menos exemplos
- **Mitigação:** Documentação oficial é excelente

**Lição Aprendida:** Adotar novas arquiteturas mais cedo evita refactoring massivo depois.

### 3.2 TypeScript vs JavaScript

**Decisão:** Usar TypeScript

**Alternativas Consideradas:**
- JavaScript: Menos verboso, mais rápido de escrever
- JSDoc: Adicionar tipos via comentários

**Por que TypeScript?**
- **Type safety:** Previne erros de tipo em runtime
- **IntelliSense:** Melhor autocomplete e refactoring
- **Refactoring seguro:** Types ajudam a refatorar
- **Documentação:** Types servem como documentação
- **Standard:** Indústria está adotando TypeScript

**Trade-offs:**
- **Contra:** Mais verboso, mais tempo de setup
- **Mitigação:** strict mode opcional (usar em código crítico)

**Lição Aprendida:** Type safety vale o overhead inicial, especialmente em projetos grandes.

### 3.3 Monaco Editor vs CodeMirror

**Decisão:** Usar Monaco Editor

**Alternativas Consideradas:**
- CodeMirror: Menos pesado, menos familiar
- Ace Editor: Menos mantido
- VS Code Web: Muito pesado, dependência complexa

**Por que Monaco Editor?**
- **Usado por VS Code:** Familiar para a maioria dos programadores
- **Suporte para 100+ linguagens:** Cobertura completa
- **API rica:** Extensível, customizável
- **Ativamente mantido:** Pela Microsoft
- **Performance:** Canvas-based rendering

**Trade-offs:**
- **Contra:** Mais pesado que CodeMirror (bundle size)
- **Mitigação:** Lazy loading, code splitting

**Lição Aprendida:** Familiaridade com ferramentas reduz curva de aprendizagem.

### 3.4 xterm.js vs jQuery Terminal

**Decisão:** Usar xterm.js

**Alternativas Consideradas:**
- jQuery Terminal: Descontinuado
- ttyd: Server-side terminal, não client-side
- WebTTY: Menos mantido

**Por que xterm.js?**
- **Padrão da indústria:** VS Code usa xterm.js
- **Performance:** Canvas-based rendering
- **Plugins:** fit, web-links, etc.
- **Ativamente mantido:** Continua sendo desenvolvido

**Trade-offs:**
- **Contra:** Mais pesado que alternativas
- **Mitigação:** Lazy loading

**Lição Aprendida:** Usar padrões da indústria reduz riscos e aumenta familiaridade.

### 3.5 Zustand vs Redux vs Context API

**Decisão:** Usar Zustand

**Alternativas Consideradas:**
- Redux: Overkill, muito boilerplate
- Context API: Re-render desnecessário, performance
- Recoil: Mais complexo, menos maduro
- Jotai: Atômico, mas menos familiar

**Por que Zustand?**
- **Leve:** 1kb minified
- **Simples:** API minimalista
- **Sem providers:** Boilerplate zero
- **TypeScript-friendly:** Types automáticos
- **DevTools:** Integrados
- **Persistência:** Middleware opcional

**Trade-offs:**
- **Contra:** Menos ecossistema que Redux
- **Mitigação:** Para casos complexos, pode migrar para Redux

**Lição Aprendida:** Para a maioria dos casos, simplicidade é melhor que features avançadas.

## 4. Decisões de LLM

### 4.1 Qwen2.5 vs Llama 3 vs Mistral

**Decisão:** Usar Qwen2.5

**Alternativas Consideradas:**
- Llama 3: Mais popular, mas licença mais restritiva
- Mistral 7B: Excelente performance, mas menos tamanhos disponíveis
- DeepSeek Coder: Excelente performance, mas menos suporte em Ollama

**Por que Qwen2.5?**
- **Performance:** Supera Llama 3 em benchmarks de código (HumanEval, MBPP)
- **Licença:** Apache 2.0 (permissiva, permite uso comercial)
- **Tamanhos:** Múltiplos tamanhos disponíveis (0.5b, 3b, 7b, 14b, 32b)
- **Ecossistema Ollama:** Bem suportado
- **Português:** Excelente performance em português (importante para utilizadores lusófonos)

**Trade-offs:**
- **Contra:** Menos popular que Llama 3 (menos comunidade)
- **Mitigação:** Ollama suporta bem, documentação é boa

**Lição Aprendida:** Licença e performance são mais importantes que popularidade.

### 4.2 Ollama vs vLLM vs LocalLLM

**Decisão:** Usar Ollama

**Alternativas Consideradas:**
- vLLM: Excelente throughput, mas mais complexo de configurar
- LocalLLM: Menos maduro, menos modelos disponíveis
- text-generation-webui: Mais focado em UI, menos em API

**Por que Ollama?**
- **Simples:** Single binary, fácil instalação
- **API REST:** API simples e bem documentada
- **Ecossistema:** Grande ecossistema de modelos
- **Suporte GPU:** Suporta múltiplas GPUs
- **Ativamente desenvolvido:** Ativamente mantido

**Trade-offs:**
- **Contra:** Menos throughput que vLLM
- **Mitigação:** Para MVP, throughput não é crítico. vLLM pode ser adicionado depois.

**Lição Aprendida:** Simplicidade e UX são mais importantes que performance otimizada para MVP.

### 4.3 Quantização 4-bit vs 8-bit vs FP16

**Decisão:** Usar quantização 4-bit

**Alternativas Consideradas:**
- 8-bit: Menos perda de qualidade, mas usa 2x mais VRAM
- FP16: Qualidade máxima, mas usa 4x mais VRAM
- FP32: Qualidade máxima, mas usa 8x mais VRAM

**Por que 4-bit?**
- **VRAM:** Reduz VRAM em ~4x (permite rodar múltiplos modelos)
- **Performance:** Inferência 2-3x mais rápida
- **Qualidade:** Perda de qualidade mínima (<2% em benchmarks)
- **Suporte:** Ollama usa 4-bit por padrão

**Trade-offs:**
- **Contra:** Perda de qualidade em tarefas sensíveis
- **Mitigação:** Usar FP16 para tarefas críticas (se necessário)

**Lição Aprendida:** Quantização é um trade-off aceitável para a maioria dos casos de uso.

### 4.4 ReAct Loop vs Single-Shot

**Decisão:** Usar ReAct Loop

**Alternativas Consideradas:**
- Single-Shot: Mais rápido, menos complexo
- Chain-of-Thought: Menos ações, apenas raciocínio
- Plan-and-Solve: Mais estruturado, mas mais complexo

**Por que ReAct Loop?**
- **Decomposição:** Permite decompor tarefas complexas
- **Recuperação:** Pode tentar outra ação se falhar
- **Transparência:** Pode ver raciocínio do agente
- **Flexibilidade:** Pode adaptar estratégia

**Trade-offs:**
- **Contra:** Mais lento (múltiplas iterações)
- **Mitigação:** Limite de 7 iterações previne loops infinitos

**Lição Aprendida:** Iteração é necessária para tarefas complexas, mesmo que adicione latência.

## 5. Decisões de Infraestrutura

### 5.1 Docker vs Podman

**Decisão:** Usar Docker

**Alternativas Consideradas:**
- Podman: Daemonless, mais seguro, mas menos familiar
- Singularity: Focado em HPC, não para desenvolvimento
- LXC: Menos isolamento que containers

**Por que Docker?**
- **Padrão da indústria:** Amplamente adotado
- **Ecossistema:** Muitas ferramentas suportam Docker
- **Comunidade:** Grande comunidade e documentação
- **Compatibilidade:** Funciona em Linux, Mac, Windows

**Trade-offs:**
- **Contra:** Docker daemon pode ser vulnerável (CVE)
- **Mitigação:** Atualizar regularmente, usar rootless mode

**Lição Aprendida:** Padrões da indústria têm mais recursos e suporte.

### 5.2 Docker Compose vs Kubernetes

**Decisão:** Docker Compose para development, Kubernetes para production

**Alternativas Consideradas:**
- Docker Swarm: Mais simples que K8s, mas menos features
- Nomad: Mais simples, mas menos ecossistema
- Serverless (AWS Lambda): Pay-per-use, mas cold starts

**Por que Docker Compose para Development?**
- **Simples:** YAML simples, fácil de usar
- **Local:** Fácil de rodar localmente
- **Hot reload:** Suporta hot reload para desenvolvimento rápido
- **Multi-container:** Orquestra múltiplos containers facilmente

**Por que Kubernetes para Production?**
- **Escalabilidade:** Horizontal scaling automático
- **Alta disponibilidade:** Self-healing, rolling updates
- **Resource management:** Limits e requests por pod
- **Multi-cluster:** Pode deploy em múltiplas regiões

**Trade-offs:**
- **Contra:** Kubernetes é complexo, learning curve íngreme
- **Mitigação:** Usar Docker Compose para staging, K8s apenas para production

**Lição Aprendida:** Ferramentas diferentes para diferentes ambientes (simples para dev, complexo para prod).

### 5.3 Prometheus vs Datadog vs New Relic

**Decisão:** Usar Prometheus

**Alternativas Consideradas:**
- Datadog: Excelente UI, mas cloud-only (custo, privacidade)
- New Relic: Similar ao Datadog
- InfluxDB: Time-series database, mas menos ecossistema

**Por que Prometheus?**
- **Padrão da indústria:** CNCF project, amplamente adotado
- **Pull-based:** Mais seguro que push (agent não precisa de credenciais)
- **Linguagem de query:** PromQL é expressivo
- **Alerting:** Alertmanager nativo
- **Grafana:** Integração perfeita
- **Open-source:** Sem custo, privacidade total

**Trade-offs:**
- **Contra:** Menos features que Datadog (sem APM integrado)
- **Mitigação:** OpenTelemetry para tracing, Grafana para dashboards

**Lição Aprendida:** Open-source pode ser tão bom quanto soluções comerciais para muitos casos de uso.

## 6. Decisões de Segurança

### 6.1 Patterns vs ML para Prompt Injection

**Decisão:** Usar Patterns (regex)

**Alternativas Consideradas:**
- ML-based: Mais inteligente, mas mais complexo
- Hybrid: Patterns + ML
- Heuristic: Baseado em regras simples

**Por que Patterns?**
- **Determinístico:** Zero false positives
- **Rápido:** Regex é extremamente rápido
- **Auditável:** Pode ver exatamente o que está a ser detetado
- **Manutenível:** Fácil adicionar novos padrões
- **Sem treinamento:** Não precisa de dataset

**Trade-offs:**
- **Contra:** Não pode detetar novos padrões de ataque
- **Mitigação:** Atualizar padrões regularmente, ML opcional para fases posteriores

**Lição Aprendida:** Soluções determinísticas são preferíveis quando possíveis.

### 6.2 Docker Sandbox vs chroot vs VM

**Decisão:** Usar Docker Sandbox

**Alternativas Consideradas:**
- chroot: Menos isolamento (network, process)
- VM: Mais pesado, mais lento
- gVisor: Mais complexo, overhead maior

**Por que Docker Sandbox?**
- **Isolamento completo:** Network, FS, process, capabilities
- **Resource limits:** CPU, memory, PIDs configuráveis
- **Cross-platform:** Linux containers funcionam em Linux, Mac, Windows
- **Ecossistema:** Images pré-construídas para todas as linguagens
- **Performance:** Baixo overhead (quanto native)

**Trade-offs:**
- **Contra:** Docker não é 100% seguro (escape vulnerabilities existem)
- **Mitigação:** Defense in depth (sandbox + sanitização + rate limiting)

**Lição Aprendida:** Sandbox é necessário mas não suficiente, precisa de múltiplas camadas de defesa.

### 6.3 JWT vs OAuth2 vs Session Cookies

**Decisão:** Usar JWT

**Alternativas Consideradas:**
- OAuth2: Mais complexo, requer provider externo
- Session Cookies: Estado no servidor (escalabilidade)
- API Keys: Simples, mas sem expiração automática

**Por que JWT?**
- **Stateless:** Não precisa de armazenar sessões no servidor
- **Standard:** JWT é o padrão da indústria
- **Flexível:** Pode incluir claims customizados
- **Performance:** Validação é rápida (crypto nativo)

**Trade-offs:**
- **Contra:** Não pode revogar tokens sem estado adicional
- **Mitigação:** Curta expiração (24h), refresh tokens

**Lição Aprendida:** Stateless authentication escala melhor que stateful.

## 7. Decisões de Performance

### 7.1 Redis Cache vs Memcached vs In-Memory

**Decisão:** Usar Redis Cache

**Alternativas Consideradas:**
- Memcached: Mais rápido, mas sem persistência
- In-Memory (Python dict): Mais rápido, mas não compartilhado
- Database: PostgreSQL como cache (overkill)

**Por que Redis Cache?**
- **Persistência:** Dados persistem entre restarts
- **TTL:** Expiração automática
- **Pub/Sub:** Pode ser usado para event bus
- **Compartilhado:** Múltiplos processos podem acessar
- **Já usado:** Redis já é usado para cache/queue

**Trade-offs:**
- **Contra:** Mais lento que Memcached
- **Mitigação:** Cache hits são suficientemente rápidos

**Lição Aprendida:** Features adicionais (TTL, Pub/Sub) justificam pequena perda de performance.

### 7.2 SSE vs WebSocket vs Polling

**Decisão:** Usar SSE para chat, WebSocket para terminal

**Alternativas Consideradas:**
- Polling: Ineficiente (muitos requests)
- gRPC: Complexo, não browser nativo
- WebRTC: Overkill para chat

**Por que SSE para Chat?**
- **Unidirectional:** Server → client (suficiente para chat)
- **HTTP padrão:** Menos firewall issues
- **Reconnection automática:** EventSource nativo
- **Streaming:** Suporte nativo

**Por que WebSocket para Terminal?**
- **Bidirecional:** Terminal precisa enviar input E receber output
- **Baixa latência:** WebSocket é mais rápido que polling
- **Real-time:** Necessário para interatividade

**Lição Aprendida:** Escolher a ferramenta certa para o caso de uso (não uma solução para todos).

### 7.3 Async vs Sync

**Decisão:** Usar Async (async/await)

**Alternativas Consideradas:**
- Sync: Mais simples, mas bloqueia threads
- Threads: Mais complexo, GIL limita performance
- Multiprocessing: Mais complexo, overhead de comunicação

**Por que Async?**
- **I/O-bound:** Backend é I/O-bound (LLM, Redis, HTTP)
- **Performance:** Async permite concorrência sem threads
- **Escalabilidade:** Async escala melhor que sync
- **Python 3.12:** Async/await é nativo e maduro

**Trade-offs:**
- **Contra:** Async é mais complexo que sync
- **Mitigação:** Pydantic, pytest-asyncio facilitam async

**Lição Aprendida:** Para I/O-bound workloads, async é superior a sync/threads.

## 8. Decisões de Observabilidade

### 8.1 Prometheus vs Datadog vs CloudWatch

**Decisão:** Usar Prometheus

**Alternativas Consideradas:**
- Datadog: Excelente UI, mas cloud-only
- CloudWatch: AWS-specific (lock-in)
- Stackdriver: Google Cloud (lock-in)

**Por que Prometheus?**
- **Padrão da indústria:** CNCF project
- **Pull-based:** Mais seguro que push
- **PromQL:** Linguagem de query poderosa
- **Grafana:** Dashboards excelentes
- **Open-source:** Sem custo, privacidade

**Trade-offs:**
- **Contra:** Menos features que Datadog (sem APM integrado)
- **Mitigação:** OpenTelemetry para tracing, custom metrics

**Lição Aprendida:** Open-source pode ser tão bom quanto soluções comerciais para muitos casos.

### 8.2 OpenTelemetry vs Jaeger SDK vs Zipkin SDK

**Decisão:** Usar OpenTelemetry

**Alternativas Consideradas:**
- Jaeger SDK: Vendor-specific (Jaeger)
- Zipkin SDK: Vendor-specific (Zipkin)
- Datadog APM: Cloud-only

**Por que OpenTelemetry?**
- **Vendor-neutral:** Pode exportar para Jaeger, Zipkin, Datadog
- **Unified:** Traces, metrics, logs em um framework
- **Multi-linguagem:** Python, JavaScript, Go, etc.
- **Standard:** CNCF project, futuro da observabilidade

**Trade-offs:**
- **Contra:** Mais complexo que SDKs específicos
- **Mitigação:** Documentação é excelente, exemplos são claros

**Lição Aprendida:** Vendor-neutral é melhor para evitar lock-in.

### 8.3 Structlog vs Logging vs Loguru

**Decisão:** Usar structlog

**Alternativas Consideradas:**
- Python logging: Built-in, mas não estruturado
- Loguru: Excelente API, mas menos features
- Logstash: Mais complexo, overhead

**Por que structlog?**
- **Estruturado:** Logs são dicts, não strings
- **Context:** Adiciona contexto automaticamente
- **Performance:** Rápido (compilado em Rust)
- **Flexibilidade:** Múltiplos formatters (JSON, console)
- **Integration:** Integra com standard logging

**Trade-offs:**
- **Contra:** Mais dependência (precisa instalar)
- **Mitigação:** Dependency management (poetry)

**Lição Aprendida:** Logs estruturados são muito mais úteis que logs de texto.

## 9. Decisões de Testes

### 9.1 pytest vs unittest vs nose2

**Decisão:** Usar pytest

**Alternativas Consideradas:**
- unittest: Python padrão, mas menos features
- nose2: Menos mantido
- doctest: Apenas para docstrings

**Por que pytest?**
- **Features ricas:** Fixtures, parametrização, plugins
- **Sintaxe simples:** Menos boilerplate
- **Ecossistema:** Muitos plugins (pytest-cov, pytest-asyncio)
- **Performance:** Mais rápido que unittest

**Trade-offs:**
- **Contra:** Não é built-in (precisa instalar)
- **Mitigação:** Poetry facilita instalação

**Lição Aprendida:** Frameworks de terceiros podem ser superiores ao built-in.

### 9.2 Vitest vs Jest vs Mocha

**Decisão:** Usar vitest

**Alternativas Consideradas:**
- Jest: Padrão, mas mais lento
- Mocha: Mais verboso
- Jasmine: Mais antigo

**Por que vitest?**
- **Rápido:** Native ESM, mais rápido que Jest
- **Features:** Similar ao Jest (snapshot, mocking, coverage)
- **Configuração simples:** Vite config compartilhada
- **Ativamente mantido:** Pela Vite team

**Trade-offs:**
- **Contra:** Menos maduro que Jest
- **Mitigação:** Vite é amplamente usado, vitest é estável

**Lição Aprendida:** Ferramentas modernas (ESM-first) são superiores às antigas.

## 10. Lições Aprendidas

### 10.1 Lições Gerais

1. **Simplicidade primeiro:** Começar simples, adicionar complexidade quando necessário
2. **Padrões da indústria:** Usar padrões da indústria reduz riscos
3. **Open-source:** Open-source pode ser tão bom quanto soluções comerciais
4. **Defense in depth:** Múltiplas camadas de defesa são necessárias
5. **Performance vs features:** Trade-offs são inevitáveis, escolher sabiamente

### 10.2 Lições Específicas

1. **Async/await:** Para I/O-bound workloads, async é superior
2. **TypeScript:** Type safety vale o overhead inicial
3. **Docker:** Docker é o padrão para containers
4. **Redis:** Features adicionais (TTL, Pub/Sub) justificam overhead
5. **Ollama:** Simplicidade e UX são mais importantes que performance otimizada

### 10.3 Arrependimentos

1. **Llama 3:** Consideramos Llama 3 inicialmente, mas Qwen2.5 tem melhor performance e licença
2. **vLLM:** Consideramos vLLM para throughput, mas Ollama é mais simples para MVP
3. **Memcached:** Consideramos Memcached para cache, mas Redis tem mais features
4. **Single-shot:** Consideramos single-shot para velocidade, mas ReAct é necessário para tarefas complexas
5. **Context API:** Consideramos Context API para state, mas Zustand é mais simples

## 11. Decisões Futuras

### 11.1 Decisões Pendentes

**Kubernetes vs Docker Swarm para Production:**
- **Status:** Decidido por Kubernetes
- **Razão:** Escalabilidade e alta disponibilidade são críticas para production

**ML-based Prompt Injection Detection:**
- **Status:** Pendente
- **Razão:** Patterns são suficientes para MVP, ML pode ser adicionado depois

**vLLM para Throughput:**
- **Status:** Pendente
- **Razão:** Ollama é suficiente para MVP, vLLM pode ser adicionado para scale

### 11.2 Decisões a Revisitar

**Monaco Editor vs CodeMirror:**
- **Status:** Decidido por Monaco
- **Quando revisitar:** Se bundle size for problema crítico

**Zustand vs Redux:**
- **Status:** Decidido por Zustand
- **Quando revisitar:** Se state management se tornar muito complexo

**SSE vs WebSocket para Chat:**
- **Status:** Decidido por SSE
- **Quando revisitar:** Se bidirecional communication for necessário

## 12. Conclusão

As decisões arquiteturais de NEXUS IDE são baseadas em:
- **Performance:** Escolher tecnologias rápidas (async, uvloop, vitest)
- **Simplicidade:** Escolher tecnologias simples (Docker Compose, Ollama)
- **Padrões:** Seguir padrões da indústria (TypeScript, Prometheus, Kubernetes)
- **Privacidade:** Priorizar soluções open-source e locais
- **Escalabilidade:** Escolher tecnologias que escalam (Kubernetes, Redis)

Cada decisão foi tomada após considerar alternativas, trade-offs, e lições aprendidas.
