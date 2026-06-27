#!/bin/bash
# Configuração da API key do OpenCode Go (OpenRouter)
set -e

echo "🔑 Configurando API key do OpenCode Go (OpenRouter)..."

# Verificar se já está configurado
if grep -q "OPENCODE_GO_API_KEY" .env 2>/dev/null; then
    echo "   ✅ OPENCODE_GO_API_KEY já existe no .env"
    echo "   Valor atual (mascarado):"
    grep "OPENCODE_GO_API_KEY" .env | sed 's/=\(.*\)/=***/' 
else
    echo "   ❌ OPENCODE_GO_API_KEY NÃO encontrado"
    echo ""
    echo "   📝 Por favor, adicione a sua API key do OpenRouter:"
    echo "   1. Aceda: https://openrouter.ai/keys"
    echo "   2. Crie uma API key"
    echo "   3. Adicione ao .env:"
    echo ""
    echo "   OPENCODE_GO_API_KEY=sua_api_key_aqui"
    echo "   OPENROUTER_API_KEY=sua_api_key_aqui  # (mesmo valor)"
    echo ""
    echo "   Alternativamente, edite o ficheiro: .env"
fi

echo ""
echo "🧪 Testando conexão com OpenCode Go..."
python -c "
from backend.llm.opencode_go import opencode_go
result = opencode_go.test_connection()
if result['success']:
    print('✅ Conexão OK!')
    print(f'   Modelos disponíveis: {len(result.get("models", {}).get("data", []))}')
else:
    print(f'❌ Erro: {result["error"]}')
"

echo ""
echo "✅ Configuração concluída!"
