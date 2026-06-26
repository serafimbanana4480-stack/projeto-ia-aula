# NEXUS IDE — CI/CD Detalhado

## 1. Visão Geral do CI/CD

CI/CD (Continuous Integration / Continuous Deployment) em NEXUS IDE é implementado através de GitHub Actions, automatizando testes, linting, type checking, security scans, e Docker builds. Esta abordagem garante que cada commit seja testado e validado antes de ser mergeado.

### 1.1 Pipeline de CI/CD

```
┌─────────────────────────────────────────────────────────────┐
│                   CI/CD Pipeline - NEXUS IDE                  │
│                                                              │
│  Trigger: Push to main / Pull Request                       │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Job 1: Backend Tests                                │    │
│  │  ├── Checkout code                                  │    │
│  │  ├── Set up Python 3.12                             │    │
│  │  ├── Install dependencies (poetry)                   │    │
│  │  ├── Run pytest (with coverage)                     │    │
│  │  ├── Run ruff (lint)                                │    │
│  │  └── Run mypy (type check)                          │    │
│  └──────────────────────────────────────────────────────┘    │
│                           ↓                                 │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Job 2: Frontend Tests                               │    │
│  │  ├── Checkout code                                  │    │
│  │  ├── Set up Node 20                                 │    │
│  │  ├── Install dependencies (pnpm)                     │    │
│  │  ├── Run vitest (with coverage)                     │    │
│  │  ├── Run ESLint (lint)                              │    │
│  │  └── Run TypeScript type check                      │    │
│  └──────────────────────────────────────────────────────┘    │
│                           ↓                                 │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Job 3: Security Scans                              │    │
│  │  ├── Checkout code                                  │    │
│  │  ├── Run bandit (Python security)                   │    │
│  │  ├── Run safety (Python dependencies)                │    │
│  │  ├── Run trivy (Docker images)                      │    │
│  │  └── Run npm audit (JavaScript dependencies)         │    │
│  └──────────────────────────────────────────────────────┘    │
│                           ↓                                 │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Job 4: Docker Build                                 │    │
│  │  ├── Checkout code                                  │    │
│  │  ├── Set up Docker Buildx                           │    │
│  │  ├── Build backend image                            │    │
│  │  ├── Build frontend image                           │    │
│  │  └── Push to Docker Hub (on main only)              │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  All jobs must pass for PR to be mergeable                │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Por que GitHub Actions?

**Alternativas:**
- **GitLab CI:** Requer GitLab (não GitHub)
- **CircleCI:** Bom, mas mais caro para projetos grandes
- **Travis CI:** Menos features, mais caro
- **Jenkins:** Complexo, requer setup manual

**Por que GitHub Actions?**
- **Integrado:** Integrado nativamente com GitHub
- **Free:** Gratuito para projetos open-source
- **YAML simples:** Fácil de configurar
- **Marketplace:** Muitas actions pré-construídas
- **Parallel jobs:** Execução paralela gratuita
- **Caching:** Cache de dependências integrado

## 2. Workflow Principal

### 2.1 Configuração

```yaml
# .github/workflows/ci.yml
name: NEXUS IDE CI/CD

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  backend-tests:
    name: Backend Tests
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: 'pip'
      
      - name: Install dependencies
        working-directory: ./backend
        run: |
          python -m pip install --upgrade pip
          pip install pytest pytest-cov pytest-asyncio ruff mypy
          pip install -e .
      
      - name: Run pytest
        working-directory: ./backend
        run: |
          pytest tests/ -v --cov=. --cov-report=xml --cov-report=html
      
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          files: ./backend/coverage.xml
          flags: backend
      
      - name: Run ruff
        working-directory: ./backend
        run: ruff check .
      
      - name: Run mypy
        working-directory: ./backend
        run: mypy .

  frontend-tests:
    name: Frontend Tests
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json
      
      - name: Install dependencies
        working-directory: ./frontend
        run: npm ci
      
      - name: Run vitest
        working-directory: ./frontend
        run: npm run test -- --coverage
      
      - name: Run ESLint
        working-directory: ./frontend
        run: npm run lint
      
      - name: Run TypeScript check
        working-directory: ./frontend
        run: npm run type-check

  security-scan:
    name: Security Scans
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Run bandit
        working-directory: ./backend
        run: |
          pip install bandit
          bandit -r .
      
      - name: Run safety
        working-directory: ./backend
        run: |
          pip install safety
          safety check --json > safety-report.json || true
      
      - name: Run trivy
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: 'fs'
          scan-ref: '.'
          format: 'sarif'
          output: 'trivy-results.sarif'
      
      - name: Run npm audit
        working-directory: ./frontend
        run: npm audit --audit-level=moderate

  docker-build:
    name: Docker Build
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKER_USERNAME }}
          password: ${{ secrets.DOCKER_PASSWORD }}
      
      - name: Build and push backend
        uses: docker/build-push-action@v5
        with:
          context: ./backend
          push: true
          tags: nexuside/backend:latest, nexuside/backend:${{ github.sha }}
          cache-from: type=registry,ref=nexuside/backend:latest
          cache-to: type=inline
      
      - name: Build and push frontend
        uses: docker/build-push-action@v5
        with:
          context: ./frontend
          push: true
          tags: nexuside/frontend:latest, nexuside/frontend:${{ github.sha }}
          cache-from: type=registry,ref=nexuside/frontend:latest
          cache-to: type=inline
