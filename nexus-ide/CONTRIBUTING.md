# Contributing to NEXUS IDE

Welcome to NEXUS IDE! This document guides you through setting up the development environment, running tests, and contributing to the project.

**[🇺🇸 English](#english) | [🇵🇹 Português](#português)**

---

## English

For detailed development setup instructions, see the **[Developer Setup Guide](./docs/developer-setup.md)**.

### Quick Start

```bash
# Clone and setup
git clone <repository-url>
cd nexus-ide
cp .env.example .env

# Run initial setup
make setup

# Start development environment
make dev
```

### Development Documentation

- **[Developer Setup Guide](./docs/developer-setup.md)** - Comprehensive development environment setup
- **[User Guide](./docs/user-guide.md)** - Understanding the application features
- **[Troubleshooting Guide](./docs/troubleshooting.md)** - Common development issues
- **[FAQ](./docs/FAQ.md)** - Frequently asked questions
- **[ARCHITECTURE.md](./ARCHITECTURE.md)** - Technical architecture

### Testing

```bash
# Run all tests
make test

# Run backend tests
make test-backend

# Run frontend tests
make test-frontend
```

### Code Quality

```bash
# Lint all code
make lint

# Format all code
make format
```

### Pull Request Process

1. Create a feature branch: `git checkout -b feature/feature-name`
2. Make your changes and commit with clear messages
3. Run tests and lint locally: `make test && make lint`
4. Push and create a pull request
5. Wait for CI checks to pass
6. Address code review feedback
7. Merge after approval

---

## Português

Bem-vindo ao NEXUS IDE! Este documento guia-te através de como configurar o ambiente de desenvolvimento, correr testes, e contribuir para o projeto.

Para instruções detalhadas de configuração do ambiente de desenvolvimento, consulta o **[Developer Setup Guide](./docs/developer-setup.md)** (em inglês).

## Pré-requisitos

- **Python 3.12+**
- **Node 20+**
- **Docker & Docker Compose** (para Ollama, Redis, Prometheus)
- **Ollama** (local ou via Docker)

## Setup Inicial

### 1. Clonar e Configurar

```bash
git clone <repo-url>
cd nexus-ide
cp .env.example .env
# Edit .env com as tuas chaves (BRAVE_API_KEY, etc.)
```

### 2. Iniciar Infraestrutura

```bash
make setup
# ou manualmente:
bash scripts/setup.sh
```

Isto vai:
- Iniciar duas instâncias Ollama (porta 11434 para main, 11435 para dashboard)
- Pull dos modelos Qwen
- Build da imagem Docker de sandbox
- Iniciar backend, frontend, Redis, Prometheus

### 3. Instalar Dependências

**Backend:**
```bash
cd backend
pip install -e ".[dev]"
```

**Frontend:**
```bash
cd frontend
npm install
```

## Estrutura do Projeto

```
nexus-ide/
├── backend/           # FastAPI orchestrator + 9 agents
│   ├── agents/        # Agent implementations
│   ├── orchestrator/  # Routing, agent pool, fallback
│   ├── tools/         # ReAct tools (web search, code executor, etc.)
│   ├── config/        # Settings, models.yaml loader
│   ├── observability/ # Prometheus metrics, OpenTelemetry
│   └── tests/         # pytest test suite
├── frontend/          # Next.js 15 IDE
│   ├── app/           # App Router pages
│   ├── components/    # React components
│   ├── hooks/         # Custom React hooks
│   ├── lib/           # Utilities
│   └── tests/         # vitest test suite
├── config/            # models.yaml, prompts/, prometheus.yml
├── docker/            # Dockerfiles + docker-compose.yml
└── scripts/           # setup.sh, helpers
```

## Correr Testes

### Backend

```bash
# Todos os testes com coverage
make test-backend
# ou
cd backend && pytest tests/ --cov=backend --cov-report=term-missing

# Apenas um ficheiro
pytest backend/tests/agents/test_base.py

# Com verbose
pytest -v
```

### Frontend

```bash
make test-frontend
# ou
cd frontend && npm test
```

## Lint e Type Check

### Backend

```bash
make lint-backend
# ou
cd backend && ruff check .
cd backend && mypy . --ignore-missing-imports
```

### Frontend

```bash
make lint-frontend
# ou
cd frontend && npm run lint
cd frontend && npm run type-check
```

## Adicionar um Novo Agente

1. **Criar ficheiro do agente:** `backend/agents/<agent_name>.py`
   ```python
   from backend.agents.base import AgentBase, AgentAction

   class NewAgent(AgentBase):
       name = "NEW_AGENT"
       model_key = "small"  # ou outro de models.yaml
       prompt_file = "new_agent"  # config/prompts/new_agent.md
       supported_actions = {AgentAction.READ_FILE, ...}

       async def run(self, request):
           # implementação
           yield "response"
   ```

2. **Criar prompt do agente:** `config/prompts/<agent_name>.md`
   - Seguir o formato dos prompts existentes (architect.md, coder.md)

3. **Atualizar `config/models.yaml`** (se necessário)
   - Adicionar entrada em `concurrency:` se o agente precisa de limites específicos

4. **Adicionar testes:** `backend/tests/agents/test_<agent_name>.py`
   ```python
   def test_metadata():
       agent = NewAgent()
       assert agent.name == "NEW_AGENT"
   ```

5. **Registrar no orchestrator** (quando a implementação estiver pronta)
   - Adicionar ao routing em `orchestrator/router.py`

## Workflow de Pull Request

1. Criar branch a partir de `develop`: `git checkout -b feature/feature-name`
2. Fazer commits com mensagens claras
3. Correr `make test` e `make lint` localmente
4. Push e abrir PR
5. Aguardar CI passar
6. Code review
7. Merge para `develop`

## Naming Conventions

- **Branches:** `feature/`, `bugfix/`, `docs/`, `refactor/`
- **Commits:** Conventional Commits (feat:, fix:, docs:, refactor:, test:)
- **Python:** snake_case, PascalCase para classes
- **TypeScript/React:** camelCase, PascalCase para componentes

## Debugging

### Logs

Backend logs aparecem no stdout do container Docker ou localmente via uvicorn.

Frontend logs aparecem no browser console.

### Observabilidade

- **Prometheus:** http://localhost:9090
- **Dashboard:** http://localhost:3000/dashboard (quando implementado)

## Perguntas Comuns

**Q: Os testes do frontend falham com "Cannot find module"?**  
A: Corre `npm install` no diretório `frontend/` para instalar as dependências de teste.

**Q: O Ollama não responde?**  
A: Verifica se o container está a correr: `docker ps`. Se não, corre `make setup` ou `docker compose -f docker/docker-compose.yml up -d`.

**Q: Preciso de ter todos os modelos Ollama?**  
A: Para desenvolvimento, começa com `qwen3.5:2b` (NANO) e `qwen3.5:4b` (MICRO). O script `setup.sh` pull todos os modelos mas podes parar e pull apenas os necessários.

**Q: Como corro apenas os testes do backend?**  
A: `make test-backend` ou `cd backend && pytest tests/`

**Q: Como faço reset do ambiente?**  
A: `make clean` limpa volumes Docker e artefactos de build.

## Resources / Recursos

- **[Developer Setup Guide](./docs/developer-setup.md)** - Comprehensive development setup
- **[User Guide](./docs/user-guide.md)** - User documentation and features
- **[Troubleshooting Guide](./docs/troubleshooting.md)** - Common issues and solutions
- **[FAQ](./docs/FAQ.md)** - Frequently asked questions
- **Architecture:** `ARCHITECTURE.md`
- **Implementation Plan:** `docs/IMPLEMENTATION_PLAN.md`
- **Cascade Rules:** `.windsurf/rules.md`
- **Cascade Workflows:** `.windsurf/workflows/`

## Licença

[Adicionar licença quando definida]
