@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ========================================
echo    NEXUS IDE - Iniciando Aplicacao
echo ========================================
echo.

REM Ensure Docker Desktop is running
echo [INFO] Verificando se Docker Desktop está em execução...
set "DOCKER_EXE=C:\Program Files\Docker\Docker\Docker Desktop.exe"
if exist "%DOCKER_EXE%" (
    start "" "%DOCKER_EXE%"
    timeout /t 10 /nobreak > NUL
)
:docker_wait
docker ps > NUL 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Docker ainda não está rodando. Aguardando 5 segundos...
    timeout /t 5 /nobreak > NUL
    goto docker_wait
)

REM Verificar configuracao de ambiente
if not exist .env (
    echo [INFO] Criando arquivo .env...
    copy /y .env.example .env > NUL
    echo.
    echo Edite o arquivo .env para configurar as variaveis de ambiente.
    echo.
)

REM Iniciar Ollama (se necessario)
echo [INFO] Verificando modelos Ollama...
call scripts\check-ollama.bat

REM Iniciar servicos Docker
echo [INFO] Iniciando stack Docker...
docker compose up -d

REM Esperar pelos servicos a iniciarem
echo [INFO] A aguardar inicializacao dos servicos...
timeout /t 30 /nobreak > NUL

REM Verificar se tudo esta rodando
echo [INFO] Verificando status dos servicos...
echo [INFO] Verificando status dos servicos... && docker compose ps

REM Iniciar backend e frontend em background
echo [INFO] Iniciando Backend e Frontend...
start /B cmd /c "cd backend && uvicorn backend.orchestrator.main:app --host 0.0.0.0 --port 8000 --reload"
start /B cmd /c "cd frontend && npm run dev"

REM Abrir navegador
echo [INFO] Abrindo navegador para http://localhost:3000...
start http://localhost:3000

REM Mostrar mensagens de status
echo.
echo ========================================
echo    NEXUS IDE - Iniciado com Sucesso!
echo ========================================
echo.
echo Servicos em http://localhost:
echo   - IDE:      3000
echo   - API Docs: 8000/docs
echo   - Prometheus:9090
echo   - Dashboard:3000/dashboard
echo.
echo Pressione qualquer tecla para finalizar...

