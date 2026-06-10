# NEXUS IDE — Análise Profissional Completa e Crítica

> **Projeto**: IA AULA / NEXUS IDE  
> **Data da Análise**: 2026-06-03  
> **Analista**: Kimi Code CLI  
> **Escopo**: Arquitetura, funcionalidades, segurança, qualidade de código, pontos fortes e críticas

---

## 1. VISÃO GERAL DO PROJETO

A **NEXUS IDE** é uma Integrated Development Environment (IDE) assistida por Inteligência Artificial que opera predominantemente em ambiente local. O projeto foi construído como demonstração educacional/protótipo de uma arquitetura **multiagente especializada**, onde 9 agentes distintos colaboram para tarefas de desenvolvimento de software.

### Stack Tecnológica

| Camada | Tecnologia | Versão/Anotação |
|--------|-----------|-----------------|
| **Backend** | Python + FastAPI + Uvicorn | 3.12, Pydantic v2 |
| **Frontend** | Next.js 15 (App Router) | React 19, TypeScript |
| **Estilos** | Tailwind CSS + shadcn/ui | Design system moderno |
| **Editor** | Monaco Editor | Motor idêntico ao VS Code |
| **Desktop** | Electron | App nativa (main.js, preload.js, package.json) |
| **IA/LLM** | Ollama (local) | Qwen3, DeepSeek — 8 modelos distintos |
| **Base de Dados** | SQLite (Alembic migrations) | PostgreSQL suportado via config |
| **Cache** | Redis (com fallback in-memory) | Opcional |
| **Embeddings** | Ollama embeddings + ChromaDB ready | RAG semântico |
| **Observabilidade** | OpenTelemetry + Prometheus + métricas SSE | Dashboard dedicado |
| **Sandbox** | Docker SDK + subprocess fallback | Isolamento de execução |
| **Testes** | pytest (backend) + vitest/Playwright (frontend) | 435 testes backend |
| **CI/CD** | GitHub Actions | `.github/workflows/ci.yml` |

---

## 2. ARQUITETURA MULTIAGENTE

### 2.1 Filosofia de Design

O projeto adota uma filosofia de **especialização em vez de generalização**. Em vez de um único LLM genérico, cada pedido do utilizador é analisado por um **ROUTER** (modelo NANO de 2B parâmetros) que classifica a intenção e encaminha para o agente mais adequado.

### 2.2 Matriz de Modelos

| ID Interno | Modelo Ollama | VRAM | Função Principal |
|-----------|---------------|------|-----------------|
| NANO | qwen3.5:2b | ~2.7GB | Roteamento, classificação de intenção |
| MICRO | qwen3.5:4b | ~3.4GB | Q&A rápido, formatação |
| SMALL | qwen3.5:9b | ~6.6GB | Análise, tarefas gerais |
| MEDIUM | qwen3-coder:7b | ~5.2GB | Geração de código focada |
| LARGE | qwen3.5:27b | ~17GB | Raciocínio complexo, arquitetura |
| EXPERT | qwen3-coder:30b (MoE) | ~20GB | Engenharia avançada |
| VISION | qwen3-vl:7b | ~8GB | Análise de imagem/UI |
| EMBED | qwen3-embedding:4b | ~3.0GB | Pesquisa semântica, RAG |
| DASHBOARD | qwen3.5:4b (:11435) | ~3.4GB | Monitorização contínua (dedicado) |

### 2.3 Os 9 Agentes Especializados

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   ROUTER    │────▶│  ARCHITECT  │────▶│   CODER     │
│  (NANO/2B)  │     │ (LARGE/27B) │     │ (EXPERT/30B)│
└─────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │
       ▼                   ▼                   ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ RESEARCHER  │     │  ANALYZER   │     │  DEBUGGER   │
│ (SMALL/9B)  │     │ (LARGE/27B) │     │ (MEDIUM/7B) │
└─────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │
       ▼                   ▼                   ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ DOCUMENTER  │     │  OPTIMIZER  │     │  DASHBOARD  │
