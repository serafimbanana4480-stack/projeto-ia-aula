@echo off
setlocal enabledelayedexpansion

echo ========================================
echo    NEXUS IDE - Parando Aplicacao
echo ========================================
echo.

echo [INFO] Parando servicos Docker...
echo [INFO] Parando servicos Docker...
rem Using Docker Compose V2 to bring down the stack
docker compose -f docker/docker-compose.yml down -v

echo [INFO] Parando processos em background...
taskkill /F /IM uvicorn.exe > NUL 2>&1 || echo [WARN] uvicorn.exe not running
taskkill /F /IM node.exe > NUL 2>&1 || echo [WARN] node.exe not running

echo [INFO] Limpeando temporarios...
echo [INFO] Limpeza de recursos Docker e volumes temporarios...
rem Docker compose down already removed volumes; additional cleanup if needed
rem (Placeholder for any custom cleanup commands)

echo.
echo ========================================
echo    NEXUS IDE - Parado com Sucesso!
echo ========================================
echo.
echo Pressione qualquer tecla para continuar...
echo Pressione qualquer tecla para terminar... && pause > NUL
