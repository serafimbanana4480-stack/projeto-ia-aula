# 🧠 Projeto IA Aula — NEXUS IDE

> **Uma IDE assistida por IA com arquitetura multi-agente** — Desenvolvimento de software acelerado com colaboração de múltiplos agentes de IA.

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Node.js 18+](https://img.shields.io/badge/Node.js-18+-green.svg)](https://nodejs.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)]()
[![Docker](https://img.shields.io/badge/Docker-Compose-blue.svg)](Dockerfile)

---

## 🎯 Visão Geral

O **NEXUS IDE** é uma **IDE do futuro** que combina:

1. **Múltiplos Agentes de IA** (Executivo, Arquiteto, Coder, Reviewer, etc.)
2. **Orquestração Inteligente** (topologia de agentes, comunicação assíncrona)
3. **Frontend Moderno** (Next.js + TypeScript + Tailwind)
4. **Backend Robusto** (FastAPI + Python + WebSocket)
5. **Observabilidade Completa** (métricas, logs, tracing, dashboard)
6. **Colaboração em Tempo Real** (chat multi-agente, partilha de contexto)

---

## ✨ Funcionalidades Principais

| Funcionalidade | Descrição | Estado |
|----------------|-------------|--------|
| **Multi-Agent System** | 15+ agentes especializados (CEO, CTO, Arquiteto, Coder, etc.) | ✅ Ativo |
| **Intelligent Orchestrator** | Decisão autónoma de qual agente usar | ✅ Ativo |
| **Real-Time Chat** | Chat com múltiplos agentes simultâneos | ✅ Ativo |
| **Code Generation** | Geração de código com refatoração automática | ✅ Ativo |
| **Project Analysis** | Análise profunda de código (AST, dependências) | ✅ Ativo |
| **Testing Framework** | Geração de testes unitários e E2E | ✅ Ativo |
| **Observabilidade** | Métricas Prometheus, logs estruturados, tracing | ✅ Ativo |
| **Docker Ready** | Deploy completo com Docker Compose | ✅ Ativo |
| **Next.js Frontend** | UI moderna, responsiva, tema escuro | ✅ Ativo |
| **FastAPI Backend** | API REST + WebSocket em Python | ✅ Ativo |

---

## 🏗️ Arquitetura

```
nexus-ide/
├── frontend/                  # Next.js + TypeScript + Tailwind
│   ├── app/                # App Router (Next.js 13+)
│   ├── components/          # Componentes React
│   ├── hooks/             # Custom hooks
│   ├── lib/               # Utilitários frontend
│   └── stores/            # State management (Zustand)
├── backend/                  # FastAPI + Python
│   ├── agents/            # Agentes especializados
│   │   ├── executive/     # CEO, CTO, Arquiteto
│   │   ├── backend/       # API Agent, Database Agent
│   │   ├── frontend/      # UI/UX Agent, Component Agent
│   │   └── ...          # +10 outros agentes
│   ├── orchestrator/      # Orquestrador principal
│   ├── llm/              # Provedores LLM (OpenAI, Anthropic, etc.)
│   ├── tools/             # Ferramentas (git, shell, browser)
│   ├── observability/     # Métricas, logs, tracing
│   └── api/              # Endpoints FastAPI
├── docker/                  # Configurações Docker
├── docs/                    # Documentação
├── tests/                   # Testes E2E e unitários
└── README.md              # Este ficheiro
```

---

## 🚀 Quick Start

### Opção 1: Docker (Recomendado)

```bash
# 1. Clonar o repositório
git clone https://github.com/serafimbanana4480-stack/projeto-ia-aula.git
cd projeto-ia-aula/nexus-ide

# 2. Configurar ambiente
cp .env.example .env
# Editar .env com as tuas configurações

# 3. Iniciar com Docker Compose
docker-compose up -d

# 4. Aceder à IDE
http://localhost:3000  (Frontend)
http://localhost:8000  (Backend API)
```

### Opção 2: Instalação Local

```bash
# 1. Backend (Python)
cd nexus-ide/backend
python -m venv venv
source venv/bin/activate  # Linux/Mac
# .\venv\Scripts\Activate.ps1  # Windows
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 2. Frontend (Node.js)
cd nexus-ide/frontend
npm install
npm run dev  # http://localhost:3000
```

---

## 📖 Guia de Uso

### 1. Primeiro Contacto

1. Acede a `http://localhost:3000`
2. Fazes login (ou usa modo guest)
3. Crias um novo projeto ou importas um existente
4. Abres o chat multi-agente
5. Pedes ao "CEO Agent" para planear uma funcionalidade
6. O orquestrador distribui tarefas pelos agentes especializados
7. Acompanhas o progresso em tempo real

### 2. Chat Multi-Agente

```
Tu: "Quero criar uma API REST para gestão de utilizadores"

CEO Agent: "Vou planear isto. Arquiteto, podes desenhar a arquitetura?"
Arquiteto Agent: "Desenhei. Coder, podes implementar os endpoints?"
Coder Agent: "Implementei. Reviewer, podes rever o código?"
Reviewer Agent: "Revisei. Testes necessários. Tester, podes gerar testes?"
Tester Agent: "Gerados. PR pronto para review!"
```

### 3. Agentes Disponíveis

| Agente | Função | Exemplo de Uso |
|--------|----------|-------------|
| **CEO** | Decisões estratégicas | "Planear arquitetura de microserviços" |
| **CTO** | Decisões técnicas | "Escolher entre PostgreSQL vs MongoDB" |
| **Arquiteto** | Desenho de sistemas | "Criar diagrama de classes" |
| **Coder** | Implementação | "Escrever código Python" |
| **Reviewer** | Revisão de código | "Analisar qualidade do código" |
| **Tester** | Testes | "Gerar testes unitários" |
| **Debugger** | Debugging | "Encontrar bug no código" |
| **Documenter** | Documentação | "Gerar documentação API" |
| **Refactor** | Refatoração | "Melhorar performance" |
| **Researcher** | Pesquisa | "Pesquisar melhores práticas" |

---

## 🔧 Configuração

### Ficheiro `.env`

| Variável | Descrição | Defeito |
|----------|-------------|----------|
| `OPENAI_API_KEY` | API key OpenAI | - |
| `ANTHROPIC_API_KEY` | API key Anthropic (Claude) | - |
| `GEMINI_API_KEY` | API key Google Gemini | - |
| `DATABASE_URL` | PostgreSQL connection | SQLite |
| `REDIS_URL` | Redis para cache | `redis://localhost:6379` |
| `JWT_SECRET` | Secret para JWT | - |
| `CORS_ORIGINS` | Origens CORS permitidas | `*` |

---

## 📊 Observabilidade

O NEXUS IDE inclui **observabilidade completa**:

### 1. Métricas (Prometheus)

- **Requests por segundo**
- **Latência de LLM**
- **Uso de CPU/Memória**
- **Número de agentes ativos**

Aceder: `http://localhost:8000/metrics`

### 2. Logs Estruturados

- **Formato JSON** (fácil de parser)
- **Níveis**: DEBUG, INFO, WARNING, ERROR
- **Contexto**: request_id, agent_id, user_id

### 3. Tracing (OpenTelemetry)

- **Rastreio de requests** fim-a-fim
- **Latência por componente**
- **Dependency graph**

### 4. Dashboard (Grafana)

- **Pré-configurado** com Docker Compose
- **Templates** para métricas de LLM
- **Alertas** para erros críticos

---

## 🌐 Deploy

### Railway

1. Conectar repositório GitHub ao Railway
2. Adicionar variáveis de ambiente
3. Fazer deploy

### Render

1. Fazer push do código para GitHub
2. Criar novo Web Service no Render
3. Configurar variáveis de ambiente
4. Fazer deploy

### VPS (Linux)

```bash
# 1. SSH para o servidor
ssh user@server-ip

# 2. Clonar repositório
git clone https://github.com/serafimbanana4480-stack/projeto-ia-aula.git

# 3. Configurar `.env`
nano .env

# 4. Iniciar com Docker Compose
docker-compose up -d

# 5. Verificar logs
docker-compose logs -f
```

---

## 🧪 Testes

```bash
# 1. Backend (Python)
cd nexus-ide/backend
python -m pytest tests/ -v

# 2. Frontend (Node.js)
cd nexus-ide/frontend
npm run test

# 3. E2E (Playwright)
npm run test:e2e

# 4. Lint
cd backend && ruff check .
cd frontend && npm run lint
```

---

## 📂 Estrutura do Projeto

```
projeto-ia-aula/
├── nexus-ide/               # Código principal
│   ├── backend/            # FastAPI + Python
│   ├── frontend/          # Next.js + TypeScript
│   ├── docker/            # Configurações Docker
│   ├── docs/              # Documentação
│   ├── tests/             # Testes
│   └── README.md          # Documentação completa
├── README.md              # Este ficheiro
└── .gitignore            # Ficheiros ignorados
```

---

## 🔍 Troubleshooting

### Backend não inicia

- Verificar se Python 3.11+ está instalado
- Confirmar que todas as dependências estão instaladas (`pip install -r requirements.txt`)
- Rever logs em `backend/logs/nexus.log`

### Frontend não carrega

- Verificar se Node.js 18+ está instalado
- Confirmar que `npm install` foi executado
- Rever logs no terminal (Next.js)

### Agentes não respondem

- Verificar se as API keys dos LLMs estão configuradas
- Confirmar que o Redis está a correr (para filas de mensagens)
- Rever métricas em `http://localhost:8000/metrics`

### Docker não funciona

- Verificar se Docker e Docker Compose estão instalados
- Confirmar que as portas 3000, 8000, 5432, 6379 estão livres
- Rever logs: `docker-compose logs -f`

---

## 📝 Licença

MIT — usar com liberdade.

---

## 🤝 Contribuições

Contribuições são bem-vindas! Por favor:

1. Fazer fork do repositório
2. Criar uma branch de funcionalidade
3. Fazer as tuas alterações
4. Submeter um Pull Request

---

## 📞 Suporte

Para problemas e questões:

- Consultar a seção de troubleshooting
- Rever logs em `backend/logs/nexus.log`
- Abrir uma issue no GitHub

---

## 🙏 Agradecimentos

- **FastAPI**: https://fastapi.tiangolo.com/
- **Next.js**: https://nextjs.org/
- **Tailwind CSS**: https://tailwindcss.com/
- **OpenAI**: https://openai.com/
- **Anthropic**: https://www.anthropic.com/

---

## 📈 Estatísticas do Projeto

- **Última atualização:** 2026-06-28
- **Branch:** `main`
- **Total de ficheiros:** ~1000 (backend + frontend)
- **Módulos Python:** 50+
- **Componentes React:** 100+
- **Cobertura de testes:** 80%+

---

**Feito com ❤️ em Portugal** 🇵🇹
