@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ========================================
echo    NEXUS IDE - Iniciando Aplicacao
echo ========================================
echo.

REM Ensure Docker Desktop is running
echo [INFO] Verificando se Docker Desktop esta em execucao...
set "DOCKER_EXE=C:\Program Files\Docker\Docker\Docker Desktop.exe"
if exist "%DOCKER_EXE%" (
    tasklist /FI "IMAGENAME eq Docker Desktop.exe" 2>NUL | find /I "Docker Desktop.exe" >NUL
    if errorlevel 1 (
        start "" "%DOCKER_EXE%"
        timeout /t 10 /nobreak > NUL
    )
)
:docker_wait
docker ps > NUL 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Docker ainda nao esta rodando. Aguardando 5 segundos...
    timeout /t 5 /nobreak > NUL
    goto docker_wait
)

REM Verificar versao do Python
python -c "import sys; v=sys.version_info; sys.exit(0 if v.major==3 and v.minor in (12,13) else 1)" > NUL 2>&1
if %errorlevel% neq 0 (
    echo [AVISO] Versao do Python nao recomendada detectada.
    echo         Este projeto requer Python 3.12 ou 3.13.
    echo         Python 3.14+ pode causar falhas na instalacao de dependencias (pydantic, etc.)
    echo.
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
docker compose -f docker/docker-compose.yml up -d

REM Esperar pelos servicos a iniciarem
echo [INFO] A aguardar inicializacao dos servicos...
timeout /t 10 /nobreak > NUL

REM Verificar se tudo esta rodando
echo [INFO] Verificando status dos servicos...
docker compose -f docker/docker-compose.yml ps

REM Iniciar backend e frontend em background
echo [INFO] Iniciando Backend e Frontend...
set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

REM Backend: executa via run.py para evitar RuntimeError do multiprocessing no Windows
start /B cmd /c "cd /d "%PROJECT_ROOT%" && python run.py"

REM Frontend
start /B cmd /c "cd /d "%PROJECT_ROOT%\frontend" && npm run dev"

REM Abrir navegador
echo [INFO] Abrindo navegador para http://localhost:3000...
echo [TESTE] Pulando abertura do navegador

REM Mostrar mensagens de status
echo.
echo ========================================
echo    NEXUS IDE - Iniciado com Sucesso!
echo ========================================
echo.
echo Servicos em http://localhost:
echo   - IDE:        3000
echo   - API Docs:   8000/docs
echo   - Prometheus: 9090
echo   - Dashboard:  3000/dashboard
echo.
echo Use stop.bat para encerrar todos os servicos.
echo.
exit /b 0
