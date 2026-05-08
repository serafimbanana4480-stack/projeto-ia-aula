# NEXUS IDE

Browser-native AI IDE for macOS with specialized submodels, iterative orchestration and total observability.

**Stack:** Qwen3/3.5 via Ollama · FastAPI · Next.js · Monaco Editor · Docker · OpenTelemetry

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full system design.

## Status

This is a scaffold. No functional logic yet — every module contains stubs and TODOs referencing the architecture document.

## Quick start (once implemented)

```bash
cp .env.example .env
# edit BRAVE_API_KEY etc.
./scripts/setup.sh
open http://localhost:3000
```

## Structure

```
nexus-ide/
├── backend/        FastAPI orchestrator + 9 specialized agents
├── frontend/       Next.js 15 IDE (Monaco + chat + dashboard)
├── docker/         Compose files + Dockerfiles
├── config/         models.yaml, prometheus.yml, prompts/
└── scripts/        setup.sh and helpers
```

## Roadmap

Six phases (18 weeks) — see `ARCHITECTURE.md §13`.
