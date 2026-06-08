#!/bin/bash
# NEXUS IDE - Unified Start Script
# Starts Ollama, Backend, and Frontend with proper logging and setup

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Project root
PROJECT_ROOT="/Users/240416/Desktop/ia aula/nexus-ide"
cd "$PROJECT_ROOT"

echo -e "${BLUE}=== NEXUS IDE - Unified Start Script ===${NC}"
echo ""

# Create logs directory
mkdir -p logs
mkdir -p data

# Initialize SQLite database
echo -e "${BLUE}[Setup] Initializing Database...${NC}"
source .venv/bin/activate
python -c "
from backend.persistence.db import init_db
init_db()
print('Database initialized successfully')
"
echo -e "${GREEN}✓${NC} Database initialized"

# Function to check if a process is running
check_process() {
    local name=$1
    local port=$2
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} $name is already running on port $port"
        return 0
    else
        echo -e "${YELLOW}✗${NC} $name is not running on port $port"
        return 1
    fi
}

# Check airllm (HF cache) and download missing models
echo -e "${BLUE}[1/3] Checking airllm model stack...${NC}"
if [ -f scripts/install-models.py ]; then
    source .venv/bin/activate
    python scripts/install-models.py
else
    echo -e "${YELLOW}⚠ scripts/install-models.py not found; skipping model check.${NC}"
fi

# Check Backend
echo -e "${BLUE}[2/3] Checking Backend...${NC}"
if ! check_process "Backend" 8000; then
    echo -e "${YELLOW}Starting Backend...${NC}"
    source .venv/bin/activate
    python -m backend.orchestrator.main > logs/backend.log 2>&1 &
    BACKEND_PID=$!
    echo -e "${GREEN}✓${NC} Backend started (PID: $BACKEND_PID)"
    sleep 3
else
    echo -e "${GREEN}✓${NC} Backend already running, skipping start"
fi

# Check Frontend
echo -e "${BLUE}[3/3] Checking Frontend...${NC}"
if ! check_process "Frontend" 3000; then
    echo -e "${YELLOW}Starting Frontend...${NC}"
    cd frontend
    npm run dev > ../logs/frontend.log 2>&1 &
    FRONTEND_PID=$!
    cd "$PROJECT_ROOT"
    echo -e "${GREEN}✓${NC} Frontend started (PID: $FRONTEND_PID)"
    sleep 3
else
    echo -e "${GREEN}✓${NC} Frontend already running, skipping start"
fi

echo ""
echo -e "${GREEN}=== All Services Started Successfully ===${NC}"
echo ""
echo "Services:"
echo "  • Backend API:   http://localhost:8000"
echo "  • Frontend:      http://localhost:3000"
echo "  • Dashboard:     http://localhost:3000/dashboard"
echo "  • Projects:      http://localhost:3000/projects"
echo "  • Models:        http://localhost:3000/models"
echo "  • Settings:      http://localhost:3000/settings"
echo ""
echo "Logs:"
echo "  • Backend:   logs/backend.log"
echo "  • Frontend:  logs/frontend.log"
echo ""
echo "To stop all services:"
echo "  ./stop-all.sh"
echo ""
echo "To view logs in real-time:"
echo "  tail -f logs/backend.log"
echo "  tail -f logs/frontend.log"
echo ""
echo "To install multi-model stack:"
echo "  ./scripts/install-models.sh"
echo ""

# Save PIDs for stop script
if [ -n "$OLLAMA_PID" ]; then echo $OLLAMA_PID > logs/ollama.pid; fi
if [ -n "$BACKEND_PID" ]; then echo $BACKEND_PID > logs/backend.pid; fi
if [ -n "$FRONTEND_PID" ]; then echo $FRONTEND_PID > logs/frontend.pid; fi

echo -e "${GREEN}Ready! Open http://localhost:3000 in your browser.${NC}"
