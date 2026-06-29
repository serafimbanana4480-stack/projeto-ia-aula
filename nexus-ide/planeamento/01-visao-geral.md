# NEXUS IDE — Visão Geral e Filosofia

## 1. Introdução ao Projeto

NEXUS IDE é um ambiente de desenvolvimento integrado (IDE) inteligente, totalmente local e open-source, que utiliza múltiplos agentes de IA especializados para auxiliar programadores em todas as fases do ciclo de desenvolvimento de software. O projeto nasce da necessidade de ter uma ferramenta de desenvolvimento assistida por IA que respeite a privacidade, funcione offline, e ofereça capacidades de raciocínio complexo através de uma arquitetura multi-agente especializada.

### 1.1 Objetivos Principais

**Privacidade Total:** Todos os modelos de IA executam localmente via Ollama, sem qualquer comunicação com serviços externos. Isto garante que o código fonte, prompts, e dados sensíveis do utilizador nunca saem da máquina local. Esta é uma escolha deliberada em contraste com soluções como GitHub Copilot, Claude, ou ChatGPT que dependem de APIs cloud.

**Especialização sobre Generalismo:** Em vez de usar um único modelo LLM genérico para todas as tarefas, NEXUS IDE emprega 9 agentes especializados, cada um com um sistema de prompts específico e otimizado para o seu domínio. Esta abordagem permite que cada agente seja extremamente competente na sua área específica, em vez de ser apenas "bom" em tudo.

**Iteração ReAct:** Os agentes seguem um ciclo de Reasoning → Acting → Observing, permitindo que decomponham tarefas complexas em passos menores, executem ações como web search, leitura de ficheiros, execução de código, e observem os resultados antes de tomar a próxima decisão. Isto contrasta com abordagens de "single-shot" onde o modelo tem que acertar tudo de primeira.

**Modelos Right-Sized:** Cada tarefa utiliza o menor modelo viável. Routing e classificação usam modelos de 0.5B-3B, geração de código usa modelos de 7B-32B especializados, análise complexa usa modelos de 14B-27B. Isto minimiza o uso de VRAM e energia, mantendo a qualidade.

**Dashboard como Cidadão de Primeira Classe:** Um agente dedicado (DASHBOARD AGENT) executa continuamente numa instância Ollama separada (porta 11435), monitorizando métricas, detectando anomalias, e respondendo a perguntas em linguagem natural sobre o estado do sistema. Isto é único - a maioria das ferramentas de observabilidade são passivas; NEXUS IDE tem um agente ativo interpretando métricas.

### 1.2 Contexto e Motivação

O desenvolvimento de software moderno é complexo. Programadores precisam de:
- Arquitetura de sistemas
- Geração de código
- Debugging e troubleshooting
- Pesquisa de documentação
- Otimização de performance
- Documentação técnica
- Revisão de código

Ferramentas existentes como GitHub Copilot oferecem autocomplete de código, mas não têm capacidade de raciocínio multi-passo. ChatGPT pode raciocinar, mas não tem acesso ao contexto do projeto, não pode executar código, e envia dados para servidores externos. Cursor AI combina autocomplete com chat, mas ainda depende de APIs cloud.

NEXUS IDE preenche esta lacuna ao oferecer:
- Acesso completo ao códigobase via embeddings semânticos
- Execução de código em sandbox seguro
- Web search para informação atualizada
- ReAct loop para decomposição de tarefas
- Múltiplos agentes especializados
- Tudo local, privado, e offline

### 1.3 Diferenciais Competitivos

**vs GitHub Copilot:**
- Copilot: Single-shot autocomplete, API cloud, sem raciocínio multi-passo
- NEXUS: ReAct loop, múltiplos agentes, local, execução de código, web search

**vs Cursor AI:**
- Cursor: Chat + autocomplete, API cloud (Claude/GPT), contexto limitado
- NEXUS: Local, embeddings semânticos do codebase, execução sandbox, dashboard ativo

**vs Aider:**
- Aider: CLI-based, git-integrated, single agent
- NEXUS: GUI completa (Monaco Editor), múltiplos agentes, dashboard visual

**vs Continue.dev:**
- Continue: VS Code extension, API cloud, single chat interface
- NEXUS: IDE standalone, multi-agent, observabilidade avançada

**vs OpenAI Code Interpreter:**
- Code Interpreter: Execução de código, mas API cloud, sem acesso a codebase local
- NEXUS: Sandbox local, embeddings do codebase, agentes especializados

## 2. Filosofia de Design

### 2.1 Princípios Fundamentais

