# CHANGELOG — NEXUS IDE

## [2026-06-07] — Documentation Cleanup & Agent Hardening

### Fixed
- **Agentes:** Loop ReAct agora e obrigatorio; ferramentas em falta registadas corretamente
- **Dashboard:** Eliminadas chamadas API duplicadas e conexoes SSE redundantes

### Added
- **Chat:** Timeout handling, sincronizacao de modo, UI de upload de ficheiros, indicador de projeto
- **Relatorios:** Arquivados 35+ documentos de auditoria/relatorio para `.archive/`

### Changed
- **Dashboard:** Metricas centralizadas com Zustand store; removida dependencia d3; lazy loading de componentes
- **Documentacao:** README sincronizado com `config/models.yaml` (matriz de modelos actualizada)

---

## [2026-05-29] — Deep Verification & Hardening

### Fixed
- **Chat SSE:** `request.is_disconnected()` no longer raises `NameError` inside `_run_pipeline` — `Request` object now passed explicitly
- **Frontend file attachments:** Files selected in chat UI are now read and inlined into the message body (text files up to 50KB, binary files referenced by name)
- **Frontend console noise:** All `console.error/log/warn/debug` calls replaced with `log.*` helper that only emits in development
- **Frontend build:** Type-check and production build both clean

### Changed
- Frontend imports organized for `log` helper usage across 11 files

---

## [2026-05-29] — Audit Recovery

### Fixed
- **Build:** `pyproject.toml` now explicitly declares `packages = ["backend"]` to fix setuptools auto-discovery failure
- **Streaming:** `ollama_client.py` no longer crashes when messages are already dictionaries (`.to_dict()` guard)
- **Tests:** Fixed 10 broken tests across agents, orchestrator, tools, and integration suites
  - Updated `OrchestrationEngine` constructor param from `ollama` to `llm_client` in tests
  - Added missing `scaffold_project` to expected actions in `test_base.py`
  - Fixed shell runner assertions for actual return structure (`exit_code` vs `success`)
  - Fixed directory tools tests to match implementation (no `confirm` param)
  - Fixed project analyzer tests for actual return schema
  - Fixed agent stream tests to account for ReAct event markers
  - Fixed Windows path separator bug in project analyzer test detection
- **Frontend:** Chat send button now clears input immediately and has `pointer-events-none` on icon to prevent click interception

### Changed
- Project analyzer now detects `tests/` directories on Windows (path separator normalization)
- Shell runner timeout test uses `node` instead of `sleep` (cross-platform compatibility)

### Known Issues
- 2 tests exhibit pollution when run in full suite (pass in isolation)
- Dashboard Ollama on :11435 is optional; backend starts gracefully without it

---

## [2026-05-25] — Production Readiness

### Added
- PRODUCTION_READINESS_REPORT.md (arquivado em `.archive/`)
- GitHub Actions CI workflow
- Security headers middleware
- Rate limiting per IP
- JWT authentication
- Docker sandbox for code execution

### Changed
- Updated README with 435 tests badge
- Improved routing confidence scoring

---

## [2026-05-13] — Major Refactor

### Added
- Multi-agent orchestration engine
- ReAct loop with tool parsing
- Dependency graph and execution plans
- Guardian agent for security monitoring
- Dashboard agent for metrics

### Changed
- Refactored agent base class to support streaming and tool execution
- Updated models.yaml with fallback chains