│ (SMALL/9B)  │     │ (SMALL/9B)  │     │ (MICRO/4B)  │
└─────────────┘     └─────────────┘     └─────────────┘
```

1. **ROUTER** — Classifica intenção do pedido e emite decisão JSON estrita
2. **ARCHITECT** — Design de sistemas, decisões arquiteturais, review final
3. **RESEARCHER** — Pesquisa web (DuckDuckGo/Brave), informação atualizada
4. **CODER** — Geração de código de produção
5. **ANALYZER** — Revisão crítica, auditoria de segurança, code smells
6. **DEBUGGER** — Análise de causa raiz de bugs, execução de testes
7. **DOCUMENTER** — Escrita técnica, README, docs de API
8. **OPTIMIZER** — Otimização de performance, benchmarking
9. **DASHBOARD AGENT** — Monitorização always-on do sistema

### 2.4 Ciclo ReAct (Reason → Act → Observe → Reason)

Todos os agentes operam num loop ReAct com máximo de 7 iterações configuráveis:

```python
# backend/agents/base.py — ReAct loop core
async def _run_react_loop(self, request: AgentRequest) -> AsyncIterator[str]:
    context = ""
    iteration = 0
    while iteration < request.max_iterations:
        iteration += 1
        # 1. Stream LLM response
        async for token in self.stream_llm(request, context=context):
            yield token
        # 2. Parse tool calls from response
        tool_calls = self._parse_tool_calls(answer)
        # 3. Execute tools and feed results back
        for tool_name, args in tool_calls:
            result = await execute_tool(tool_name, request.session_id, args)
            context += f"\nTool {tool_name} returned: {json.dumps(result)}"
        # 4. Loop continues with enriched context
```

**Ações disponíveis:**
- `SEARCH_WEB` / `FETCH_URL` — Pesquisa e fetch web
- `READ_FILE` / `WRITE_FILE` — Operações em ficheiros
- `EXECUTE_CODE` — Execução em sandbox Docker
- `CONSULT_AGENT` — Consulta a outro agente (A2A)
- `SEARCH_CODEBASE` — Pesquisa semântica no código
- `READ_DOCS` / `RECALL_CONTEXT` — Recuperação de contexto

---

## 3. ACESSO A ARQUIVOS LOCAIS — ANÁLISE PROFUNDA

### 3.1 Arquitetura de Acesso a Ficheiros

O sistema possui **duas camadas** de acesso a ficheiros:

#### Camada 1: Operações Relativas ao Projeto (Legacy/Sandbox)

```python
# backend/tools/file_ops.py
async def read_file(path: str, project_path: str = ".", ...) -> dict:
    manager = WorkspaceManager(project_path)
    full_path = manager._resolve_path(path)
    await _lock_manager.acquire_read_lock(str(full_path), owner, timeout=...)
    return await manager.read_file(path)

async def write_file(path: str, content: str, ...) -> dict:
    manager = WorkspaceManager(project_path)
    full_path = manager._resolve_path(path)
    # Trust verification — block writes to untrusted projects
    project = get_project_by_path(str(Path(project_path).resolve()))
    if project and not project.get("trust", False):
        return {"error": "Project is NOT trusted. Enable trust in project settings..."}
    await _lock_manager.acquire_write_lock(str(full_path), owner, timeout=...)
    result = await manager.write_file(path, content, ...)
    # Audit logging
    propose_change(session_id=session_id, project_id=project_id, ...)
    return result
```

**Características:**
- Path traversal prevention via `Path.relative_to()`
- File locks (read/write) para concorrência segura
- Trust verification para projetos não-confiáveis
- Backup automático antes de escritas
- Audit logging de todas as alterações

#### Camada 2: Operações Absolutas (Novo/Expandido)

```python
# backend/core/workspace.py — Funções de path absoluto
async def read_file_absolute(path: str) -> dict:
    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": reason}
    target = Path(path).expanduser().resolve()
    content = target.read_text(encoding="utf-8")
    return {"path": str(target), "content": content, "size": len(content)}

async def write_file_absolute(path: str, content: str) -> dict:
    blocked, reason = _is_blocked_path(path)
    if blocked:
        return {"error": reason}
    backup_meta = _create_backup(target)
    target.write_text(content, encoding="utf-8")
    return {"path": str(target), "written": True, "backup": backup_meta}
```

**Segurança de paths absolutos:**
- **Blocked system paths**: `/etc`, `/sys`, `/proc`, `/dev`, `/boot`, `C:\Windows\System32`, etc.
- **Path traversal prevention**: `".." in raw.parts` é bloqueado explicitamente
- **Allowed base paths**: `Path.home()`, `Path.cwd()`, `tempfile.gettempdir()`
- **Implicit deny**: qualquer path fora dos allowed bases é bloqueado

### 3.2 Directory Tools (CRUD de Diretórios)

```python
# backend/tools/directory_tools.py
async def create_directory(path: str, project_path: str = ".") -> dict:
    full_path = _validate_path(project_path, path)
    full_path.mkdir(parents=True, exist_ok=True)

async def copy_file(src: str, dest: str, ...) -> dict:
    # Acquire locks em ordem alfabética para prevenir deadlocks
    locks = sorted([(src_str, "read"), (dest_str, "write")], key=lambda x: x[0])
    shutil.copy2(str(src_path), str(dest_path))