**1. Especialização sobre Generalismo**

A escolha de ter 9 agentes especializados em vez de 1 agente generalista é baseada em evidências de que modelos especializados superam generalistas em tarefas específicas. Por exemplo:
- Um modelo treinado especificamente para código (qwen2.5-coder) supera modelos generalistas em geração de código
- Um modelo pequeno (0.5B) é suficiente para routing/classificação, economizando recursos
- Um modelo grande (27B) é necessário para arquitetura complexa, mas não para formatação de texto

Esta abordagem também permite que cada agente tenha um system prompt altamente otimizado para o seu domínio, em vez de um prompt genérico que tenta cobrir todos os casos.

**2. Iteração ReAct**

O ciclo Reasoning → Acting → Observing é inspirado no paper "ReAct: Synergizing Reasoning and Acting in Language Models" (Yao et al., 2022). A evidência mostra que permitir que modelos decomponham tarefas, executem ações, e observem resultados melhora significativamente a performance em tarefas complexas.

Em NEXUS IDE, cada agente pode:
- SEARCH_WEB: Pesquisar na web para informação atualizada
- FETCH_URL: Buscar conteúdo de URLs específicas
- READ_FILE: Ler ficheiros do codebase
- WRITE_FILE: Escrever/modificar ficheiros
- EXECUTE_CODE: Executar código em sandbox
- CONSULT_AGENT: Consultar outros agentes
- SEARCH_CODEBASE: Busca semântica no codebase
- READ_DOCS: Ler documentação
- RECALL_CONTEXT: Recuperar contexto de sessões anteriores

Este conjunto de ações permite que os agentes resolvam problemas que requerem múltiplos passos e fontes de informação.

**3. Right-Sized Models**

A escolha de modelos por tamanho é baseada em:
- **VRAM disponível:** GPUs comuns (RTX 3060, 4070) têm 8-12GB VRAM. Precisamos encaitar múltiplos modelos simultaneamente
- **Latência:** Modelos menores inferem mais rápido, melhorando UX
- **Qualidade:** Tarefas simples não precisam de modelos grandes
- **Custo:** Menores modelos usam menos energia

Model Matrix:
- NANO (0.5B): Routing, classificação - tarefas que requerem apenas decisão binária/categorização
- MICRO (3B): Q&A simples, formatação, sumarização - tarefas de NLP básico
- SMALL (7B): Análise de código, tarefas gerais - equilíbrio entre qualidade e recursos
- MEDIUM (7B coder): Geração de código focada - modelo especializado em código
- LARGE (14B): Arquitetura, análise complexa - raciocínio profundo
- EXPERT (32B coder): Engenharia avançada - código complexo, grandes codebases
- VISION (7B): Análise de imagem/UI - multimodal (placeholder)
- EMBED (270MB): Embeddings para busca semântica - modelo dedicado
- DASHBOARD (3B): Monitorização contínua - instância separada

**4. Dashboard como Cidadão de Primeira Classe**

A maioria das ferramentas de observabilidade são passivas: mostram gráficos, mas não interpretam. NEXUS IDE tem um agente dedicado que:
- Monitoriza métricas Prometheus continuamente
- Detecta anomalias (latência alta, erros, queue depth)
- Produz sumários de sessão a cada 5 minutos
- Responde a perguntas em linguagem natural sobre o estado do sistema

Isto é único porque transforma observabilidade de "ver dados" para "entender o que está a acontecer". O agente pode dizer "A latência aumentou porque o modelo EXPERT está a ser usado para uma tarefa simples - considere routing para MEDIUM".

**5. Privacidade Total**

A escolha de Ollama para execução local é deliberada:
- Zero dependência de APIs externas
- Código fonte nunca sai da máquina
- Prompts nunca são enviados para terceiros
- Funciona offline (apenas web search requer internet)

Alternativas consideradas e rejeitadas:
- **OpenAI API:** Excelente qualidade, mas envia dados para OpenAI, requer internet, custo por token
- **Anthropic Claude:** Similar ao OpenAI, privacidade comprometida
- **LocalLLM:** Menos maduro que Ollama, menos modelos disponíveis
- **vLLM:** Excelente performance, mas mais complexo de configurar, menos user-friendly

Ollama foi escolhido por:
- Simplicidade de uso (single binary)
- Grande ecossistema de modelos
- API REST simples
- Suporte para múltiplas GPUs
- Ativo desenvolvimento

### 2.2 Trade-offs Considerados

**Multi-Agent vs Single-Agent**

