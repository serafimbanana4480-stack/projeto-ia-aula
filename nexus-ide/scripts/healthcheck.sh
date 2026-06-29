#!/bin/bash
# Nexus IDE — Quick Healthcheck
# Verifies that all core services are running and responding.
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0

check() {
    local name="$1"
    local cmd="$2"
    if eval "$cmd" &>/dev/null; then
        echo -e "  ${GREEN}✅${NC} $name"
        ((PASS++))
    else
        echo -e "  ${RED}❌${NC} $name"
        ((FAIL++))
    fi
}

echo ""
echo "============================================"
echo "  NEXUS IDE — Healthcheck"
echo "============================================"
echo ""

# Backend
check "Backend HTTP (port 8000)"    "curl -sf http://localhost:8000/health"
check "Backend API /api/modes"     "curl -sf http://localhost:8000/api/modes"
check "Backend API /api/tools"     "curl -sf http://localhost:8000/api/tools"
check "Backend API /api/projects"  "curl -sf http://localhost:8000/api/projects"

# Frontend
check "Frontend (port 3000)"       "curl -sf http://localhost:3000"

# Ollama
check "Ollama (port 11434)"        "curl -sf http://localhost:11434/api/tags"

# Database
check "SQLite DB exists"           "test -f data/nexus.db"

# Config
check "models.yaml exists"         "test -f config/models.yaml"
check "modes.yaml exists"          "test -f config/modes.yaml"

echo ""
echo "--------------------------------------------"
echo -e "  Results: ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}"
echo "--------------------------------------------"
echo ""

if [ $FAIL -gt 0 ]; then
    exit 1
fi