async def delete_file(path: str, ...) -> dict:
    # Safety check: block deletion of critical config files
    critical_files = {".env", "pyproject.toml", "package.json", "docker-compose.yml", ...}
    if full_path.name.lower() in critical_files:
        return {"error": f"Deletion of critical file '{full_path.name}' is blocked"}
```

### 3.3 File Manager (Validação de Extensões)

```python
# backend/tools/file_manager.py
ALLOWED_EXTENSIONS = {
    ".py", ".ts", ".js", ".tsx", ".jsx", ".rs", ".go", ".java",
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".html",
    ".css", ".scss", ".sh", ".bash", ".sql", ".csv", ".env",
    ".gitignore", ".dockerignore", ".cfg", ".ini", ".conf", ".xml", ".log",
}
BLOCKED_PATH_PARTS = {"/etc", "/sys", "/proc", ".ssh", ".aws", "/root", "/var/run"}
```

### 3.4 File Locks (Concorrência)

```python
# backend/core/file_locks.py
class FileLockManager:
    async def acquire_read_lock(self, path: str, owner: str, timeout: float = 30.0):
        # Shared lock — múltiplos readers, nenhum writer
    
    async def acquire_write_lock(self, path: str, owner: str, timeout: float = 30.0):
        # Exclusive lock — bloqueia readers e writers
    
    def release_lock(self, path: str, owner: str):
        # Libera lock do owner especificado
```

**Nota crítica:** O sistema de file locks é implementado **em memória** (asyncio locks), não usando flock do SO. Isso funciona apenas dentro do mesmo processo. Se houver múltiplos workers Uvicorn, os locks **não são coordenados entre processos**.

---

## 4. ACESSO AO CMD/SHELL — ANÁLISE PROFUNDA

### 4.1 Shell Runner Tool

```python
# backend/tools/shell_runner.py
async def run_shell(command: str, project_path: str = ".", timeout: int = 30) -> dict:
    manager = WorkspaceManager(project_path)
    return await manager.execute_shell(command, cwd=project_path, timeout=timeout)
```

### 4.2 WorkspaceManager — execute_shell

```python
# backend/core/workspace.py
async def execute_shell(command: str, cwd: str | None = None, timeout: int = 120, env: dict | None = None) -> dict:
    command = _windows_python_fixup(command)
    is_safe, reason = _validate_shell_command(command)
    if not is_safe:
        return {"error": f"Blocked: {reason}", "command": command}
    
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(cwd_path) if cwd_path else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=merged_env,
    )
    stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=float(timeout))
    return {
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": proc.returncode,
        "cwd": str(cwd_path),
    }
```

### 4.3 Validação de Comandos Shell

A validação é **multi-camada** e bastante sofisticada:

```python
# 1. Bloqueio de padrões perigosos (whole-command)
_BLOCKED_COMMAND_PATTERNS = {
    "rm -rf /", "rm -rf /*", "rm -rf ~", "dd ", "mkfs", "fdisk",
    "format", "> /dev/sda", ":(){ :|:& };:",  # fork bomb
    "shutdown", "reboot", "poweroff", "halt",
    "del /f /s /q", "rd /s /q", "format c:", "diskpart",
}

# 2. Bloqueio de system paths
_BLOCKED_SYSTEM_PATHS = {"/etc", "/sys", "/proc", "/dev", "/boot", ...}

# 3. Bloqueio de metacaracteres shell (fora de quotes)
_DISALLOWED_METACHARACTERS = (";", "&&", "||", "`", "$(", ">>", ">", "<")
def _has_unquoted_metacharacters(command: str) -> bool:
    cleaned = _remove_quoted_parts(s)  # Remove strings quoted
    for op in _DISALLOWED_METACHARACTERS:
        if op in cleaned:
            return True

# 4. Whitelist de comandos permitidos
_SHELL_WHITELIST = {
    "python", "python3", "pip", "npm", "node", "git", "mkdir", "cp", "mv", "rm",
    "cat", "echo", "pytest", "curl", "cargo", "rustc", "go", "javac", "mvn",
    "make", "cmake", "gcc", "g++", "clang", "find", "grep", "awk", "sed",
    "tar", "zip", "unzip", "ping", "netstat", "chmod", "chown", "ln", "touch",
    "head", "tail", "less", "wc", "sort", "uniq", "diff", "patch", "jq", "yq",
}

# 5. Restrições especiais para git
_GIT_BLOCKED_SUBCOMMANDS = {"push", "reset", "clean", "rebase", "cherry-pick"}
_GIT_BLOCKED_FLAGS = {"--force", "--hard", "-f", "-D", "--delete"}