**Prós Multi-Agent:**
- Especialização: cada agente otimizado para o seu domínio
- Modularidade: fácil adicionar/remover agentes
- Escalabilidade: agentes podem rodar em máquinas diferentes
- Debugging: mais fácil isolar problemas

**Contras Multi-Agent:**
- Complexidade: routing, coordenação, fallback
- Overhead: múltiplos modelos em memória
- Latência: comunicação entre agentes

**Decisão:** Prós superam contras. A especialização e qualidade justificam a complexidade adicional.

**Local vs Cloud**

**Prós Local:**
- Privacidade total
- Funciona offline (exceto web search)
- Sem custo por token
- Controle total sobre modelos

**Contras Local:**
- Requer hardware potente (GPU)
- Modelos podem ser inferiores a SOTA cloud
- Setup mais complexo para utilizadores

**Decisão:** Privacidade é não-negociável. Hardware é cada vez mais acessível (RTX 3060 ~$300). Modelos open-source estão a aproximar-se de SOTA.

**ReAct vs Single-Shot**

**Prós ReAct:**
- Decomposição de tarefas complexas
- Recuperação de erros (pode tentar outra ação)
- Transparência (pode ver o raciocínio)
- Flexibilidade (pode adaptar estratégia)

**Contras ReAct:**
- Mais lento (múltiplas iterações)
- Mais complexo de implementar
- Pode entrar em loops

**Decisão:** A capacidade de resolver tarefas complexas supera a latência adicional. Limite de 7 iterações previne loops infinitos.

**Monaco Editor vs CodeMirror vs VS Code API**

**Prós Monaco Editor:**
- Usado por VS Code (familiar)
- Excelente suporte para linguagens
- Rich API
- Ativamente mantido pela Microsoft

**Contras Monaco Editor:**
- Mais pesado que CodeMirror
- Licença mais restritiva (MIT, mas com patentes)

**Prós CodeMirror:**
- Leve
- Licença permissiva
- Altamente customizável

**Contras CodeMirror:**
- Menos familiar para utilizadores VS Code
- Menos recursos out-of-the-box

**Decisão:** Monaco Editor foi escolhido porque a maioria dos programadores está familiarizada com VS Code, reduzindo a curva de aprendizagem.

## 3. Público-Alvo e Casos de Uso

### 3.1 Público-Alvo Primário

**Desenvolvedores Individuais:**
- Freelancers que valorizam privacidade
- Desenvolvedores que trabalham em projetos sensíveis (gov, finance)
- Entusiastas de open-source
- Desenvolvedores com hardware decente (GPU com 8GB+)

**Pequenas Equipas:**
- Startups que não podem enviar código para cloud
- Equipas com requisitos de compliance (GDPR, HIPAA)
- Equipas que querem controle total sobre o stack

**Organizações:**
- Empresas com políticas de zero-cloud para código
- Organizações governamentais
- Instituições de investigação

### 3.2 Casos de Uso

**1. Arquitetura de Sistemas:**
- Utilizador: "Preciso de arquitetura para um sistema de e-commerce"
- Agente: ARCHITECT (LARGE model)
- Ações: CONSULT_AGENT (RESEARCHER para tecnologias atuais), SEARCH_WEB (best practices), WRITE_FILE (diagramas, especificações)

**2. Geração de Código:**
- Utilizador: "Implementa uma API REST em FastAPI"
- Agente: CODER (EXPERT model)
- Ações: READ_FILE (código existente), SEARCH_CODEBASE (padrões do projeto), WRITE_FILE (nova implementação), EXECUTE_CODE (teste)

**3. Debugging:**
- Utilizador: "O endpoint /api/users está a retornar 500"
- Agente: DEBUGGER (MEDIUM model)
- Ações: READ_FILE (logs), READ_FILE (código do endpoint), EXECUTE_CODE (debug steps), CONSULT_AGENT (ANALYZER para code review)

**4. Pesquisa de Documentação:**
- Utilizador: "Como uso o React useEffect hook?"
- Agente: RESEARCHER (SMALL model)
- Ações: SEARCH_WEB (documentação oficial), FETCH_URL (exemplos), READ_DOCS (documentação local), SUMMARIZE

**5. Otimização de Performance:**
- Utilizador: "Esta função está lenta"
- Agente: OPTIMIZER (SMALL model)
- Ações: READ_FILE (código), EXECUTE_CODE (profiling), SEARCH_WEB (algoritmos alternativos), WRITE_FILE (versão otimizada)

