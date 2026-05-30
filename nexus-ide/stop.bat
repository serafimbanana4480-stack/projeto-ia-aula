@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ========================================
echo    NEXUS IDE - Parando Aplicacao
echo ========================================
echo.

echo [INFO] Parando servicos Docker...
docker compose -f docker/docker-compose.yml down -v

echo [INFO] Parando processos em background...
REM Tenta matar uvicorn.exe (se executado diretamente) e python.exe (se via python -m uvicorn)
taskkill /F /IM uvicorn.exe > NUL 2>&1
taskkill /F /IM python.exe > NUL 2>&1
taskkill /F /IM node.exe > NUL 2>&1

echo [INFO] Limpeza concluida.
echo.
echo ========================================
echo    NEXUS IDE - Parado com Sucesso!
echo ========================================
echo.
pause