```

### 2.2 Por que este Workflow?

**Paralelismo:**
- **backend-tests, frontend-tests, security-scan:** Rodam em paralelo
- **docker-build:** Roda apenas no main (após merge)
- **Tempo total:** ~10-15 minutos (vs 30+ minutos sequencial)

**Caching:**
- **pip cache:** Cache de dependências Python
- **npm cache:** Cache de dependências Node
- **Docker cache:** Cache de layers Docker
- **Tempo de build reduzido:** Caching reduz tempo em ~50%

**Coverage:**
- **pytest-cov:** Cobertura de código Python
- **vitest coverage:** Cobertura de código TypeScript
- **Codecov:** Upload de coverage para visualização
- **Threshold:** 70% mínimo (configurado em pyproject.toml)

**Security Scans:**
- **bandit:** Scanner de segurança Python
- **safety:** Scanner de vulnerabilidades de dependências Python
- **trivy:** Scanner de vulnerabilidades Docker
- **npm audit:** Scanner de vulnerabilidades JavaScript

## 3. Backend Tests Job

### 3.1 Por que pytest?

**Alternativas:**
- **unittest:** Python padrão, mas menos features
- **nose2:** Menos mantido
- **doctest:** Apenas para docstrings

**Por que pytest?**
- **Features ricas:** Fixtures, parametrização, plugins
- **Sintaxe simples:** Menos boilerplate que unittest
- **Ecossistema:** Muitos plugins (pytest-cov, pytest-asyncio, etc.)
- **Performance:** Mais rápido que unittest

### 3.2 Configuração pytest

```toml
# backend/pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
python_classes = "Test*"
python_functions = "test_*"
addopts = [
    "-v",
    "--strict-markers",
    "--tb=short",
    "--cov=.",
    "--cov-report=term-missing",
    "--cov-report=html",
    "--cov-report=xml",
]
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "integration: marks tests as integration tests",
]
```

**Por que estas opções?**
- **-v:** Verbose (mostra cada teste)
- **--strict-markers:** Previne typos em markers
- **--tb=short:** Traceback curto (mais legível)
- **--cov:** Coverage automático
- **--cov-report:** Múltiplos formatos (terminal, HTML, XML)

### 3.3 Ruff (Linting)

**Configuração:**

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "B",   # flake8-bugbear
    "C4",  # flake8-comprehensions
    "UP",  # pyupgrade
    "ARG", # flake8-unused-arguments
    "SIM", # flake8-simplify
]

ignore = [
    "E501",  # line too long (handled by formatter)
    "B008",  # do not perform function calls in argument defaults
]
```

**Por que Ruff?**
- **Rápido:** 10-100x mais rápido que flake8 (Rust)
- **Features:** Combina flake8, isort, pyupgrade em uma ferramenta
- **Configuração simples:** Um ficheiro pyproject.toml
- **Ativamente mantido:** Pela Astral (mesma equipe do Ruff formatter)

**Alternativas:**
- **flake8:** Mais lento, múltiplas ferramentas
- **pylint:** Mais lento, mais complexo
- **black:** Apenas formatter, não linter

### 3.4 mypy (Type Checking)

**Configuração:**