**6. Documentação:**
- Utilizador: "Gera docs para este módulo"
- Agente: DOCUMENTER (SMALL model)
- Ações: READ_FILE (código), SEARCH_CODEBASE (padrões de docs), WRITE_FILE (README, docstrings)

**7. Análise de Código:**
- Utilizador: "Revisa este PR"
- Agente: ANALYZER (LARGE model)
- Ações: READ_FILE (código do PR), SEARCH_CODEBASE (contexto), CONSULT_AGENT (DEBUGGER se encontrar bugs), WRITE_FILE (feedback)

**8. Monitorização:**
- Utilizador: "Por que a latência aumentou?"
- Agente: DASHBOARD (MICRO model, porta 11435)
- Ações: Query Prometheus metrics, interpretar padrões, responder em linguagem natural

## 4. Roadmap de Implementação

### 4.1 Fase 0 - Organização Estrutural (Concluída)

**Objetivo:** Criar infraestrutura de suporte sem alterar lógica funcional.

**Entregáveis:**
- Testes backend (pytest) - 74 testes, 91% coverage
- Testes frontend (vitest) - 6 testes stub
- CI/CD GitHub Actions - 4 jobs
- Lint config (ruff, mypy, ESLint)
- Makefile - automação de tarefas
- Documentação (CONTRIBUTING.md, IMPLEMENTATION_PLAN.md)

**Racional:** Ter infraestrutura sólida desde o início permite desenvolvimento rápido e seguro. Testes garantem qualidade, CI/CD garante consistência, lint garante estilo consistente.

### 4.2 Fase 1 - Foundation (Semana 1-3)

**Objetivo:** Backend FastAPI funcional com single model chat.

**Entregáveis:**
- Settings & Config completo
- FastAPI app com todos os endpoints
- Ollama client integration
- Health checks & métricas básicas
- Frontend chat UI básica

**Racional:** Começar com um MVP funcional permite iteração rápida. Single model simplifica debugging inicial.

### 4.3 Fase 2 - Agents (Semana 4-6)

**Objetivo:** 9 agentes com run() implementado, routing funcional, agent pool, fallback.

**Entregáveis:**
- ROUTER agent implementado
- Orchestrator routing (fast_route + route_with_model)
- Agent pool com semáforos
- Fallback chain
- 8 agentes restantes (ARCHITECT, CODER, etc.)

**Racional:** Agentes são o coração do sistema. Implementar routing primeiro permite testar coordenação antes de implementar todos os agentes.

### 4.4 Fase 3 - ReAct & Search (Semana 7-9)

**Objetivo:** ReAct loop, web search pipeline, code executor, file manager.

**Entregáveis:**
- ReAct loop (max 7 iterações)
- Web search (Brave API)
- Code executor (Docker sandbox)
- File manager
- Embeddings (ChromaDB)

**Racional:** ReAct tools dão poder aos agentes. Web search fornece informação atualizada. Code executor permite testar código.

### 4.5 Fase 4 - Dashboard (Semana 10-12)

**Objetivo:** Dashboard agent, métricas Prometheus, OpenTelemetry tracing, SSE streaming.

**Entregáveis:**
- Dashboard agent (porta 11435)
- Prometheus metrics completas
- OpenTelemetry tracing
- Event bus (Redis Pub/Sub)
- SSE endpoint /api/dashboard/stream

**Racional:** Observabilidade é crítica para sistemas complexos. Dashboard agent torna observabilidade ativa e inteligente.

### 4.6 Fase 5 - IDE Frontend (Semana 13-16)

**Objetivo:** Monaco Editor, chat panel com SSE, terminal, file explorer, dashboard UI.

**Entregáveis:**
- Monaco Editor com AI inline
- Chat panel com streaming SSE
- Terminal (xterm.js)
- File explorer real
- Dashboard UI com charts

**Racional:** Frontend é a interface do utilizador. Implementar depois do backend garante que a UI reflete capacidades reais.

### 4.7 Fase 6 - Polish & Security (Semana 17-18)

**Objetivo:** Sanitizer completo, rate limiting, sandbox hardening, production deploy.

**Entregáveis:**
- Prompt injection sanitizer expandido
- Rate limiting (Redis)
- Docker sandbox hardening
- Production Docker Compose
- Backup/restore procedures

**Racional:** Security é non-negociável. Hardening no final garante que todas as superfícies de ataque são cobertas.

## 5. Métricas de Sucesso

### 5.1 Métricas Técnicas

**Performance:**
- Latência média: < 2s para routing, < 5s para geração de código
- Throughput: > 10 requisições/minuto por GPU
- VRAM usage: < 12GB para todos os modelos simultâneos
- Uptime: > 99.5%

