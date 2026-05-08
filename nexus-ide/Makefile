.PHONY: test test-backend test-frontend test-unit test-integration test-e2e \
        lint lint-backend lint-frontend dev backend frontend setup clean \
        healthcheck smoke-test selftest test-agents test-tools test-memory \
        test-orchestrator observability format help

# ─── Testing ───────────────────────────────────────────────────────────

test: test-backend test-frontend

test-backend:
	cd backend && python -m pytest tests/ --cov=. --cov-report=term-missing --cov-fail-under=70 -v

test-frontend:
	cd frontend && npm test

test-unit:
	cd backend && python -m pytest tests/ -m "not integration and not e2e" --cov=. --cov-report=term-missing -v

test-integration:
	cd backend && python -m pytest tests/ -m "integration" -v

test-e2e:
	cd frontend && npx playwright test

test-agents:
	cd backend && python -m pytest tests/agents/ -v

test-tools:
	cd backend && python -m pytest tests/tools/ -v

test-memory:
	cd backend && python -m pytest tests/knowledge/ -v

test-orchestrator:
	cd backend && python -m pytest tests/orchestrator/ -v

# ─── Quality ───────────────────────────────────────────────────────────

lint-backend:
	cd backend && ruff check . && mypy . --ignore-missing-imports

lint-frontend:
	cd frontend && npm run lint && npm run type-check

lint: lint-backend lint-frontend

format:
	cd backend && ruff format .
	cd frontend && npx prettier --write .

# ─── Development ───────────────────────────────────────────────────────

dev:
	docker compose -f docker/docker-compose.yml up

backend:
	cd backend && python -m uvicorn backend.orchestrator.main:app --host 0.0.0.0 --port 8000 --reload

frontend:
	cd frontend && npm run dev

setup:
	bash scripts/setup.sh

# ─── Health & Diagnostics ──────────────────────────────────────────────

healthcheck:
	bash scripts/healthcheck.sh

smoke-test:
	bash scripts/smoke-test.sh

selftest:
	python scripts/selftest/run_diagnostics.py

observability:
	@echo "Starting observability stack..."
	docker compose -f docker/docker-compose.yml up prometheus -d
	@echo "Prometheus: http://localhost:9090"
	@echo "Backend metrics: http://localhost:8000/api/metrics/current"

# ─── Maintenance ───────────────────────────────────────────────────────

clean:
	docker compose -f docker/docker-compose.yml down -v
	rm -rf frontend/.next frontend/node_modules backend/__pycache__ backend/.pytest_cache backend/.ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

help:
	@echo "NEXUS IDE Makefile"
	@echo ""
	@echo "Testing:"
	@echo "  test              - Run all tests"
	@echo "  test-backend      - Backend pytest with coverage"
	@echo "  test-frontend     - Frontend vitest"
	@echo "  test-unit         - Unit tests only"
	@echo "  test-integration  - Integration tests"
	@echo "  test-e2e          - E2E tests with Playwright"
	@echo "  test-agents       - Agent tests"
	@echo "  test-tools        - Tool tests"
	@echo "  test-memory       - Memory/knowledge tests"
	@echo "  test-orchestrator - Orchestration engine tests"
	@echo ""
	@echo "Quality:"
	@echo "  lint              - All linters"
	@echo "  lint-backend      - ruff + mypy"
	@echo "  lint-frontend     - eslint + tsc"
	@echo "  format            - Auto-format code"
	@echo ""
	@echo "Development:"
	@echo "  dev               - Docker compose full stack"
	@echo "  backend           - Run backend only"
	@echo "  frontend          - Run frontend only"
	@echo "  setup             - Initial setup"
	@echo ""
	@echo "Health & Diagnostics:"
	@echo "  healthcheck       - Quick service health check"
	@echo "  smoke-test        - End-to-end smoke tests"
	@echo "  selftest          - AI self-diagnostics"
	@echo "  observability     - Start monitoring stack"
	@echo ""
	@echo "Maintenance:"
	@echo "  clean             - Clean all artifacts"
	@echo "  help              - This help message"
