#!/bin/bash
# Nexus IDE — Smoke Tests
# Lightweight end-to-end tests that verify the full stack works.
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'
API="http://localhost:8000"

PASS=0
FAIL=0

smoke() {
    local name="$1"
    local desc="$2"
    local cmd="$3"
    echo -n "  $desc... "
    if eval "$cmd" &>/dev/null; then
        echo -e "${GREEN}PASS${NC}"
        ((PASS++))
    else
        echo -e "${RED}FAIL${NC}"
        ((FAIL++))
    fi
}

echo ""
echo "============================================"
echo "  NEXUS IDE — Smoke Tests"
echo "============================================"
echo ""

# 1. Health endpoint
smoke "health" "Health endpoint" \
    "curl -sf $API/health | grep -q ok"

# 2. Chat API (SSE)
smoke "chat" "Chat API streaming" \
    "curl -sf -N -X POST $API/api/chat \
        -H 'Content-Type: application/json' \
        -d '{\"message\":\"Say OK\",\"session_id\":\"smoke-test\"}' \
        --max-time 30 | grep -q 'token\|done'"

# 3. Session history
smoke "history" "Session history" \
    "curl -sf $API/api/sessions/smoke-test/history"

# 4. Models list
smoke "models" "Model status" \
    "curl -sf $API/api/models/status"

# 5. Modes
smoke "modes" "Modes endpoint" \
    "curl -sf $API/api/modes | grep -q modes"

# 6. Tools
smoke "tools" "Tools endpoint" \
    "curl -sf $API/api/tools | grep -q tools"

# 7. Projects
smoke "projects" "Projects CRUD" \
    "curl -sf $API/api/projects"

# 8. File read (test file)
echo "Nexus smoke test file" > /tmp/nexus_smoke_test.txt
smoke "files" "File read" \
    "curl -sf -X POST $API/api/files/read \
        -H 'Content-Type: application/json' \
        -d '{\"path\":\"/tmp/nexus_smoke_test.txt\",\"project_path\":\"/\"}'"
rm -f /tmp/nexus_smoke_test.txt

# 9. Metrics
smoke "metrics" "Metrics endpoint" \
    "curl -sf $API/api/metrics/current"

# 10. Dashboard
smoke "dashboard" "Dashboard endpoint" \
    "curl -sf $API/api/dashboard"

echo ""
echo "--------------------------------------------"
echo -e "  Results: ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}"
echo "--------------------------------------------"
echo ""

if [ $FAIL -gt 0 ]; then
    exit 1
fi
