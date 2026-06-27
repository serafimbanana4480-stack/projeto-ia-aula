#!/bin/bash
# Instalação Automática do Ollama (Fallback Local)
set -e

echo "🦙 Verificando Ollama..."

if command -v ollama &> /dev/null; then
    echo "   ✅ Ollama já está instalado"
else
    echo "   📥 Instalando Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

echo "🚀 Iniciando Ollama..."
ollama serve &
sleep 3

echo "📦 Puxando modelo padrão (llama3.2)..."
ollama pull llama3.2

echo "✅ Ollama configurado e pronto!"
echo "   Endereço: http://localhost:11434"
