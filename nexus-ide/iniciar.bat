@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

REM ============================================================================
REM NEXUS IDE - Script Unico de Arranque (Windows)
REM ============================================================================
REM Uso:
REM   iniciar.bat                  Iniciar backend + frontend (+ Docker/Ollama)
REM   iniciar.bat --dev            Modo leve (sem Docker nem Ollama)
REM   iniciar.bat --docker         Stack completa via Docker Compose
REM   iniciar.bat --parar          Parar todos os servicos
REM   iniciar.bat --help           Mostrar ajuda
REM ============================================================================

cd /d "%~dp0"
set "PROJECT_ROOT=%CD%"
set "NEXUS_LOG=%PROJECT_ROOT%\logs\iniciar.log"
set "NEXUS_SKIP_DOCKER=0"
set "NEXUS_SKIP_OLLAMA=0"
set "NEXUS_SKIP_BROWSER=0"
set "NEXUS_DEV_MODE=0"
set "NEXUS_DOCKER_MODE=0"
set "NEXUS_STOP_MODE=0"
set "PYTHON_EXE="
set "PYTHON_ARGS="

if not exist "%PROJECT_ROOT%\logs" mkdir "%PROJECT_ROOT%\logs"

REM --- Parse argumentos ---
:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--parar" set "NEXUS_STOP_MODE=1" & shift & goto :parse_args
if /I "%~1"=="--stop" set "NEXUS_STOP_MODE=1" & shift & goto :parse_args
if /I "%~1"=="--docker" set "NEXUS_DOCKER_MODE=1" & shift & goto :parse_args
if /I "%~1"=="--dev" set "NEXUS_DEV_MODE=1" & set "NEXUS_SKIP_DOCKER=1" & set "NEXUS_SKIP_OLLAMA=1" & shift & goto :parse_args
if /I "%~1"=="--skip-docker" set "NEXUS_SKIP_DOCKER=1" & shift & goto :parse_args
if /I "%~1"=="--skip-ollama" set "NEXUS_SKIP_OLLAMA=1" & shift & goto :parse_args
if /I "%~1"=="--skip-browser" set "NEXUS_SKIP_BROWSER=1" & shift & goto :parse_args
if /I "%~1"=="--verificar" set "NEXUS_SKIP_BROWSER=1" & set "NEXUS_SKIP_PAUSE=1" & shift & goto :parse_args
if /I "%~1"=="--help" goto :show_help
if /I "%~1"=="-h" goto :show_help
echo [AVISO] Argumento desconhecido: %~1
shift
if "%~1"=="" goto :args_done
goto :parse_args
:args_done

if "%NEXUS_STOP_MODE%"=="1" (
    if not defined NEXUS_SKIP_PAUSE set "NEXUS_SKIP_PAUSE=1"
    goto :stop_services
)
if "%NEXUS_DOCKER_MODE%"=="1" goto :start_docker

echo ========================================
echo    NEXUS IDE - Iniciando Aplicacao
echo ========================================
echo.
echo [INFO] Log: %NEXUS_LOG%
echo.

echo [%date% %time%] NEXUS IDE Start > "%NEXUS_LOG%"

REM ============================================================================
REM 1. DETETAR PYTHON
REM ============================================================================

echo [INFO] A detetar Python...

if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
    echo [OK] Python no venv: .venv\Scripts\python.exe
    goto :python_done
)

python -c "import sys; v=sys.version_info; sys.exit(0 if v.major==3 and v.minor>=12 else 1)" > NUL 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_EXE=python"
    echo [OK] Python no PATH
    goto :python_done
)

for %%V in (3.14 3.13 3.12) do (
    py -%%V -c "import sys" > NUL 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-%%V"
        echo [OK] Python via py launcher: %%V
        goto :python_done
    )
)

echo [ERRO] Python 3.12+ nao encontrado. Crie um venv: python -m venv .venv
exit /b 1

:python_done

REM ============================================================================
REM 2. DEPENDENCIAS BACKEND
REM ============================================================================

echo [INFO] A verificar dependencias do backend...
"%PYTHON_EXE%" %PYTHON_ARGS% -c "import fastapi" > NUL 2>&1
if !errorlevel! neq 0 (
    echo [INFO] A instalar dependencias do backend...
    "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r backend\requirements.txt
    if !errorlevel! neq 0 exit /b 1
)
echo [OK] Backend OK.

