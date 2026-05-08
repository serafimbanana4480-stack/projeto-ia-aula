# NEXUS-IDE Project Rules

> Persistent instructions that shape how Cascade responds and writes code for the NEXUS-IDE project.
> These rules are **project-specific**, **restrictive**, and **ranked by priority**.

## Priority System

- **P0 — HARD CONSTRAINT** (never violate)
- **P1 — STRONG DEFAULT** (override only with explicit justification)
- **P2 — STYLE PREFERENCE** (apply unless user explicitly requests otherwise)

---

## Architecture Rules

- **P0** — Always follow the multi-agent architecture: Router → Agent → Tool → Observer. No shortcuts.
- **P0** — Every new agent must have a matching `.md` prompt in `config/prompts/` and an entry in `models.yaml`.
- **P1** — Prefer async/await over callbacks or synchronous blocking in all Python backend code.
- **P1** — Use FastAPI dependency injection for shared resources (Redis, Ollama client, ChromaDB).
- **P2** — Follow modular design: one responsibility per module, max 300 lines per file.

## Code Quality Rules

- **P0** — Every Python function must have type hints. Every public function must have a docstring.
- **P0** — Handle all edge cases explicitly: null inputs, empty collections, boundary values, timeouts.
- **P1** — Functions must be <= 50 lines. If larger, refactor into helpers.
- **P1** — Use Pydantic models for all API inputs/outputs. Never use raw dicts.
- **P2** — Prefer f-strings over `.format()` or `%` formatting.
- **P2** — Use `pathlib.Path` over `os.path`.

## Frontend Rules

- **P0** — Use React Server Components by default. Mark client components with `'use client'` explicitly.
- **P0** — Use TypeScript strict mode. No `any` types without explicit `// eslint-disable-next-line` justification.
- **P1** — Use Zustand for global state. Props for local state. No prop drilling deeper than 2 levels.
- **P1** — Use Tailwind utility classes. No arbitrary values unless absolutely necessary.
- **P2** — Prefer `const` assertions and discriminated unions over enums.

## Security Rules

- **P0** — Never log secrets (API keys, tokens, PII). Always redact before logging.
- **P0** — All user input must pass through the prompt-injection sanitizer before reaching any LLM.
- **P1** — Docker sandbox for code execution: no network, read-only FS, 512MB RAM, 30s timeout.
- **P1** — Rate limit every endpoint. Max 60 req/min, 100k tokens/min.

## Observability Rules

- **P1** — Every agent invocation must emit an OpenTelemetry span with agent name, model used, latency, token count.
- **P1** — Every API route must increment `nexus_requests_total` Prometheus counter.
- **P2** — Log at INFO level for happy path, DEBUG for internals, WARNING for recoverable errors, ERROR for failures.

## Testing Rules

- **P0** — Every new module must include at least one test file in the same directory or `tests/` mirror.
- **P1** — Use pytest-asyncio for async tests. Use pytest-cov — minimum 70% coverage for new code.
- **P1** — Mock external calls (Ollama, Redis, Brave API) in unit tests. Integration tests may use real services.

---

## Interaction Rules (How Cascade behaves)

- **P0** — Before writing code, verify the file does not already exist. If it does, read it first.
- **P1** — When editing code, prefer `edit` or `multi_edit` over rewriting entire files.
- **P1** — Always cite files with absolute paths and line numbers when referencing code.
- **P2** — When uncertain about a requirement, ask ONE clarifying question. Do not guess.
- **P2** — When a design flaw is detected, flag it before implementing.