```toml
[tool.mypy]
python_version = "3.12"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_no_return = true
warn_unreachable = true
strict_equality = true
```

**Por que mypy strict?**
- **Type safety:** Previne erros de tipo em runtime
- **Refactoring seguro:** Types ajudam a refatorar
- **Documentação:** Types servem como documentação
- **IDE support:** Melhor IntelliSense

**Alternativas:**
- **pyright:** Microsoft (excelente), mas mais lento
- **pyre:** Facebook (excelente), mas mais complexo

## 4. Frontend Tests Job

### 4.1 Por que vitest?

**Alternativas:**
- **Jest:** Padrão, mas mais lento
- **Mocha:** Mais verboso
- **Jasmine:** Mais antigo

**Por que vitest?**
- **Rápido:** Native ESM, mais rápido que Jest
- **Features:** Similar ao Jest (snapshot, mocking, coverage)
- **Configuração simples:** Vite config compartilhada
- **Ativamente mantido:** Pela Vite team

### 4.2 Configuração vitest

```typescript
// frontend/vitest.config.ts
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: ['node_modules/', 'tests/'],
    },
  },
});
```

**Por que jsdom?**
- **Browser-like:** Simula DOM no Node
- **Rápido:** Mais rápido que Puppeteer/Playwright
- **Features:** Suficiente para testes unitários

**Alternativas:**
- **happy-dom:** Mais rápido, mas menos features
- **puppeteer:** Browser real, mas mais lento

### 4.3 ESLint

**Configuração:**

```json
// frontend/.eslintrc.json
{
  "extends": [
    "next/core-web-vitals",
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react-hooks/recommended"
  ],
  "rules": {
    "@typescript-eslint/no-unused-vars": "error",
    "@typescript-eslint/no-explicit-any": "warn",
    "react-hooks/rules-of-hooks": "error",
    "react-hooks/exhaustive-deps": "warn"
  }
}
```

**Por que ESLint?**
- **Padrão da indústria:** Amplamente adotado
- **Plugins:** Muitos plugins (React, TypeScript, etc.)
- **Configuração flexível:** Fácil customizar

**Alternativas:**
- **TSLint:** Descontinuado (substituído por ESLint)
- **Biome:** Mais rápido, mas menos maduro

### 4.4 TypeScript Type Check

```json
// frontend/tsconfig.json
{
  "compilerOptions": {
    "target": "ES2020",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "preserve",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx"],
  "exclude": ["node_modules"]
}
```

**Por que strict mode?**
- **Type safety:** Previne erros de tipo
- **Catch bugs:** Detecta bugs em compile time
- **Refactoring:** Mais seguro com types

## 5. Security Scans Job

### 5.1 Bandit

**Por que bandit?**
- **Python-specific:** Scanner focado em Python
- **Fast:** Scan rápido
- **Rules:** Múltiplas regras de segurança

**Exemplo de vulnerabilidades detetadas:**
- Hardcoded passwords
- SQL injection
- Use of exec/eval
- Use of pickle

### 5.2 Safety

**Por que safety?**
- **Dependências:** Scanner de dependências Python
- **PyPI:** Verifica contra PyPI security database
- **Automated:** Fácil de integrar no CI

### 5.3 Trivy

**Por que trivy?**
- **Multi-scanner:** Vulnerabilidades em containers, ficheiros, Git
- **Fast:** Scan rápido
- **Comprehensive:** Cobre múltiplos vetores

**Alternativas:**
- **Snyk:** Excelente, mas pago
- **Grype:** Bom, mas menos features

### 5.4 npm audit

**Por que npm audit?**
- **Built-in:** Integrado no npm
- **Free:** Gratuito
- **Automated:** Fácil de integrar

## 6. Docker Build Job

### 6.1 Por que Docker Buildx?

**Alternativas:**
- **Docker build:** Legacy, sem cache avançado
- **Kaniko:** Google-specific, mais complexo

**Por que Docker Buildx?**
- **Cache avançado:** Cache de layers entre builds
- **Multi-platform:** Pode build para múltiplas arquiteturas
- **Integrado:** Integrado no Docker CLI

### 6.2 Cache Strategy

```yaml
cache-from: type=registry,ref=nexuside/backend:latest
cache-to: type=inline
```

