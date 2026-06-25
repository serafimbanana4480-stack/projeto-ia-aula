#!/bin/bash
# NEXUS IDE - Start Script for macOS / Linux
# Starts Backend and Frontend with proper logging and setup
#
# Usage:
#   ./start-mac.sh              Start backend + frontend (+ Ollama/Docker if available)
#   ./start-mac.sh --dev        Light mode (no Docker, no Ollama)
#   ./start-mac.sh --docker     Full stack via Docker Compose
#   ./start-mac.sh --setup      Only install dependencies (CI/clean)
#   ./start-mac.sh --status     Check running services
#   ./start-mac.sh --parar      Stop all services
#   ./start-mac.sh --help       Show help

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
NC='\033[0m'

# Project root (works from any checkout location)
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

# ─── Parse arguments ─────────────────────────────────────────────────
DEV_MODE=0
DOCKER_MODE=0
SETUP_MODE=0
STATUS_MODE=0
STOP_MODE=0
SKIP_BROWSER=0
SKIP_PAUSE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dev)    DEV_MODE=1; shift ;;
    --docker) DOCKER_MODE=1; shift ;;
    --setup)  SETUP_MODE=1; shift ;;
    --status) STATUS_MODE=1; shift ;;
    --parar|--stop) STOP_MODE=1; shift ;;
    --skip-browser) SKIP_BROWSER=1; shift ;;
    --skip-pause) SKIP_PAUSE=1; shift ;;
    --help|-h)
      echo "NEXUS IDE — macOS/Linux Start Script"
      echo ""
      echo "Usage: ./start-mac.sh [OPTION]"
      echo ""
      echo "Options:"
      echo "  --dev          Light mode (no Docker, no Ollama)"
      echo "  --docker       Full stack via Docker Compose"
      echo "  --setup        Only install dependencies"
      echo "  --status       Check running services"
      echo "  --parar/--stop Stop all services"
      echo "  --skip-browser Don't open browser automatically"
      echo "  --skip-pause   Don't pause at end"
      echo "  --help         Show this help"
      exit 0
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}"
      echo "Usage: ./start-mac.sh [--dev|--docker|--setup|--status|--parar|--help]"
      exit 1
      ;;
  esac
done

# ─── Helper functions ─────────────────────────────────────────────────
log()  { echo -e "${BLUE}[NEXUS]${NC} $1"; }
ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }

create_dirs() {
  mkdir -p logs data backend/data
}

# Check if a port is in use (macOS/Linux compatible)
is_port_in_use() {
  local port=$1
  if command -v lsof &>/dev/null; then
    lsof -Pi :"$port" -sTCP:LISTEN -t &>/dev/null
  elif command -v ss &>/dev/null; then
    ss -tlnp | grep -q ":$port "
  else
    netstat -tlnp 2>/dev/null | grep -q ":$port "
  fi
}

# Find PID listening on a port
pid_for_port() {
  local port=$1
  if command -v lsof &>/dev/null; then
    lsof -Pi :"$port" -sTCP:LISTEN -t 2>/dev/null || true
  elif command -v ss &>/dev/null; then
    ss -tlnp 2>/dev/null | grep ":$port " | awk '{print $7}' | sed 's/.*pid=//;s/,.*//' || true
  else
    netstat -tlnp 2>/dev/null | grep ":$port " | awk '{print $7}' | cut -d/ -f1 || true
  fi
}

# Kill process on a port
kill_port() {
  local port=$1
  local pid
  pid=$(pid_for_port "$port")
  if [[ -n "$pid" ]]; then
    warn "Port $port in use by PID $pid — killing..."
    kill "$pid" 2>/dev/null || true
    sleep 1
    # Force kill if still running
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
      sleep 0.5
    fi
    ok "Port $port freed"
  fi
}

# Detect Python (prefer python3, fallback python)
detect_python() {
  if command -v python3 &>/dev/null; then
    echo "python3"
  elif command -v python &>/dev/null; then
    echo "python"
  else
    err "Python not found. Install Python 3.12+ first."
    exit 1
  fi
}

# Detect Node.js
detect_node() {
  if ! command -v node &>/dev/null; then
    err "Node.js not found. Install Node.js 20+ first."
    exit 1
  fi
  local version
  version=$(node --version | sed 's/v//' | cut -d. -f1)
  if [[ "$version" -lt 20 ]]; then
    err "Node.js 20+ required, found $(node --version)"
    exit 1
  fi
  ok "Node.js $(node --version)"
}

