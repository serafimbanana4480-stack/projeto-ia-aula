#!/bin/bash
# NEXUS IDE - Stop All Services Script

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

echo -e "${BLUE}=== NEXUS IDE - Stop All Services ===${NC}"
echo ""

# Function to stop process by PID file
stop_process() {
    local name=$1
    local pid_file="logs/$2.pid"
    
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        if ps -p $pid > /dev/null 2>&1; then
            echo -e "${YELLOW}Stopping $name (PID: $pid)...${NC}"
            kill $pid
            echo -e "${GREEN}✓${NC} $name stopped"
            rm "$pid_file"
        else
            echo -e "${YELLOW}✗${NC} $name (PID: $pid) is not running"
            rm "$pid_file"
        fi
    else
        echo -e "${YELLOW}✗${NC} No PID file found for $name"
    fi
}

# Stop services
stop_process "Ollama" "ollama"
stop_process "Backend" "backend"
stop_process "Frontend" "frontend"

# Also kill by port as fallback
echo ""
echo -e "${BLUE}Cleaning up by port...${NC}"
lsof -ti:11434 | xargs kill -9 2>/dev/null || echo "Nothing on port 11434"
lsof -ti:8000 | xargs kill -9 2>/dev/null || echo "Nothing on port 8000"
lsof -ti:3000 | xargs kill -9 2>/dev/null || echo "Nothing on port 3000"

echo ""
echo -e "${GREEN}=== All Services Stopped ===${NC}"
