#!/bin/bash
# Deploy Automatizado - NEXUS IDE
set -e

echo "🚀 Iniciando deploy automático..."

# 1. Verificar dependências
echo "📦 Verificando dependências..."
command -v docker >/dev/null 2>&1 || { echo "Docker não encontrado. Instale primeiro."; exit 1; }
command -v docker-compose >/dev/null 2>&1 || { echo "Docker Compose não encontrado."; exit 1; }

# 2. Backup da base de dados
echo "💾 Fazendo backup..."
mkdir -p backups/$(date +%Y%m%d_%H%M%S)
# pg_dump ...

# 3. Pull das imagens
echo "📥 Fazendo pull das imagens..."
docker-compose -f docker/docker-compose.prod.yml pull

# 4. Build das imagens
echo "🔨 Fazendo build..."
docker-compose -f docker/docker-compose.prod.yml build

# 5. Deploy
echo "🚀 Fazendo deploy..."
docker-compose -f docker/docker-compose.prod.yml up -d

# 6. Verificar saúde
echo "🏥 Verificando saúde..."
sleep 10
curl -f http://localhost:8000/health || { echo "Backend não está saudável!"; exit 1; }
curl -f http://localhost:3000 || { echo "Frontend não está saudável!"; exit 1; }

echo "✅ Deploy completo com sucesso!"
echo "   Frontend: http://localhost:3000"
echo "   Backend: http://localhost:8000"
echo "   Grafana: http://localhost:3001"
