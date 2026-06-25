#!/bin/bash
# NEXUS IDE - Stop All Services (macOS / Linux)
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

echo -e "${BLUE}=== NEXUS IDE — Stopping All Services ===${NC}"

# Kill by PID files
for svc in ollama backend frontend; do
  pid_file="logs/${svc}.pid"
  if [[ -f "$pid_file" ]]; then
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      echo -e "${YELLOW}Stopping $svc (PID $pid)...${NC}"
      kill "$pid" 2>/dev/null || true
      sleep 1
      echo -e "${GREEN}[✓]${NC} $svc stopped"
    else
      echo -e "${YELLOW}[!]${NC} $svc (PID $pid) is not running"
    fi
    rm -f "$pid_file"
  fi
done

# Kill by port (macOS-compatible)
for port in 11434 8000 3000; do
  if command -v lsof &>/dev/null; then
    lsof -ti:"$port" | xargs kill -9 2>/dev/null || true
  elif command -v ss &>/dev/null; then
    ss -tlnp 2>/dev/null | grep ":$port " | awk '{print $7}' | sed 's/.*pid=//;s/,.*//' | xargs kill -9 2>/dev/null || true
  fi
done

echo ""
echo -e "${GREEN}=== All Services Stopped ===${NC}"