# ─── Setup mode ──────────────────────────────────────────────────────
if [[ "$SETUP_MODE" -eq 1 ]]; then
  echo -e "${MAGENTA}=== NEXUS IDE — Setup ===${NC}"
  create_dirs
  detect_node

  PYTHON=$(detect_python)
  ok "Python: $($PYTHON --version 2>&1)"

  # Create venv if missing
  if [[ ! -d .venv ]]; then
    log "Creating Python virtual environment..."
    $PYTHON -m venv .venv
    ok "Virtual environment created"
  fi

  source .venv/bin/activate

  # Install Python dependencies
  if [[ -f requirements.txt ]]; then
    log "Installing Python dependencies from requirements.txt..."
    pip install -r requirements.txt
  else
    log "Installing Python dependencies from pyproject.toml..."
    pip install -e ".[dev]"
  fi
  ok "Python dependencies installed"

  # Install frontend deps
  log "Installing frontend dependencies..."
  cd frontend && npm install && cd "$PROJECT_ROOT"
  ok "Frontend dependencies installed"

  echo ""
  echo -e "${GREEN}=== Setup complete! ===${NC}"
  echo "Run ./start-mac.sh to start the IDE."
  exit 0
fi

# ─── Status mode ─────────────────────────────────────────────────────
if [[ "$STATUS_MODE" -eq 1 ]]; then
  echo -e "${MAGENTA}=== NEXUS IDE — Service Status ===${NC}"

  if is_port_in_use 8000; then
    local_pid=$(pid_for_port 8000)
    ok "Backend: RUNNING (PID $local_pid) → http://localhost:8000"
  else
    warn "Backend: NOT running"
  fi

  if is_port_in_use 3000; then
    local_pid=$(pid_for_port 3000)
    ok "Frontend: RUNNING (PID $local_pid) → http://localhost:3000"
  else
    warn "Frontend: NOT running"
  fi

  if command -v docker &>/dev/null; then
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q nexus; then
      ok "Docker containers: RUNNING"
      docker ps --filter "name=nexus" --format "  • {{.Names}} ({{.Ports}})"
    else
      warn "Docker: no NEXUS containers running"
    fi
  else
    warn "Docker: not installed"
  fi
  exit 0
fi

# ─── Stop mode ───────────────────────────────────────────────────────
if [[ "$STOP_MODE" -eq 1 ]]; then
  echo -e "${MAGENTA}=== NEXUS IDE — Stopping Services ===${NC}"

  # Kill by PID files first
  for svc in backend frontend; do
    if [[ -f "logs/${svc}.pid" ]]; then
      pid=$(cat "logs/${svc}.pid")
      if kill -0 "$pid" 2>/dev/null; then
        warn "Stopping $svc (PID $pid)..."
        kill "$pid" 2>/dev/null || true
        sleep 1
        ok "$svc stopped"
      fi
      rm -f "logs/${svc}.pid"
    fi
  done

  # Kill by port
  kill_port 8000
  kill_port 3000

  # Stop Docker if running
  if command -v docker &>/dev/null; then
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q nexus; then
      log "Stopping Docker containers..."
      docker compose -f docker/docker-compose.yml down 2>/dev/null || true
      ok "Docker containers stopped"
    fi
  fi

  echo ""
  echo -e "${GREEN}=== All Services Stopped ===${NC}"
  exit 0
fi

# ─── Main start ──────────────────────────────────────────────────────
echo -e "${MAGENTA}"
echo "  ╔═══════════════════════════════════════════╗"
echo "  ║        NEXUS IDE — macOS / Linux          ║"
echo "  ╚═══════════════════════════════════════════╝"
echo -e "${NC}"

create_dirs
detect_node

PYTHON=$(detect_python)
ok "Python: $($PYTHON --version 2>&1)"

# ─── Activate / create venv ──────────────────────────────────────────
if [[ ! -d .venv ]]; then
  log "Creating Python virtual environment..."
  $PYTHON -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# ─── Install dependencies if missing ──────────────────────────────────
if [[ -f requirements.txt ]]; then
  if ! pip list --format=columns 2>/dev/null | grep -q fastapi; then
    log "Installing Python dependencies..."
    pip install -r requirements.txt
    ok "Python deps installed"
  fi
else
  if ! pip list --format=columns 2>/dev/null | grep -q fastapi; then
    log "Installing Python dependencies from pyproject.toml..."
    pip install -e ".[dev]"
    ok "Python deps installed"
  fi
fi

if [[ ! -d frontend/node_modules ]]; then
  log "Installing frontend dependencies..."
  cd frontend && npm install && cd "$PROJECT_ROOT"
  ok "Frontend deps installed"
fi