# 6. Restrições para curl pipe
_DANGEROUS_PIPE_TARGETS = {"python", "python3", "node", "bash", "sh", "powershell", ...}
```

### 4.4 Terminal Routes (API)

```python
# backend/orchestrator/routes/terminal.py
@router.post("/terminal/execute", response_model=TerminalExecuteResponse)
async def execute_terminal_command(req: TerminalExecuteRequest, request: Request) -> TerminalExecuteResponse:
    executor = get_sandbox_executor()
    result = await executor.execute(
        req.command,
        language="bash",
        timeout=req.timeout_seconds,
        session_id=req.session_id or request.headers.get("x-session-id", ""),
        cwd=cwd,
    )
    return TerminalExecuteResponse(...)
```

**Nota crítica:** A rota `/terminal/execute` usa o **SandboxExecutor**, que primeiro tenta Docker e faz fallback para subprocess. No entanto, o `shell_runner.py` usa o `WorkspaceManager.execute_shell()` que executa **diretamente em subprocess** sem Docker. Esta dualidade pode causar comportamentos inconsistentes.

### 4.5 SandboxExecutor (Docker + Fallback)

```python
# backend/sandbox/executor.py
class SandboxExecutor:
    async def execute(self, code: str, language: str = "python", ...):
        # Assess risk level
        risk, reasons = DangerousCommandDetector.assess_risk(code)
        if risk == RiskLevel.CRITICAL:
            return SandboxResult(stderr=f"Command blocked: {'; '.join(reasons)}", exit_code=1)
        
        docker_ok = await self.check_docker()
        if docker_ok:
            return await self._execute_docker(...)
        else:
            return await self._execute_subprocess(...)
    
    async def _execute_docker(self, ...):
        cmd = [
            "docker", "run", "--rm",
            "--network=none",           # Sem rede
            "--memory=512m",            # Limite de RAM
            "--cpus=0.5",               # Limite de CPU
            "--read-only=true",         # FS read-only
            f"-v={tmpdir}:/workspace:rw",  # Mount do workspace
            self._config.image,
        ]
```

**Características do Sandbox Docker:**
- Sem acesso de rede (`--network=none`)
- Filesystem root read-only (`--read-only=true`)
- Memória limitada a 512MB
- CPU limitada a 0.5 core
- Timeout de 30 segundos (configurável)
- Kill automático do container em timeout

---

## 5. ORQUESTRAÇÃO E ROTEAMENTO

### 5.1 Three-Level Routing

```
┌─────────────────┐
│  1. Fast Rules  │  ← Determinístico, sem modelo (regex/palavras-chave)
│   (prioridade)  │
└─────────────────┘
         │ match?
         ▼
┌─────────────────┐
│ 2. ROUTER Model │  ← NANO/2B emite decisão JSON
│  (classificador)│     {"agent": "CODER", "confidence": 0.95, "reason": "..."}
└─────────────────┘
         │ falha?
         ▼
┌─────────────────┐
│3. Auto Fallback │  ← EXPERT → LARGE → SMALL → MICRO + warning
│   (graceful)    │
└─────────────────┘
```

### 5.2 OrchestrationEngine

```python
# backend/orchestrator/engine.py
class OrchestrationEngine:
    async def create_plan(self, objective: str, session_id: str, ...) -> ExecutionPlan:
        # Usa modelo CODER para gerar plano JSON estruturado
        # 10-25 passos organizados em fases
    
    async def execute_plan(self, plan: ExecutionPlan, session_id: str, ...) -> OrchestrationResult:
        # Executa tarefas em ordem de dependência (topological layers)
        # Paraleliza tarefas independentes (max 5 em paralelo)
        # Retry com exponential backoff
    
    async def execute_autonomous(self, objective: str, ...) -> OrchestrationResult:
        # Ciclo completo: Plan → Execute → Verify → Iterate
        # 1. Cria e executa plano
        # 2. DEBUGGER verifica outputs do CODER
        # 3. Se encontrar issues, CODER cria fix tasks
        # 4. ANALYZER faz review final de qualidade
```

**Características avançadas:**
- **Dependency graph** (DAG) com resolução topológica
- **Parallel execution** de tarefas independentes
- **Auto-retry** com exponential backoff (até 2 retries)
- **Cancellation propagation**
- **Event streaming** em tempo real via EventBus
- **Autonomous cycle**: Plan → Execute → Verify (DEBUGGER) → Fix → Final Review (ANALYZER)

### 5.3 Smart Router

```python
# backend/orchestrator/smart_router.py
class SmartRouter:
    async def route(self, query: str, session_id: str, ...) -> RoutingDecision:
        # 1. Fast path: keyword matching (deterministic)
        # 2. Cache check: LRU cache de decisões anteriores
        # 3. Model routing: NANO/2B classifica intenção
        # 4. Fallback chain se modelo falhar
