#!/usr/bin/env bash
# NEXUS IDE — initial bootstrap with AirLLM.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "🚀 NEXUS IDE — initial setup (AirLLM)"

# 1. Validate .env
if [[ ! -f .env ]]; then
  echo "ℹ️  Creating .env from .env.example (edit BRAVE_API_KEY etc.)"
  cp .env.example .env
fi

# 2. Start infrastructure (Redis, Prometheus)
echo "🐳 Starting infrastructure..."
docker compose -f docker/docker-compose.yml up -d redis prometheus
sleep 5

# 3. Install Python dependencies
echo "📦 Installing Python dependencies..."
python -m pip install -r backend/requirements.txt

# 4. Pre-download essential AirLLM models
echo "⬇️  Pre-downloading AirLLM models (this may take a while)..."
python scripts/setup-airllm-models.py micro fast coder || echo "⚠️  Some models failed to download"

# 5. Build sandbox image used by the code_executor
echo "🔨 Building sandbox image..."
docker build -t nexus-sandbox -f docker/Dockerfile.sandbox . || echo "⚠️  sandbox build skipped"

echo ""
echo "✅ Setup complete!"
echo "   Start backend:  uvicorn backend.orchestrator.main:app --reload"
echo "   Start frontend: cd frontend && npm run dev"