# ─── Init database ──────────────────────────────────────────────────
log "Initializing database..."
$PYTHON -c "
import sys; sys.path.insert(0, '.')
from backend.persistence.db import init_db
init_db()
print('Database initialized')
" 2>/dev/null || warn "Database init skipped (will be created on first run)"
ok "Database ready"

# ─── Kill stale processes on our ports ──────────────────────────────
if is_port_in_use 8000; then
  old_pid=$(pid_for_port 8000)
  warn "Port 8000 in use (PID $old_pid). Use --parar or kill it manually."
  if [[ "$DEV_MODE" -eq 1 ]]; then
    warn "Dev mode: attempting to free port 8000..."
    kill_port 8000
  else
    err "Cannot start backend. Port 8000 is occupied."
    exit 2
  fi
fi

if is_port_in_use 3000; then
  old_pid=$(pid_for_port 3000)
  warn "Port 3000 in use (PID $old_pid). Use --parar or kill it manually."
  if [[ "$DEV_MODE" -eq 1 ]]; then
    warn "Dev mode: attempting to free port 3000..."
    kill_port 3000
  else
    err "Cannot start frontend. Port 3000 is occupied."
    exit 2
  fi
fi

# ─── Docker mode ─────────────────────────────────────────────────────
if [[ "$DOCKER_MODE" -eq 1 ]]; then
  if command -v docker &>/dev/null; then
    log "Starting full Docker stack..."
    docker compose -f docker/docker-compose.yml up -d
    ok "Docker stack started"
    echo ""
    echo -e "${GREEN}=== Stack running via Docker ===${NC}"
    echo "  • Backend:  http://localhost:8000"
    echo "  • Frontend: http://localhost:3000"
    echo "  • Docs:     http://localhost:8000/docs"
    echo "  • Prometheus: http://localhost:9090"
    echo ""
    echo "Run ./stop-all.sh to stop."
    exit 0
  else
    err "Docker not installed. Run ./start-mac.sh --dev for light mode."
    exit 1
  fi
fi

# ─── Check if Ollama is available ───────────────────────────────────
OLLAMA_AVAILABLE=0
if command -v ollama &>/dev/null; then
  OLLAMA_AVAILABLE=1
  if ! is_port_in_use 11434; then
    log "Starting Ollama..."
    ollama serve > logs/ollama.log 2>&1 &
    OLLAMA_PID=$!
    echo $OLLAMA_PID > logs/ollama.pid
    ok "Ollama started (PID $OLLAMA_PID)"
    sleep 2
  else
    OLLAMA_PID=$(pid_for_port 11434)
    ok "Ollama already running (PID $OLLAMA_PID)"
  fi
else
  warn "Ollama not found — LLM features will use cloud providers only"
fi

# ─── Start Backend ─────────────────────────────────────────────────
log "Starting Backend (uvicorn)..."
cd "$PROJECT_ROOT"
$PYTHON run.py > logs/backend.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > logs/backend.pid
ok "Backend started (PID $BACKEND_PID)"

# Wait for backend to be healthy
log "Waiting for backend to be ready..."
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1; then
    ok "Backend healthy after ${i}s"
    break
  fi
  if [[ $i -eq 30 ]]; then
    warn "Backend healthcheck timed out — check logs/backend.log"
  fi
  sleep 1
done

# ─── Start Frontend ────────────────────────────────────────────────
log "Starting Frontend (Next.js)..."
cd "$PROJECT_ROOT/frontend"
npm run dev > "$PROJECT_ROOT/logs/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > "$PROJECT_ROOT/logs/frontend.pid"
cd "$PROJECT_ROOT"
ok "Frontend started (PID $FRONTEND_PID)"

# Wait a moment for frontend to begin listening
sleep 3

# ─── Done! ──────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  NEXUS IDE — All Services Started!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo "  • Backend API:   http://localhost:8000"
echo "  • API Docs:      http://localhost:8000/docs"
echo "  • Frontend IDE:  http://localhost:3000"
echo ""
echo "  Logs:"
echo "  • Backend:       tail -f logs/backend.log"
echo "  • Frontend:      tail -f logs/frontend.log"
echo ""
echo "  Commands:"
echo "  • Stop all:      ./start-mac.sh --parar"
echo "  • Status:        ./start-mac.sh --status"
echo ""

if [[ "$SKIP_BROWSER" -eq 0 ]]; then
  if command -v open &>/dev/null; then
    sleep 1
    open http://localhost:3000 2>/dev/null || true
  fi
fi

if [[ "$SKIP_PAUSE" -eq 0 ]]; then
  echo -e "${YELLOW}Press Ctrl+C to stop all services.${NC}"
  echo ""
  trap '' INT
  wait
fi