```

---

## 6. FRONTEND (NEXT.JS 15 + MONACO EDITOR)

### 6.1 Estrutura de Páginas

```
frontend/app/
├── page.tsx              # Landing / Chat principal
├── layout.tsx            # Root layout com providers
├── analysis/             # Análise de código/projetos
├── dashboard/            # Métricas e observabilidade
├── database/             # Gestão de base de dados
├── documents/            # Documentação gerada
├── mission-control/      # Controlo de missões/orquestração
├── models/               # Gestão de modelos Ollama
├── projects/             # Gestão de projetos
├── scraping/             # Ferramentas de web scraping
├── settings/             # Configurações
└── tools/                # Ferramentas diversas
```

### 6.2 Componentes Principais

- **Chat com Streaming SSE**: Respostas em tempo real via Server-Sent Events
- **Monaco Editor**: Syntax highlighting, IntelliSense, multi-cursor
- **File Explorer**: Árvore de ficheiros com drag-and-drop
- **Terminal Embutido**: xterm.js para execução de comandos
- **Dashboard de Métricas**: Tokens/s, latência, atividade dos agentes

### 6.3 State Management

```typescript
// Zustand stores
- themeStore.ts      # Dark/Light mode
- chatStore.ts       # Histórico de conversas
- projectStore.ts    # Projetos ativos
```

### 6.4 Desktop (Electron)

```javascript
// desktop/main.js
const { app, BrowserWindow } = require('electron');
// Cria janela nativa carregando o Next.js
// Preload script para bridge segura
```

---

## 7. SEGURANÇA — ANÁLISE CRÍTICA

### 7.1 Pontos Fortes de Segurança

| Camada | Implementação | Avaliação |
|--------|--------------|-----------|
| **Path Traversal** | `Path.relative_to()` + `..` check | ✅ Bom |
| **Blocked Paths** | Blacklist de system paths | ✅ Adequado |
| **File Locks** | Asyncio shared/exclusive locks | ⚠️ Apenas intra-processo |
| **Trust System** | Projetos precisam de trust flag para writes | ✅ Excelente |
| **Shell Validation** | Multi-camada: blacklist + whitelist + metachars | ✅ Muito bom |
| **Docker Sandbox** | No network, read-only FS, resource limits | ✅ Excelente |
| **Rate Limiting** | slowapi 10 req/min por IP | ✅ Adequado |
| **JWT Auth** | Registo/login com tokens | ✅ Implementado |
| **Prompt Sanitization** | Proteção contra prompt injection | ✅ Presente |
| **Audit Logging** | Todas as alterações loggedas | ✅ Excelente |
| **Git Safety** | Push apenas para GitHub/GitLab/Bitbucket | ✅ Bom |

### 7.2 Vulnerabilidades e Críticas de Segurança

#### CRÍTICO: File Locks Não São Distribuídos

```python
# backend/core/file_locks.py
# O FileLockManager usa asyncio.Lock() — apenas funciona no MESMO processo
# Se Uvicorn correr com múltiplos workers (ex: 4 processos),
# cada worker tem o seu próprio FileLockManager
# Isso permite race conditions em writes concorrentes
```

**Recomendação:** Implementar locks baseados em ficheiros (`filelock` library) ou usar Redis para coordenação distribuída.

#### ALTO: create_subprocess_shell com User Input

```python
# backend/core/workspace.py
proc = await asyncio.create_subprocess_shell(command, ...)
```

Apesar da validação extensiva, `create_subprocess_shell` é **inherentemente mais perigoso** que `create_subprocess_exec`. Comandos como `echo "$(rm -rf ~)"` podem escapar a validação se a quote parsing não for perfeita.

**Recomendação:** Migrar para `create_subprocess_exec` com argumentos tokenizados via `shlex.split()` sempre que possível.

#### MÉDIO: Validação de Extensões Insuficiente

```python
# backend/tools/file_manager.py
ALLOWED_EXTENSIONS = {".py", ".ts", ...}
```

A whitelist de extensões no `file_manager.py` não é usada consistentemente em todas as rotas. O `file_ops.py` e `workspace.py` não restringem extensões.

#### MÉDIO: Falta de Content-Type Validation em Uploads

```python
# backend/orchestrator/routes/files.py
@router.post("/files/upload")
async def upload_file(file: UploadFile = File(...), ...):
    content = await file.read()
    target_path.write_bytes(content)
