#!/usr/bin/env bash
# NEXUS IDE — initial bootstrap. See ARCHITECTURE.md §12.3.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "🚀 NEXUS IDE — initial setup"

# 1. Validate .env
if [[ ! -f .env ]]; then
  echo "ℹ️  Creating .env from .env.example (edit BRAVE_API_KEY etc.)"
  cp .env.example .env
fi

# 2. Start Ollama instances
echo "🐳 Starting Ollama (main + dashboard)..."
docker compose -f docker/docker-compose.yml up -d ollama-main ollama-dashboard
sleep 5

# 3. Pull models (lightest first to front-load routing + dashboard)
MAIN_MODELS=(
  "qwen3.5:2b"        # NANO
  "qwen3.5:4b"        # MICRO
  "qwen3.5:9b"        # SMALL
  "qwen3-coder:7b"    # MEDIUM
  "qwen3.5:27b"       # LARGE
  "qwen3-coder:30b"   # EXPERT
  "qwen3-embedding:4b"
)
echo "⬇️  Pulling models to the main Ollama instance..."
for m in "${MAIN_MODELS[@]}"; do
  echo "   - $m"
  docker exec nexus-ollama-main ollama pull "$m" || echo "   ⚠️  failed: $m (skipping)"
done

echo "⬇️  Pulling qwen3.5:4b on dashboard Ollama instance..."
docker exec nexus-ollama-dashboard ollama pull qwen3.5:4b

# 4. Build sandbox image used by the code_executor
echo "🧱 Building nexus-sandbox image..."
docker build -f docker/sandbox.Dockerfile -t nexus-sandbox:latest .

# 5. Bring up the rest of the stack
echo "🔧 Starting backend, frontend, redis, prometheus..."
docker compose -f docker/docker-compose.yml up -d

cat <<EOF

✅ NEXUS IDE is up.
   IDE        → http://localhost:3000
   Dashboard  → http://localhost:3000/dashboard
   Backend    → http://localhost:8000
   Prometheus → http://localhost:9090

EOF