**Qualidade:**
- Coverage de testes: > 70%
- Lint: zero erros
- Type checking: zero erros
- Security scan: zero vulnerabilidades críticas

**Observabilidade:**
- Todas as métricas Prometheus expostas
- Tracing end-to-end para 100% dos requests
- Eventos emitidos para todas as ações significantes

### 5.2 Métricas de Utilizador

**Adoção:**
- 100+ stars no GitHub (primeiro mês)
- 50+ forks (primeiro mês)
- 10+ contribuidores externos

**Satisfação:**
- NPS (Net Promoter Score) > 40
- < 5% taxa de churn após primeira semana
- > 70% de utilizadores ativos semanalmente

**Qualidade de Resposta:**
- > 80% de respostas consideradas úteis (feedback)
- < 10% de respostas com bugs (feedback)
- > 90% de tarefas completadas com sucesso

## 6. Riscos e Mitigações

### 6.1 Riscos Técnicos

**Risco 1: VRAM Insuficiente**
- **Probabilidade:** Alta (muitos utilizadores não têm GPU potente)
- **Impacto:** Crítico (sistema não funciona)
- **Mitigação:**
  - Suporte para CPU-only (mais lento, mas funcional)
  - Modelos quantizados (4-bit, 8-bit)
  - Offloading para RAM (mais lento)
  - Documentação clara de requisitos

**Risco 2: Ollama Instability**
- **Probabilidade:** Média (Ollama é relativamente novo)
- **Impacto:** Alto (sistema depende de Ollama)
- **Mitigação:**
  - Wrapper robusto com retries
  - Fallback para modelos alternativos
  - Monitorização de saúde do Ollama
  - Contribuir para Ollama se necessário

**Risco 3: ReAct Loop Infinito**
- **Probabilidade:** Média (agentes podem entrar em loops)
- **Impacto:** Médio (gasta recursos, mas não crash)
- **Mitigação:**
  - Hard limit de 7 iterações
  - Timeout por iteração (30s)
  - Detecção de repetição
  - Fallback para modelo menor

**Risco 4: Prompt Injection Bem-sucedido**
- **Probabilidade:** Baixa (sanitizer robusto)
- **Impacto:** Crítico (execução de código malicioso)
- **Mitigação:**
  - Sanitizer multi-layer
  - Sandbox Docker (network disabled)
  - Rate limiting
  - Monitorização de tentativas
  - Community auditing

### 6.2 Riscos de Produto

**Risco 1: Adoção Baixa**
- **Probabilidade:** Média (competição forte)
- **Impacto:** Alto (projeto morre)
- **Mitigação:**
  - Diferenciais claros (privacidade, multi-agent)
  - Demo interativo no site
  - Integração com ferramentas populares (VS Code extension)
  - Comunidade ativa (Discord, GitHub Discussions)

**Risco 2: Manutenção Alta**
- **Probabilidade:** Alta (múltiplos modelos, dependências)
- **Impacto:** Alto (burnout de desenvolvedores)
- **Mitigação:**
  - Arquitetura modular
  - Testes abrangentes
  - Documentação completa
  - Automatização (CI/CD)
  - Contribuidores externos

**Risco 3: Modelos Desatualizados**
- **Probabilidade:** Alta (LLMs evoluem rápido)
- **Impacto:** Médio (qualidade diminui)
- **Mitigação:**
  - Configuração externalizada (models.yaml)
  - Pipeline de atualização de modelos
  - A/B testing de novos modelos
  - Comunidade contribuindo com novos prompts

## 7. Conclusão

NEXUS IDE representa uma abordagem única ao desenvolvimento assistido por IA, combinando:
- Privacidade total (execução local)
- Especialização (9 agentes)
- Raciocínio complexo (ReAct loop)
- Observabilidade ativa (dashboard agent)
- IDE completo (Monaco, terminal, file explorer)

A filosofia de design é clara: qualidade sobre quantidade, especialização sobre generalismo, privacidade sobre conveniência. As escolhas tecnológicas (Ollama, FastAPI, Next.js, Monaco) são baseadas em maturidade, ecossistema, e alinhamento com os princípios do projeto.

O roadmap de 18 semanas é ambicioso mas realista, com milestones claros e entregáveis mensuráveis. Os riscos foram identificados e mitigados.

NEXUS IDE tem o potencial de ser a ferramenta de desenvolvimento assistido por IA mais privada, poderosa, e flexível disponível.
