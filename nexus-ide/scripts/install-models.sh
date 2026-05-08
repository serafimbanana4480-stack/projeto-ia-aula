#!/usr/bin/env bash
# NEXUS / LUSO AI — Multi-Model Stack Installer
# Instala 5 modelos especializados em paralelo via Ollama.
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔═══════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   NEXUS — Multi-Model Stack Installer         ║${NC}"
echo -e "${BLUE}║   Stack: MICRO + FAST + CODER + REASON + DEEP ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════╝${NC}"

if ! command -v ollama &>/dev/null; then
  echo -e "${RED}✗ ollama não instalado. Instala em https://ollama.com${NC}"
  exit 1
fi

if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo -e "${YELLOW}⚠ Ollama não está rodando. Iniciando...${NC}"
  ollama serve >/tmp/ollama.log 2>&1 &
  sleep 3
fi

declare -a MODELS=(
  "qwen2.5:0.5b|MICRO|~400MB|Perguntas triviais (1+1)"
  "qwen2.5:3b|FAST|~2GB|Respostas rápidas"
  "qwen2.5-coder:7b|CODER|~4.7GB|Código"
  "deepseek-r1:14b|REASONING|~9GB|Raciocínio multi-step"
  "qwen2.5:32b|DEEP|~20GB|Análises complexas"
)

echo -e "${BLUE}Modelos a instalar:${NC}"
for entry in "${MODELS[@]}"; do
  IFS='|' read -r model tier size desc <<< "$entry"
  echo -e "  ${GREEN}•${NC} $tier ($size) → $model — $desc"
done
echo ""

INSTALLED=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}')

pull_model() {
  local model="$1"
  local tier="$2"
  if echo "$INSTALLED" | grep -q "^${model}$"; then
    echo -e "${GREEN}✓ $tier ($model) já instalado${NC}"
  else
    echo -e "${YELLOW}↓ $tier ($model) — a baixar...${NC}"
    if ollama pull "$model" >/tmp/ollama-pull-${tier}.log 2>&1; then
      echo -e "${GREEN}✓ $tier ($model) instalado${NC}"
    else
      echo -e "${RED}✗ $tier ($model) falhou (ver /tmp/ollama-pull-${tier}.log)${NC}"
    fi
  fi
}

# Pull em paralelo (max 2 simultâneos para não sobrecarregar a rede)
PIDS=()
for entry in "${MODELS[@]}"; do
  IFS='|' read -r model tier size desc <<< "$entry"
  pull_model "$model" "$tier" &
  PIDS+=($!)
  if (( ${#PIDS[@]} >= 2 )); then
    wait "${PIDS[0]}"
    PIDS=("${PIDS[@]:1}")
  fi
done

for pid in "${PIDS[@]}"; do
  wait "$pid"
done

echo ""
echo -e "${BLUE}═══════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Stack completa instalada${NC}"
echo -e "${BLUE}═══════════════════════════════════════${NC}"
ollama list
