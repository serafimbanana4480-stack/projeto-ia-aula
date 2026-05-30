# CRITICAL_RISKS.md — NEXUS IDE

**Date:** 2026-05-29
**Severity Scale:** CRITICAL | HIGH | MEDIUM | LOW

---

## CRITICAL

### RISK-001: Default Secrets in Production
- **Location:** `.env.example`, `backend/config/settings.py`
- **Issue:** `SECRET_KEY` and `JWT_SECRET` have placeholder defaults
- **Impact:** If deployed without changing, trivial JWT forgery and session hijacking
- **Mitigation:** Settings validator already warns; add startup fatal error in production if defaults detected
- **Status:** Validator warns but does not block startup

### RISK-002: Test Pollution Causes False Negatives
- **Location:** `backend/tests/test_models_api.py`, `backend/tests/tools/test_directory_tools.py`
- **Issue:** 2 tests fail when run with full suite but pass in isolation
- **Impact:** Developers lose confidence in CI; real regressions may be missed
- **Mitigation:** Investigate shared state (likely DB or file system); add `pytest-randomly` to surface order-dependent bugs
- **Status:** Documented, needs investigation

---

## HIGH

### RISK-003: Windows Path Separator Bugs
- **Location:** `backend/tools/project_analyzer.py`, potentially others
- **Issue:** String matching on `/` fails on Windows (`\` separator)
- **Impact:** Feature detection (tests, frameworks) fails on Windows deployments
- **Mitigation:** Use `Path.as_posix()` or `.replace("\\", "/")` for all path string comparisons
- **Status:** Partially fixed in project_analyzer

### RISK-004: Missing Frontend Test Coverage
- **Location:** `frontend/tests/`
- **Issue:** Only 5 vitest tests, all shallow; Playwright E2E not running in CI
- **Impact:** UI regressions undetected; dashboard/chat bugs slip through
- **Mitigation:** Add component tests for chat streaming, dashboard widgets, file operations; enable Playwright in CI
- **Status:** Known gap

### RISK-005: Dashboard Ollama Instance Not Required
- **Location:** `backend/orchestrator/main.py`
- **Issue:** Background tasks start DashboardAgent and GuardianAgent unconditionally; DashboardAgent connects to `:11435`
- **Impact:** If dashboard Ollama is down, background tasks fail silently or spam logs
- **Mitigation:** Add graceful degradation when dashboard host is unreachable
- **Status:** Backend starts but logs warnings

---

## MEDIUM

### RISK-006: AgentName Literal Missing SUPERVISOR
- **Location:** `backend/models/api.py`
- **Issue:** `AgentName` type does not include `"SUPERVISOR"`, but registry registers `SupervisorAgent`
- **Impact:** If router ever returns SUPERVOR, Pydantic validation fails
- **Mitigation:** Add `"SUPERVISOR"` to `AgentName` Literal
- **Status:** Not observed in production yet

### RISK-007: GuardianAgent Not in Registry
- **Location:** `backend/orchestrator/registry.py`
- **Issue:** `build_default_registry()` omits `NexusGuardianAgent`
- **Impact:** Other agents cannot consult Guardian via `consult_agent` tool
- **Mitigation:** Add GuardianAgent to registry
- **Status:** Low impact since guardian runs as background task

### RISK-008: Shell Runner Whitelist Too Permissive
- **Location:** `backend/tools/shell_runner.py`
- **Issue:** `rm`, `cp`, `mv` are whitelisted; combined with path traversal could be dangerous
- **Impact:** Malicious agent could delete/modify files outside project
- **Mitigation:** Already has path validation via `_validate_command`; review for edge cases
- **Status:** Acceptable with current safeguards

### RISK-009: No Health Check on Dashboard Agent
- **Location:** `docker/docker-compose.yml`
- **Issue:** Docker compose lacks `healthcheck` stanzas for services
- **Impact:** Orchestrator may not know when Ollama is ready
- **Mitigation:** Add `healthcheck` to docker-compose services
- **Status:** Documented in config audit

### RISK-010: CORS Origins Too Permissive in Dev
- **Location:** `backend/orchestrator/main.py`
- **Issue:** CORS allows `localhost:3000` and `127.0.0.1:3000` in all environments
- **Impact:** In production, this could allow local development origins
- **Mitigation:** `ALLOWED_ORIGINS` is env-driven; ensure prod overrides it
- **Status:** Configurable via `.env`

---

## LOW

### RISK-011: Unused Import in Supervisor
- **Location:** `backend/agents/supervisor.py:22`
- **Issue:** Imports `list_sessions` but never uses it
- **Impact:** None (cosmetic)
- **Mitigation:** Remove unused import

### RISK-012: E2E Tests Not in CI
- **Location:** `.github/workflows/ci.yml`
- **Issue:** Playwright E2E tests not automated in GitHub Actions
- **Impact:** Manual testing required for full user flows
- **Mitigation:** Add E2E job to CI workflow

### RISK-013: Codecov Upload Disabled
- **Location:** `.github/workflows/ci.yml`
- **Issue:** Coverage upload commented out
- **Impact:** No historical coverage tracking
- **Mitigation:** Re-enable when ready
