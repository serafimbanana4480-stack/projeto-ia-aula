# NEXUS IDE - Projeto de Desenvolvimento

Este diretório contém o projeto **NEXUS IDE**, uma IDE assistida por IA para desenvolvimento local com orquestração multiagente.

## 📁 Estrutura do Diretório

```
ia aula/
└── nexus-ide/          # Projeto principal NEXUS IDE
    ├── backend/        # API FastAPI, agentes, orquestração
    ├── frontend/       # Interface Next.js + React
    ├── desktop/        # Aplicação Electron
    ├── config/         # Configurações de models e prompts
    ├── docs/           # Documentação
    └── scripts/        # Scripts de setup e automação
```

## 🚀 Início Rápido

O projeto principal está localizado em `nexus-ide/`. Para começar:

```bash
cd nexus-ide

# Copiar arquivo de ambiente
cp .env.example .env

# Executar setup
bash scripts/setup.sh

# Ou executar manualmente
make dev
```

## 📚 Documentação

- **README do Projeto**: `nexus-ide/README.md`
- **Arquitetura**: `nexus-ide/ARCHITECTURE.md`
- **Plano de Melhorias**: `nexus-ide/PLANO_MELHORIAS.md`
- **Contribuição**: `nexus-ide/CONTRIBUTING.md`

## 🛠️ Status do Projeto

**Status**: 🚧 Em Desenvolvimento Ativo

O projeto está em fase inicial de desenvolvimento com uma arquitetura sólida baseada em agentes especializados de IA.

### Principais Componentes

- **Backend**: FastAPI com sistema de agentes especializados
- **Frontend**: Next.js 15 + React 19 com Monaco Editor
- **Desktop**: Electron para experiência nativa
- **IA**: Integração com Ollama para modelos locais
- **Observabilidade**: OpenTelemetry + Prometheus

## 🔧 Comandos Úteis

```bash
cd nexus-ide

# Ver help disponível
make help

# Executar testes
make test

# Linting
make lint

# Setup inicial
make setup

# Limpar artefatos
make clean
```

## 📝 Notas

Este é um projeto educacional e de demonstração de uma IDE assistida por IA com arquitetura de agentes especializados.

---

**Última atualização**: 2026-05-13 