REM ============================================================================
REM 3. NODE.JS
REM ============================================================================

echo [INFO] A verificar Node.js...
node --version > NUL 2>&1
if !errorlevel! neq 0 (
    echo [ERRO] Node.js 20+ nao encontrado.
    exit /b 1
)
call npm --version > NUL 2>&1
if !errorlevel! neq 0 (
    echo [ERRO] npm nao encontrado.
    exit /b 1
)
echo [OK] Node.js e npm encontrados.

REM ============================================================================
REM 4. .env
REM ============================================================================

if not exist .env (
    echo [INFO] A criar .env a partir de .env.example...
    copy /y .env.example .env > NUL
    echo [AVISO] Edite o .env antes de reiniciar em producao.
)

REM ============================================================================
REM 5. DOCKER (opcional)
REM ============================================================================

if "%NEXUS_SKIP_DOCKER%"=="1" goto :docker_done

echo [INFO] A verificar Docker...
docker --version > NUL 2>&1
if !errorlevel! neq 0 (
    echo [AVISO] Docker nao encontrado. Modo sem sandbox Docker.
    set "NEXUS_SKIP_DOCKER=1"
    goto :docker_done
)

if exist "docker\docker-compose.yml" (
    echo [INFO] A iniciar servicos Docker...
    docker compose -f "docker\docker-compose.yml" up -d
    if !errorlevel! neq 0 (
        echo [AVISO] docker compose up falhou. A continuar sem Docker.
        set "NEXUS_SKIP_DOCKER=1"
    ) else (
        echo [OK] Docker iniciado.
    )
)

:docker_done

REM ============================================================================
REM 6. OLLAMA (opcional)
REM ============================================================================

if "%NEXUS_SKIP_OLLAMA%"=="1" goto :ollama_done

echo [INFO] A verificar Ollama...
ollama --version > NUL 2>&1
if !errorlevel! neq 0 (
    echo [AVISO] Ollama nao encontrado. Modelos locais indisponiveis.
    set "NEXUS_SKIP_OLLAMA=1"
    goto :ollama_done
)

echo [OK] Ollama encontrado.
if not defined OLLAMA_EXE set "OLLAMA_EXE=C:\Ollama\Ollama.exe"

ollama list > NUL 2>&1
if !errorlevel! neq 0 (
    if exist "!OLLAMA_EXE!" (
        echo [INFO] A iniciar Ollama...
        start "" "!OLLAMA_EXE!"
        timeout /t 5 >nul 2>&1
    )
)

echo [INFO] Modelos Ollama:
ollama list 2>nul

ollama show llama3.1:8b > NUL 2>&1
if !errorlevel! neq 0 (
    echo [INFO] A fazer pull de llama3.1:8b ^(modelo principal^)...
    start "" ollama pull llama3.1:8b
)

ollama show nomic-embed-text > NUL 2>&1
if !errorlevel! neq 0 (
    echo [INFO] A fazer pull de nomic-embed-text ^(embeddings^)...
    start "" ollama pull nomic-embed-text
)

:ollama_done

REM ============================================================================
REM 7. PORTAS
REM ============================================================================

echo [INFO] A verificar portas 3000 e 8000...
for %%P in (3000 8000) do (
    netstat -ano | findstr ":%%P " | findstr "LISTENING" > NUL 2>&1
    if !errorlevel! equ 0 (
        echo [AVISO] Porta %%P em uso. Use: iniciar.bat --parar
    ) else (
        echo [OK] Porta %%P livre.
    )
)

REM ============================================================================
REM 8. BACKEND
REM ============================================================================

echo [INFO] A iniciar Backend (FastAPI)...
start /B "NEXUS-BACKEND" cmd /c "cd /d "%PROJECT_ROOT%" && "%PYTHON_EXE%" %PYTHON_ARGS% run.py > logs\backend.log 2>&1"
timeout /t 3 >nul 2>&1
echo [OK] Backend iniciado. Log: logs\backend.log

REM ============================================================================
REM 9. FRONTEND
REM ============================================================================