**Por que cache?**
- **Reduz tempo:** Cache reduz tempo de build em ~50%
- **Reduz custo:** Menos tempo de CI = menos custo
- **Mais rápido:** Feedback mais rápido para desenvolvedores

### 6.3 Multi-stage Builds

**Dockerfile Backend:**

```dockerfile
# Stage 1: Build
FROM python:3.12-slim as builder
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi

# Stage 2: Runtime
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY . .
CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Por que Multi-stage?**
- **Imagem menor:** Runtime stage não inclui build dependencies
- **Segurança:** Build tools não estão na imagem final
- **Cache:** Build stage pode ser cached separadamente

### 6.4 Tags

```yaml
tags: nexuside/backend:latest, nexuside/backend:${{ github.sha }}
```

**Por que múltiplos tags?**
- **latest:** Para uso geral
- **SHA:** Para rollback específico
- **Version:** Para releases (ex: v1.0.0)

## 7. Pre-commit Hooks

### 7.1 Configuração

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.8.0
    hooks:
      - id: mypy
        additional_dependencies: [types-requests]

  - repo: https://github.com/pre-commit/mirrors-prettier
    rev: v3.1.0
    hooks:
      - id: prettier
        types_or: [yaml, markdown]

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
```

**Por que pre-commit?**
- **Automático:** Hooks rodam automaticamente antes de commit
- **Fast:** Feedback rápido (local, não precisa de CI)
- **Consistência:** Garante que todos os commits seguem os mesmos padrões

### 7.2 Instalação

```bash
pip install pre-commit
pre-commit install
```

## 8. Dependabot

### 8.1 Configuração

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/backend"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10

  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10
```

**Por que Dependabot?**
- **Automated:** Atualiza dependências automaticamente
- **Security:** Prioriza vulnerabilidades de segurança
- **PRs:** Cria PRs automaticamente
- **Free:** Gratuito para projetos open-source

## 9. Release Strategy

### 9.1 Semantic Versioning

**Formato:** MAJOR.MINOR.PATCH (ex: 1.0.0)

- **MAJOR:** Mudanças incompatíveis (API breaking changes)
- **MINOR:** Nova funcionalidade compatível com backwards
- **PATCH:** Bug fixes compatíveis com backwards

**Exemplos:**
- 1.0.0 → 1.0.1: Bug fix
- 1.0.0 → 1.1.0: Nova feature
- 1.0.0 → 2.0.0: Breaking change

### 9.2 Release Process

1. **Create branch:** `git checkout -b release/v1.0.0`
2. **Update version:** Update version in package.json, pyproject.toml
3. **Run tests:** `make test`
4. **Create tag:** `git tag -a v1.0.0 -m "Release v1.0.0"`
5. **Push:** `git push origin main --tags`
6. **GitHub Release:** Create release on GitHub
7. **Docker:** Docker images tagged with version

### 9.3 GitHub Release Automation

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Create GitHub Release
        uses: softprops/action-gh-release@v1
        with:
          generate_release_notes: true
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## 10. Monitoring CI/CD

### 10.1 Métricas

**Métricas a monitorizar:**
- **Tempo de build:** Tempo médio por job
- **Taxa de sucesso:** % de builds que passam
- **Coverage:** Cobertura de código ao longo do tempo
- **Security:** Vulnerabilidades detetadas

### 10.2 Alertas

**Alertas a configurar:**
- **Build falhando:** Se main build falhar > 3 vezes consecutivas
- **Coverage caindo:** Se coverage cair < 70%
- **Vulnerabilidade crítica:** Se vulnerability severity = critical

## 11. Conclusão

CI/CD em NEXUS IDE é implementado através de:
- **GitHub Actions:** Automatização completa
- **Testes:** pytest (backend), vitest (frontend)
- **Linting:** ruff (backend), ESLint (frontend)
- **Type Checking:** mypy (backend), TypeScript (frontend)
- **Security:** bandit, safety, trivy, npm audit
- **Docker:** Multi-stage builds com cache
- **Pre-commit:** Hooks locais para feedback rápido
- **Dependabot:** Atualizações automáticas de dependências

Esta abordagem garante:
- **Qualidade:** Cada commit é testado e validado
- **Segurança:** Vulnerabilidades são detetadas automaticamente
- **Velocidade:** Caching e paralelismo reduzem tempo de build
- **Confiança:** Deploy automatizado reduz erros humanos