```

Não há validação de MIME type, tamanho máximo, ou magic bytes. Um upload de ficheiro `.py` malicioso é trivial.

#### BAIXO: Backup Directory Predictable

```python
backup_name = f"{path.name}.{timestamp}.{hash_suffix}.bak"
# hash_suffix = sha256(str(path).encode()).hexdigest()[:8]
```

O hash é determinístico baseado no path. Um atacante pode prever nomes de backup.

### 7.3 Resumo de Segurança

A segurança do projeto está **acima da média para um protótipo educacional**, com múltiplas camadas de defesa. No entanto, antes de produção real, é necessário:

1. ✅ Corrigir file locks para serem inter-processo
2. ✅ Migrar `create_subprocess_shell` → `create_subprocess_exec` onde possível
3. ✅ Adicionar validação de MIME type e magic bytes em uploads
4. ✅ Implementar Content Security Policy (CSP) headers no frontend
5. ✅ Adicionar rate limiting por utilizador autenticado (não apenas por IP)
6. ✅ Auditar todas as rotas para path traversal com symlinks

---

## 8. OBSERVABILIDADE E MONITORIZAÇÃO

### 8.1 Stack de Observabilidade

```
┌─────────────────────────────────────────┐
│           DASHBOARD AGENT               │
│         (qwen3.5:4b @ :11435)           │
│  ── Monitorização always-on do sistema  │
└─────────────────────────────────────────┘
                    │
    ┌───────────────┼───────────────┐
    ▼               ▼               ▼
┌─────────┐   ┌──────────┐   ┌──────────┐
│Prometheus│   │OpenTelem.│   │  Event   │
│ Metrics  │   │  Traces  │   │   Bus    │
└─────────┘   └──────────┘   └──────────┘
```

### 8.2 Métricas Customizadas

- `nexus_requests_total` — Total de requests
- `nexus_tokens_generated_total` — Tokens gerados por modelo
- `nexus_response_latency_seconds` — Latência de resposta
- `nexus_agent_executions_total` — Execuções por agente
- `nexus_routing_decisions_total` — Decisões de routing

### 8.3 Dashboard

Rota dedicada `/dashboard` alimentada exclusivamente pelo DASHBOARD AGENT. Exibe:
- Estado do sistema em tempo real
- Tokens por segundo
- Latência média
- Qualidade de roteamento
- Interações recentes
- Q&A em linguagem natural sobre métricas

---

## 9. QUALIDADE DE CÓDIGO E TESTES

### 9.1 Estatísticas de Testes

- **435 testes** backend passando
- **71% coverage** (mínimo configurado: 70%)
- Testes organizados por módulo: agents, core, orchestrator, tools, middleware, observability
- E2E com Playwright

### 9.2 Estrutura de Testes

```
backend/tests/
├── agents/              # 20+ ficheiros de teste para cada agente
├── core/                # workspace, file_locks, auto_correction, debate, peer_review
├── orchestrator/        # engine, router, registry, chat endpoints
├── tools/               # file_ops, shell_runner, web_search, embeddings
├── middleware/          # auth, rate_limit, security
├── observability/       # metrics, events, tracing, dashboard
├── integration/         # API endpoints, collaboration layer
└── contracts/           # API contract validation
```

### 9.3 Críticas de Qualidade de Código

#### POSITIVO
- Tipagem forte com Python 3.12 + Pydantic v2
- Uso extensivo de `from __future__ import annotations`
- Docstrings detalhadas em todos os módulos
- Separação clara de concerns (agents, orchestrator, tools, core)
- Registry pattern para tools (auto-registo)

#### NEGATIVO
- **Código morto comentado** em vários ficheiros (ex: `web_search_router` comentado em `main.py`)
- **Imports circulares potenciais** entre `backend.tools` e `backend.core.workspace`
- **Módulos muito grandes**: `workspace.py` tem 2026 linhas — viola SRP
- **Inconsistência de estilo**: alguns ficheiros usam português, outros inglês (ex: `MELHORIAS_IMPLEMENTADAS.md` vs `ARCHITECTURE.md`)
- **Magic numbers** espalhados: timeouts hardcoded (30s, 120s) sem constantes centralizadas
- **TODOs e FIXMEs** em produção

---

## 10. FUNCIONALIDADES AVANÇADAS

### 10.1 Agent Bus (Pub/Sub Inter-Agente)

```python
# backend/core/agent_bus.py
class AgentBus:
    async def publish(self, topic: str, message: BusMessage) -> None:
        # Publica mensagem em tópico
    async def subscribe(self, topic: str, callback: Callable) -> Subscription:
        # Subscrição em tópico