echo [INFO] A iniciar Frontend (Next.js)...
if not exist "%PROJECT_ROOT%\frontend\node_modules\.bin\next" (
    echo [INFO] A instalar dependencias do frontend...
    pushd "%PROJECT_ROOT%\frontend"
    call npm install
    if !errorlevel! neq 0 exit /b 1
    popd
)

start /B "NEXUS-FRONTEND" cmd /c "cd /d "%PROJECT_ROOT%\frontend" && call npm run dev > ..\logs\frontend.log 2>&1"
timeout /t 3 >nul 2>&1
echo [OK] Frontend iniciado. Log: logs\frontend.log

REM ============================================================================
REM 10. HEALTHCHECK
REM ============================================================================

echo [INFO] A aguardar backend...
set "HEALTH_RETRIES=0"
:healthcheck_loop
set /a HEALTH_RETRIES+=1
curl -s "http://localhost:8000/health" > NUL 2>&1
if !errorlevel! equ 0 goto :healthcheck_ok
"%PYTHON_EXE%" %PYTHON_ARGS% -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" > NUL 2>&1
if !errorlevel! equ 0 goto :healthcheck_ok
if !HEALTH_RETRIES! geq 30 (
    echo [AVISO] Backend nao respondeu. Verifique logs\backend.log
    goto :healthcheck_done
)
timeout /t 2 >nul 2>&1
goto :healthcheck_loop

:healthcheck_ok
echo [OK] Backend responde em http://localhost:8000/health

:healthcheck_done

REM ============================================================================
REM 11. NAVEGADOR
REM ============================================================================

if "%NEXUS_SKIP_BROWSER%"=="0" (
    echo [INFO] A abrir navegador...
    start http://localhost:3000
)

echo.
echo ========================================
echo    NEXUS IDE - Iniciado!
echo ========================================
echo   IDE:      http://localhost:3000
echo   API:      http://localhost:8000
echo   Docs:     http://localhost:8000/docs
echo   Parar:    iniciar.bat --parar
echo.

if not defined NEXUS_SKIP_PAUSE pause
exit /b 0

REM ============================================================================
REM MODO DOCKER
REM ============================================================================
:start_docker
echo ========================================
echo    NEXUS IDE - Docker Compose
echo ========================================
docker info >nul 2>&1
if !errorlevel! neq 0 (
    echo [ERRO] Docker nao acessivel. Ligue o Docker Desktop ou use: iniciar.bat --dev
    exit /b 1
)
cd /d "%PROJECT_ROOT%\docker"
docker compose up --build -d
if !errorlevel! neq 0 exit /b 1
echo.
echo [OK] Stack Docker iniciada.
echo   IDE:  http://localhost:3000
echo   API:  http://localhost:8000
echo   Parar: iniciar.bat --parar
echo.
if not defined NEXUS_SKIP_PAUSE pause
exit /b 0

REM ============================================================================
REM PARAR SERVICOS
REM ============================================================================
:stop_services
echo ========================================
echo    NEXUS IDE - A Parar
echo ========================================
echo.

docker --version > NUL 2>&1
if !errorlevel! equ 0 (
    if exist "docker\docker-compose.yml" (
        docker compose -f "docker\docker-compose.yml" down > NUL 2>&1
        echo [OK] Docker parado.
    )
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F > NUL 2>&1
    echo [OK] Frontend ^(porta 3000^) encerrado.
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F > NUL 2>&1
    echo [OK] Backend ^(porta 8000^) encerrado.
)

echo.
echo [OK] Servicos parados.
if not defined NEXUS_SKIP_PAUSE pause
exit /b 0

REM ============================================================================
REM AJUDA
REM ============================================================================
:show_help
echo Uso: iniciar.bat [opcoes]
echo.
echo   ^(sem opcoes^)     Iniciar backend + frontend
echo   --dev             Modo leve ^(sem Docker/Ollama^)
echo   --docker          Stack completa via Docker Compose
echo   --parar, --stop   Parar todos os servicos
echo   --skip-docker     Ignorar Docker
echo   --skip-ollama     Ignorar Ollama
echo   --skip-browser    Nao abrir navegador
echo   --verificar       Iniciar sem browser nem pause ^(CI/testes^)
echo   --help            Mostrar esta ajuda
echo.
exit /b 0
