.PHONY: test test-backend test-frontend lint lint-backend lint-frontend dev setup clean help

test: test-backend test-frontend

test-backend:
	cd backend && pytest tests/ --cov=. --cov-report=term-missing --cov-fail-under=70

test-frontend:
	cd frontend && npm test

lint-backend:
	cd backend && ruff check . && mypy . --ignore-missing-imports

lint-frontend:
	cd frontend && npm run lint && npm run type-check

lint: lint-backend lint-frontend

dev:
	docker compose -f docker/docker-compose.yml up

setup:
	bash scripts/setup.sh

clean:
	docker compose -f docker/docker-compose.yml down -v
	rm -rf frontend/.next frontend/node_modules backend/__pycache__ backend/.pytest_cache backend/.ruff_cache

help:
	@echo "NEXUS IDE Makefile"
	@echo ""
	@echo "Targets:"
	@echo "  test          - Run all tests (backend + frontend)"
	@echo "  test-backend  - Run backend pytest with coverage"
	@echo "  test-frontend - Run frontend vitest"
	@echo "  lint          - Run all linters (backend + frontend)"
	@echo "  lint-backend  - Run ruff and mypy on backend"
	@echo "  lint-frontend - Run eslint and tsc on frontend"
	@echo "  dev           - Start dev environment with docker compose"
	@echo "  setup         - Run initial setup script"
	@echo "  clean         - Clean docker volumes and build artifacts"
	@echo "  help          - Show this help message"