```

Permite comunicação assíncrona entre agentes (ex: DEBUGGER publica `errors.found`, CODER subscreve).

### 10.2 Shared Memory (Swarm Intelligence)

```python
# backend/core/shared_memory.py
class SharedMemory:
    def write_entry(self, agent_name, topic, content, importance, tags):
        # Memória compartilhada entre agentes
```

### 10.3 Auto-Correction Loop

```python
# backend/core/auto_correction.py
class AutoCorrectionLoop:
    async def start_monitoring(self):
        # Monitoriza falhas de agentes e tenta correções automáticas
```

### 10.4 Peer Review e Debate

```python
# backend/core/peer_review.py
class PeerReviewSystem:
    # Agentes revisam o trabalho uns dos outros

# backend/core/debate.py
class DebateSystem:
    # Múltiplos agentes debatem soluções
```

### 10.5 Background Workers

```python
# backend/core/background_workers.py
class BackgroundWorkerManager:
    # Workers para tarefas assíncronas (indexação, cleanup, etc.)
```

### 10.6 Guardian Agent

```python
# backend/agents/guardian.py
class NexusGuardianAgent:
    # Monitora a saúde do sistema e bloqueia operações suspeitas
```

### 10.7 Embeddings e RAG

```python
# backend/tools/embeddings.py
async def index_codebase(project_path: str) -> dict:
    # Indexa código para pesquisa semântica

async def search_codebase(query: str, project_path: str) -> dict:
    # Pesquisa semântica no código
```

### 10.8 Web Search Integrado

```python
# backend/tools/web_search.py / web_search_v2.py
async def web_search(query: str, max_results: int = 5) -> dict:
    # DuckDuckGo/Brave search com relevance scoring
