@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ========================================
echo    NEXUS IDE - Iniciando Aplicacao
echo ========================================
echo.

REM Resolver um interpretador Python suportado no Windows
set "PYTHON_EXE="
set "PYTHON_ARGS="
python -c "import sys; v=sys.version_info; sys.exit(0 if v.major==3 and v.minor in (12,13) else 1)" > NUL 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_EXE=python"
) else (
    py -3.12 -c "import sys" > NUL 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3.12"
    ) else (
        py -3.13 -c "import sys" > NUL 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_EXE=py"
            set "PYTHON_ARGS=-3.13"
        )
    )
)

REM Paths configuraveis via variaveis de ambiente
if not defined DOCKER_DESKTOP_EXE set "DOCKER_DESKTOP_EXE=C:\Program Files\Docker\Docker\Docker Desktop.exe"
if not defined OLLAMA_EXE set "OLLAMA_EXE=C:\Ollama\Ollama.exe"
if not defined DOCKER_COMPOSE_FILE set "DOCKER_COMPOSE_FILE=docker\docker-compose.yml"

REM Ensure Docker Desktop is running
echo [INFO] Verificando se Docker Desktop esta em execucao...
set "DOCKER_EXE=%DOCKER_DESKTOP_EXE%"
set "DOCKER_WAIT_COUNT=0"
set "DOCKER_WAIT_MAX=24"

if exist "%DOCKER_EXE%" (
    tasklist /FI "IMAGENAME eq Docker Desktop.exe" 2>NUL | find /I "Docker Desktop.exe" >NUL
    if errorlevel 1 (
        echo [INFO] A iniciar Docker Desktop...
        start "" "%DOCKER_EXE%"
        echo [INFO] Aguardando Docker Desktop inicializar (pode demorar ate 60s no primeiro arranque)...
        timeout /t 20 /nobreak > NUL
    ) else (
        echo [INFO] Docker Desktop ja esta aberto. A verificar se o engine esta pronto...
    )
)

:docker_wait
docker info > NUL 2>&1
if %errorlevel% equ 0 (
    echo [OK] Docker engine esta pronto.
    goto docker_ready
)

REM docker info falhou — verificar se e erro de conexao ao daemon
docker ps > NUL 2>&1
if %errorlevel% equ 0 (
    echo [OK] Docker engine esta pronto.
    goto docker_ready
)

set /a DOCKER_WAIT_COUNT+=1
if %DOCKER_WAIT_COUNT% geq %DOCKER_WAIT_MAX% (
    echo [ERRO] Docker nao ficou pronto apos 2 minutos.
    echo.
    echo Possiveis causas:
    echo   1. Docker Desktop ainda esta inicializando (WSL2 pode demorar).
    echo   2. Docker Desktop esta em modo "Starting..." — aguarde manualmente.
    echo   3. WSL2 nao esta instalado ou esta corrompido.
    echo   4. Docker Desktop nao tem permissao para criar named pipes.
    echo.
    echo Sugestao: Abra o Docker Desktop manualmente e aguarde o indicador
    echo           ficar verde antes de correr este script novamente.
    exit /b 1
)

if %DOCKER_WAIT_COUNT% equ 1 (
    echo [INFO] Docker Desktop aberto, mas engine ainda nao responde. Aguardando...
) else (
    echo [INFO] Aguardando engine Docker... (tentativa %DOCKER_WAIT_COUNT%/%DOCKER_WAIT_MAX%)
)
timeout /t 5 /nobreak > NUL
goto docker_wait

:docker_ready

REM Verificar versao do Python
if not defined PYTHON_EXE (
    echo [ERRO] Python 3.12 ou 3.13 nao encontrado.
    echo        Instale uma versao suportada ou garanta que o launcher `py`
    echo        consegue resolver `-3.12` ou `-3.13`.
    exit /b 1
) else (
    echo [INFO] Usando Python via %PYTHON_EXE% %PYTHON_ARGS%
    echo.
)

REM Verificar Node.js e npm (necessarios para o frontend)
echo [INFO] Verificando Node.js e npm...
node --version > NUL 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Node.js nao encontrado. Instale o Node.js ^(versao 20+^).
    exit /b 1
)
npm --version > NUL 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] npm nao encontrado. Verifique a instalacao do Node.js.
    exit /b 1
)
echo [OK] Node.js e npm detectados.
echo.

REM Verificar configuracao de ambiente
if not exist .env (
    echo [INFO] Criando arquivo .env...
    copy /y .env.example .env > NUL
    echo.
    echo Edite o arquivo .env para configurar as variaveis de ambiente.
    echo.
)

REM Verificar servico e modelos Ollama
echo [INFO] Verificando Ollama...
call scripts\check-ollama.bat

REM Iniciar servicos Docker
echo [INFO] Iniciando stack Docker...
docker compose -f "%DOCKER_COMPOSE_FILE%" up -d

REM Esperar pelos servicos a iniciarem
echo [INFO] A aguardar inicializacao dos servicos...
timeout /t 30 /nobreak > NUL

REM Verificar se tudo esta rodando
echo [INFO] Verificando status dos servicos...
docker compose -f "%DOCKER_COMPOSE_FILE%" ps

REM Iniciar backend e frontend em background
echo [INFO] Iniciando Backend e Frontend...
set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

REM Backend: executa via run.py para evitar RuntimeError do multiprocessing no Windows
start /B cmd /c "cd /d "%PROJECT_ROOT%" && call %PYTHON_EXE% %PYTHON_ARGS% run.py"

REM Frontend
start /B cmd /c "cd /d "%PROJECT_ROOT%\frontend" && npm run dev"

REM Healthcheck do backend antes de abrir o navegador
echo [INFO] A aguardar backend ficar pronto...
set "HEALTH_URL=http://localhost:8000/docs"
set "HEALTH_RETRIES=0"
set "HEALTH_MAX=24"
:healthcheck_loop
set /a HEALTH_RETRIES+=1
curl -s "%HEALTH_URL%" > NUL 2>&1
if %errorlevel% equ 0 (
    echo [OK] Backend respondeu em %HEALTH_URL%.
    goto healthcheck_done
)
if %HEALTH_RETRIES% geq %HEALTH_MAX% (
    echo [AVISO] Backend nao respondeu apos %HEALTH_MAX% tentativas.
    echo          O navegador sera aberto mesmo assim, mas a API pode ainda estar a inicializar.
    goto healthcheck_done
)
timeout /t 2 /nobreak > NUL
goto healthcheck_loop
:healthcheck_done
echo.

REM Abrir navegador (pode ser suprimido via NEXUS_SKIP_BROWSER)
if not defined NEXUS_SKIP_BROWSER (
    echo [INFO] Abrindo navegador para http://localhost:3000...
    start http://localhost:3000
) else (
    echo [INFO] Modo sem browser ativo. Navegador nao sera aberto.
)

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

if not defined NEXUS_SKIP_PAUSE (
    pause
)
