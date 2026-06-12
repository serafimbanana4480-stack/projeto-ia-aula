@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

REM ============================================================================
REM NEXUS IDE - Start with Docker Compose (Ollama + Backend + Frontend)
REM ============================================================================

cd /d "%~dp0"
set "PROJECT_ROOT=%CD%"

echo ========================================
echo    NEXUS IDE - Docker Compose Start
echo ========================================
echo.

REM Check if Docker daemon is reachable
docker info >nul 2>&1
if !errorlevel! neq 0 (
    echo [ERRO] Docker nao esta acessivel.
    echo        Certifique-se de que o Docker Desktop esta ligado.
    echo        Alternativa: use start.bat --dev  (modo sem Docker)
    exit /b 1
)

REM Build and start the full stack
cd /d "%PROJECT_ROOT%\docker"
docker compose up --build -d

if !errorlevel! neq 0 (
    echo [ERRO] Falha ao iniciar a stack Docker.
    exit /b 1
)

echo.
echo ========================================
echo    NEXUS IDE - Stack Docker iniciada!
echo ========================================
echo.
echo Servicos:
echo   - IDE:        http://localhost:3000
echo   - API:        http://localhost:8000
echo   - API Docs:   http://localhost:8000/docs
echo   - Health:     http://localhost:8000/health
echo   - Prometheus: http://localhost:9090
echo.
echo Comandos uteis:
echo   - docker compose logs -f
echo   - docker compose down
echo   - stop.bat
echo.

pause
exit /b 0