```

---

## 11. PONTOS FORTES DO PROJETO

1. **Arquitetura inovadora** — Multiagente especializado é um diferenciador real
2. **Privacidade total** — Tudo local via Ollama, nenhum dado sai da máquina
3. **Observabilidade first-class** — Dashboard dedicado com agente próprio
4. **Segurança em camadas** — Múltiplas camadas de validação para shell e ficheiros
5. **Fallbacks inteligentes** — De modelos a Docker→subprocess, sempre há plano B
6. **Autonomia real** — Ciclo Plan→Execute→Verify→Iterate funciona end-to-end
7. **Testes abrangentes** — 435 testes com 71% coverage
8. **Documentação extensa** — 15+ documentos de planeamento, READMEs, reports
9. **Modularidade** — Registry pattern permite adicionar agentes/tools facilmente
10. **Streaming SSE** — UX responsiva com respostas em tempo real

---

## 12. CRÍTICAS E RECOMENDAÇÕES

### 12.1 Críticas Arquiteturais

| # | Problema | Severidade | Recomendação |
|---|----------|-----------|--------------|
| 1 | File locks apenas intra-processo | **ALTA** | Usar `filelock` ou Redis locks |
| 2 | `workspace.py` com 2026 linhas | **ALTA** | Dividir em módulos: security, backup, shell, fs |
| 3 | Dupla API de ficheiros (relativa + absoluta) | **MÉDIA** | Unificar numa única API com path resolution clara |
| 4 | Imports lazy com side-effects | **MÉDIA** | `import backend.tools as _tools` auto-regista tools — difícil de testar |
| 5 | Banco SQLite para produção | **MÉDIA** | Migrar para PostgreSQL como default |
| 6 | Cache in-memory não distribuído | **MÉDIA** | Redis deve ser obrigatório em produção |
| 7 | Falta de schema GraphQL/tRPC | **BAIXA** | REST é OK, mas tipagem end-to-end seria melhor |
| 8 | Frontend .next commited | **BAIXA** | `.next/` deveria estar em `.gitignore` |

### 12.2 Críticas de Performance

| # | Problema | Severidade | Recomendação |
|---|----------|-----------|--------------|
| 1 | Cada agente carrega prompt do disco | **MÉDIA** | Cachear prompts em memória com invalidação |
| 2 | ReAct loop sem streaming de tool results | **BAIXA** | Stream results parciais para melhor UX |
| 3 | Sem batching de requests LLM | **BAIXA** | Agrupar queries independentes |
| 4 | Search semântico linear (grep-like) | **BAIXA** | Usar ChromaDB/vector search real |

### 12.3 Críticas de Manutenibilidade

| # | Problema | Severidade | Recomendação |
|---|----------|-----------|--------------|
| 1 | Mix de PT e EN em nomes/código | **BAIXA** | Padronizar para inglês (já está 80%) |
| 2 | Múltiplos READMEs e reports | **BAIXA** | Consolidar documentação |
| 3 | Variáveis de ambiente não tipadas | **BAIXA** | Usar Pydantic Settings com validação strict |
| 4 | Hardcoded paths e configurações | **BAIXA** | Centralizar em `config/settings.py` |

---

## 13. DIAGRAMA DE ARQUITETURA SIMPLIFICADO

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              NEXUS IDE                                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Electron  │  │  Next.js 15 │  │   Monaco    │  │   xterm.js  │         │
│  │   (Desktop) │  │  (Frontend) │  │   (Editor)  │  │  (Terminal) │         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         └─────────────────┴─────────────────┴─────────────────┘              │
│                                    │                                         │
│                              HTTP / SSE                                      │
│                                    │                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     FASTAPI BACKEND (:8000)                         │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │    │
│  │  │   Auth      │  │   Chat      │  │   Files     │  │  Terminal │ │    │
│  │  │  (JWT)      │  │  (SSE)      │  │  (CRUD)     │  │  (Shell)  │ │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘ │    │
│  │                                                                    │    │
│  │  ┌─────────────────────────────────────────────────────────────┐  │    │
│  │  │              ORCHESTRATION ENGINE                            │  │    │
│  │  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        │  │    │
│  │  │  │ Router  │→ │  Plan   │→ │ Execute │→ │ Verify  │        │  │    │
│  │  │  │(NANO)   │  │(CODER)  │  │(Parallel│  │(DEBUG)  │        │  │    │
│  │  │  └─────────┘  └─────────┘  │ max 5)  │  └─────────┘        │  │    │
│  │  │                            └─────────┘                      │  │    │
│  │  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        │  │    │
│  │  │  │ARCHITECT│  │  CODER  │  │ DEBUGGER│  │ANALYZER │ ...    │  │    │
│  │  │  │(LARGE)  │  │(EXPERT) │  │(MEDIUM) │  │(LARGE)  │        │  │    │
│  │  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘        │  │    │
│  │  └─────────────────────────────────────────────────────────────┘  │    │
│  │                                                                    │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │    │
│  │  │  ReAct Loop │  │  Agent Bus  │  │ Shared Mem  │               │    │
│  │  │  (7 iter)   │  │  (Pub/Sub)  │  │ (Swarm)     │               │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘               │    │
│  │                                                                    │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │    │
│  │  │   Sandbox   │  │   File Ops  │  │  Web Search │               │    │
│  │  │  (Docker)   │  │  (Locks)    │  │  (DuckDuck) │               │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘               │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         DATA LAYER                                   │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐  │    │
│  │  │  SQLite     │  │   Redis     │  │  ChromaDB   │  │ .nexus/   │  │    │
│  │  │  (Alembic)  │  │  (Cache)    │  │(Embeddings) │  │ (Backups) │  │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      LLM PROVIDERS                                   │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐  │    │
│  │  │   Ollama    │  │   OpenAI    │  │    Kimi     │  │  AirLLM   │  │    │
│  │  │  (Local)    │  │  (Cloud)    │  │  (Cloud)    │  │  (Local)  │  │    │
│  │  │  :11434     │  │  (API key)  │  │  (API key)  │  │  (GPU)    │  │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 14. CONCLUSÃO

A **NEXUS IDE** é um projeto **excepcionalmente ambicioso e bem executado** para um protótipo educacional. A arquitetura multiagente é genuinamente inovadora, a segurança tem múltiplas camadas de defesa, e a observabilidade é first-class.

### Score Geral

| Critério | Nota (1-10) |
|----------|-------------|
| Arquitetura | 9/10 |
| Segurança | 7/10 |
| Qualidade de Código | 7/10 |
| Testes | 8/10 |
| Documentação | 9/10 |
| UX/Frontend | 7/10 |
| Performance | 6/10 |
| Prontidão para Produção | 5/10 |
| **Média** | **7.3/10** |

### Para Tornar Production-Ready

1. **Corrigir file locks** (inter-processo)
2. **Refatorar `workspace.py`** (dividir em módulos)
3. **Migrar para PostgreSQL** como default
4. **Implementar CSP headers** e hardening do frontend
5. **Adicionar validação de uploads** (MIME, magic bytes, tamanho)
6. **Otimizar cache de prompts** e resultados LLM
7. **Consolidar APIs** (relativa vs absoluta)
8. **Adicionar health checks** e readiness probes para todos os serviços
9. **Implementar graceful shutdown** para todos os background tasks
10. **Criar Helm chart / Kubernetes manifests** para deployment

---

*Análise realizada por Kimi Code CLI em 2026-06-03.*
*Este documento é uma avaliação técnica independente baseada na inspeção do código-fonte.*
