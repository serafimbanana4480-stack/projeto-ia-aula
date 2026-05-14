# NEXUS IDE

<p align="center">
  <strong>An AI-assisted IDE for local development, multi-agent orchestration, and professional-grade observability.</strong><br>
  Built to unite intelligent chat, code editor, web search, dashboard, and automation in a single fluid experience.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Stack-FastAPI%20%7C%20Next.js%20%7C%20Ollama-0ea5e9?style=for-the-badge" alt="Stack" />
  <img src="https://img.shields.io/badge/Privacy-Local%20First-22c55e?style=for-the-badge" alt="Privacy" />
  <img src="https://img.shields.io/badge/Observability-OpenTelemetry%20%7C%20Prometheus-f59e0b?style=for-the-badge" alt="Observability" />
</p>

> For the complete technical specification, see [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

**[🇺🇸 English Documentation](#english-documentation) | [🇵🇹 Documentação em Português](#documentação-em-português)**

---

## English Documentation

### What is NEXUS IDE?

**NEXUS IDE** is a modern development environment with AI designed to enhance productivity, clarity, and technical control. Instead of relying on a single generic model, the system distributes responsibilities across **specialized agents**, each focused on a specific task.

In practice, this enables:

- **More accurate responses** for each type of request
- **Better separation of concerns** between analysis, code, and documentation
- **More context and less noise** during complex tasks
- **Local execution** with focus on privacy and autonomy

### Quick Start

```bash
# Clone and setup
git clone <repository-url>
cd nexus-ide
cp .env.example .env

# Run initial setup (downloads models, starts services)
./scripts/setup.sh

# Start all services
./start-all.sh
```

Then open [http://localhost:3000](http://localhost:3000) in your browser.

### Documentation

- **[User Guide](./docs/user-guide.md)** - Comprehensive user instructions and features
- **[Developer Setup Guide](./docs/developer-setup.md)** - Development environment setup
- **[Troubleshooting Guide](./docs/troubleshooting.md)** - Common issues and solutions
- **[FAQ](./docs/FAQ.md)** - Frequently asked questions
- **[CONTRIBUTING.md](./CONTRIBUTING.md)** - Contribution guidelines
- **[ARCHITECTURE.md](./ARCHITECTURE.md)** - Technical architecture

### Key Features

| Area | Capability |
|------|------------|
| Chat | Technical assistant with conversational flow support |
| Code | Monaco-based editor with IDE experience |
| Orchestration | Router + specialized agents for different tasks |
| Search | Web search and local context integration |
| Observability | Metrics, logs, and tracing with OpenTelemetry/Prometheus |
| Dashboard | Real-time operational system view |
| Execution | Local environment with Docker and isolated components |

### System Requirements

- **Python 3.12+**
- **Node.js 18+**
- **Ollama** (runs via Docker)
- **Docker & Docker Compose**
- **RAM:** Minimum 16GB (32GB recommended)
- **VRAM:** Minimum 8GB (16GB+ recommended)

### Main Agents

1. **ROUTER** — Classifies intents and chooses the right path
2. **ARCHITECT** — Structures systems, flows, and technical decisions
3. **RESEARCHER** — Searches for current information and validates sources
4. **CODER** — Generates or adjusts code with production focus
5. **ANALYZER** — Evaluates quality, risks, and consistency
6. **DEBUGGER** — Finds root causes of errors and failures
7. **DOCUMENTER** — Creates clear and useful documentation
8. **OPTIMIZER** — Suggests performance improvements
9. **DASHBOARD AGENT** — Monitors the system continuously

### Tech Stack

**Backend:**
- Python 3.12, FastAPI, Uvicorn, Redis

**Frontend:**
- Next.js 15, React, TypeScript, Tailwind CSS, Monaco Editor

**Infrastructure:**
- Ollama, Docker, OpenTelemetry, Prometheus

### Project Structure

```
nexus-ide/
├── backend/         # FastAPI API, agents, orchestration, tools, tests
├── frontend/        # Next.js IDE interface, chat, dashboard, editor
├── desktop/         # Electron shell with native filesystem bridge
├── config/          # Prompts, models, operational configuration
├── docker/          # Dockerfiles and docker-compose
├── docs/            # Documentation (user guide, troubleshooting, FAQ)
├── scripts/         # Setup and automation scripts
└── planeamento/     # Architecture and roadmap documentation
```

---

## Documentação em Português

## O que é o NEXUS IDE?

O **NEXUS IDE** é um ambiente de desenvolvimento moderno com IA pensado para potenciar produtividade, clareza e controlo técnico. Em vez de depender de um único modelo genérico, o sistema distribui responsabilidades por **agentes especializados**, cada um focado numa tarefa específica.

Na prática, isto permite:

- **Respostas mais precisas** para cada tipo de pedido.
- **Melhor separação de responsabilidades** entre análise, código e documentação.
- **Mais contexto e menos ruído** durante tarefas complexas.
- **Execução local** com foco em privacidade e autonomia.

## Proposta de valor

O projeto foi desenhado para resolver dores reais de desenvolvimento:

- **Desenvolver mais depressa** com assistência inteligente dentro da IDE.
- **Reduzir retrabalho** com análise, depuração e revisão automatizadas.
- **Visualizar o estado do sistema** com métricas e tracing integrados.
- **Centralizar o fluxo de trabalho** em chat, editor, terminal e dashboard.

## Principais capacidades

| Área | Capacidade |
|---|---|
| Chat | Assistente técnico com suporte a fluxo conversacional |
| Código | Editor baseado em Monaco com experiência de IDE |
| Orquestração | Router + agentes especializados para diferentes tarefas |
| Pesquisa | Integração com pesquisa web e contexto local |
| Observabilidade | Métricas, logs e tracing com OpenTelemetry/Prometheus |
| Dashboard | Visão operacional do sistema em tempo real |
| Execução | Ambiente local com Docker e componentes isolados |

## Arquitetura em alto nível

O fluxo principal segue esta lógica:

1. O utilizador envia um pedido pela interface.
2. O **ROUTER** classifica a intenção.
3. O orquestrador escolhe o agente mais adequado.
4. O agente executa a tarefa usando ferramentas ou pesquisa, se necessário.
5. Os resultados são apresentados no frontend e registados para observabilidade.

### Agentes principais

1. **ROUTER** — classifica intenções e escolhe o caminho certo.
2. **ARCHITECT** — estrutura sistemas, fluxos e decisões técnicas.
3. **RESEARCHER** — procura informação atual e valida fontes.
4. **CODER** — gera ou ajusta código com foco em produção.
5. **ANALYZER** — avalia qualidade, riscos e consistência.
6. **DEBUGGER** — encontra causas raiz de erros e falhas.
7. **DOCUMENTER** — cria documentação clara e útil.
8. **OPTIMIZER** — sugere melhorias de desempenho.
9. **DASHBOARD AGENT** — monitoriza o sistema continuamente.

## Matriz de modelos

O projeto usa modelos diferentes consoante a exigência de cada tarefa:

- **NANO** — routing e classificação rápida
- **MICRO** — Q&A curto e formatação
- **SMALL** — análise leve e tarefas gerais
- **MEDIUM** — geração de código focada
- **LARGE** — raciocínio complexo e arquitetura
- **EXPERT** — engenharia avançada
- **VISION** — leitura visual de interfaces/imagens
- **EMBED** — embeddings, pesquisa semântica e RAG
- **DASHBOARD** — monitorização contínua dedicada

## Stack tecnológica

### Backend

- Python 3.12
- FastAPI
- Uvicorn
- Redis
- componentes de persistência e pesquisa no backend

### Frontend

- Next.js 15
- React
- TypeScript
- Tailwind CSS
- Monaco Editor
- componentes de interface para chat, dashboard e editor

### Infraestrutura e observabilidade

- Ollama
- Docker e Docker Compose
- OpenTelemetry
- Prometheus

## Pré-requisitos

Antes de começares, garante que tens instalado:

- **Python 3.12**
- **Node.js 18+**
- **Ollama**
- **Docker** e **Docker Compose**
- **Git**

## Configuração do ambiente

Cria o ficheiro de variáveis de ambiente a partir do exemplo:

```bash
cp .env.example .env
```

### Variáveis principais

- `OLLAMA_HOST` — endpoint principal do Ollama
- `OLLAMA_DASHBOARD_HOST` — endpoint dedicado ao dashboard
- `REDIS_URL` — fila e cache
- `BRAVE_API_KEY` — pesquisa web
- `BACKEND_HOST` / `BACKEND_PORT` — backend FastAPI
- `NEXT_PUBLIC_API_URL` — URL pública do backend
- `OTEL_EXPORTER_OTLP_ENDPOINT` — exportação de tracing
- `PROMETHEUS_PORT` — porta do Prometheus

## Instalação e arranque rápido

```bash
cp .env.example .env
./scripts/setup.sh
./start-all.sh
```

Depois abre:

```text
http://localhost:3000
```

## Execução manual

Se preferires subir os componentes separadamente:

### Backend

```bash
python -m uvicorn backend.orchestrator.main:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Desktop app com acesso nativo a qualquer pasta

Para abrir a IDE como aplicação desktop e escolher qualquer pasta do Mac com o seletor nativo:

```bash
cd desktop
npm install
npm start
```

Depois, o Electron abre o frontend existente e ativa o bridge local para:

- Selecionar uma pasta do sistema com um diálogo nativo.
- Ler e gravar ficheiros dentro da pasta escolhida.
- Executar comandos com `cwd` nessa pasta.

### Parar os serviços

```bash
./stop-all.sh
```

## Estrutura do projeto

```text
nexus-ide/
├── backend/         # API FastAPI, agentes, orquestração, ferramentas e testes
├── desktop/         # Shell Electron e bridge nativa para acesso ao sistema de ficheiros
├── frontend/        # Interface web da IDE, chat, dashboard e editor
├── config/          # Prompts, modelos e configuração operacional
├── docker/          # Dockerfiles e docker-compose
├── docs/            # Documentação complementar
├── scripts/         # Scripts de setup e automação
└── planeamento/     # Documentação de arquitetura e roadmap
```

## Documentação útil

- **[User Guide](./docs/user-guide.md)** — Guia completo do utilizador (Inglês)
- **[Developer Setup Guide](./docs/developer-setup.md)** — Configuração do ambiente de desenvolvimento (Inglês)
- **[Troubleshooting Guide](./docs/troubleshooting.md)** — Problemas comuns e soluções (Inglês)
- **[FAQ](./docs/FAQ.md)** — Perguntas frequentes (Inglês)
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — referência oficial da arquitetura
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — guia para contribuir
- [`PLANO_MELHORIAS.md`](./PLANO_MELHORIAS.md) — evolução futura do projeto
- [`.windsurf/`](./.windsurf) — documentação e workflows do ambiente

## Roadmap

O desenvolvimento está organizado em fases:

1. **Fundação** — chat base, serviços essenciais e estrutura inicial.
2. **Agentes** — implementação dos agentes especializados e do router.
3. **ReAct e pesquisa** — iteração, pesquisa web e contexto.
4. **Dashboard** — observabilidade e monitorização avançada.
5. **IDE completa** — terminal, editor e integrações profundas.
6. **Polimento e segurança** — hardening, testes e preparação para produção.

## Estado atual

O repositório encontra-se em evolução ativa. A base estrutural já está montada para crescer de forma modular, com espaço para consolidação progressiva de cada componente conforme o roadmap.

## Como contribuir

Se quiseres ajudar no projeto:

1. Cria uma branch nova.
2. Mantém a consistência com a arquitetura existente.
3. Executa os testes relevantes antes de abrir PR.
4. Atualiza a documentação sempre que mudares comportamento ou API.

## Próximos passos recomendados

- Adicionar **screenshots** da interface.
- Inserir **badges reais de build/testes** quando o CI estiver ativo.
- Publicar uma secção de **demo** ou vídeo curto.
- Definir uma **licença** no repositório.

## Licença

Se ainda não tiveres uma licença formal, adiciona um ficheiro `LICENSE` antes de publicares amplamente o projeto.

---

**NEXUS IDE** foi pensado para elevar a experiência de programação com IA a um nível mais integrado, confiável e profissional.
