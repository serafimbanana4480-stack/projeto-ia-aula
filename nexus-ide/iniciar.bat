@echo off
setlocal enabledelayedexpansion
chcp 65001 > NUL 2>&1

REM ============================================================================
REM  NEXUS IDE - Script Unico de Arranque (Windows)
REM  Versao: 2.0.0
REM  Data:   2026-06-18
REM ============================================================================
REM  Uso:
REM    iniciar.bat                    Iniciar backend + frontend (+ Docker/Ollama)
REM    iniciar.bat --dev              Modo leve (sem Docker nem Ollama)
REM    iniciar.bat --docker           Stack completa via Docker Compose
REM    iniciar.bat --setup            Apenas instalar dependencias (CI/clean)
REM    iniciar.bat --status           Verificar servicos em execucao
REM    iniciar.bat --reset            Parar + limpar + reinstalar do zero
REM    iniciar.bat --parar            Parar todos os servicos
REM    iniciar.bat --help             Mostrar ajuda
REM ============================================================================

cd /d "%~dp0"
set "PROJECT_ROOT=%CD%"
set "NEXUS_LOG=%PROJECT_ROOT%\logs\iniciar.log"
set "NEXUS_SKIP_DOCKER=0"
set "NEXUS_SKIP_OLLAMA=0"
set "NEXUS_SKIP_BROWSER=0"
set "NEXUS_SKIP_PAUSE=0"
set "NEXUS_DEV_MODE=0"
set "NEXUS_DOCKER_MODE=0"
set "NEXUS_STOP_MODE=0"
set "NEXUS_SETUP_MODE=0"
set "NEXUS_STATUS_MODE=0"
set "NEXUS_RESET_MODE=0"
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
if /I "%~1"=="--setup" set "NEXUS_SETUP_MODE=1" & shift & goto :parse_args
if /I "%~1"=="--status" set "NEXUS_STATUS_MODE=1" & shift & goto :parse_args
if /I "%~1"=="--reset" set "NEXUS_RESET_MODE=1" & shift & goto :parse_args
if /I "%~1"=="--help" goto :show_help
if /I "%~1"=="-h" goto :show_help
echo [AVISO] Argumento desconhecido: %~1
shift
if "%~1"=="" goto :args_done
goto :parse_args
:args_done

if "%NEXUS_STOP_MODE%"=="1" (
    set "NEXUS_SKIP_PAUSE=1"
    goto :stop_services
)
if "%NEXUS_DOCKER_MODE%"=="1" goto :start_docker
if "%NEXUS_SETUP_MODE%"=="1" goto :setup_only
if "%NEXUS_STATUS_MODE%"=="1" goto :show_status
if "%NEXUS_RESET_MODE%"=="1" goto :reset_all

:main_start

echo =========================================
echo    NEXUS IDE - Iniciando Aplicacao
echo =========================================
echo.
echo [INFO] Log: %NEXUS_LOG%
echo.

echo [%date% %time%] NEXUS IDE Start > "%NEXUS_LOG%"

REM ============================================================================
REM  [1/11] DETETAR PYTHON
REM ============================================================================

echo ===== [1/11] Python =====

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
REM  [2/11] DEPENDENCIAS BACKEND
REM ============================================================================

echo ===== [2/11] Dependencias Backend =====

echo [INFO] A verificar dependencias do backend...
"%PYTHON_EXE%" %PYTHON_ARGS% -c "import fastapi" > NUL 2>&1
if !errorlevel! neq 0 (
    echo [INFO] A instalar dependencias do backend...
    "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r backend\requirements.txt
    if !errorlevel! neq 0 exit /b 1
)
echo [OK] Backend OK.

REM ============================================================================
REM  [3/11] NODE.JS
REM ============================================================================

echo ===== [3/11] Node.js =====

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
REM  [4/11] .ENV
REM ============================================================================

echo ===== [4/11] Configuracao .env =====

if not exist .env (
    echo [INFO] A criar .env a partir de .env.example...
    copy /y .env.example .env > NUL
    echo [AVISO] Edite o .env antes de reiniciar em producao.
)

set "ENV_WARN=0"
findstr /R "^JWT_SECRET=$" .env > NUL 2>&1
if !errorlevel! equ 0 set "ENV_WARN=1"
findstr /R "^JWT_SECRET=change-me$" .env > NUL 2>&1
if !errorlevel! equ 0 set "ENV_WARN=1"
findstr /R "^SECRET_KEY=$" .env > NUL 2>&1
if !errorlevel! equ 0 set "ENV_WARN=1"
findstr /R "^SECRET_KEY=change-me$" .env > NUL 2>&1
if !errorlevel! equ 0 set "ENV_WARN=1"
if "!ENV_WARN!"=="1" (
    echo [WARNING] JWT_SECRET ou SECRET_KEY usam valores placeholder!
    echo [WARNING] Edite o ficheiro .env com chaves seguras antes de producao.
)

REM ============================================================================
REM  [5/11] DOCKER (opcional)
REM ============================================================================

echo ===== [5/11] Docker =====

if "%NEXUS_SKIP_DOCKER%"=="1" goto :docker_done

echo [INFO] A verificar Docker...
docker --version > NUL 2>&1
if !errorlevel! neq 0 (
    echo [AVISO] Docker nao encontrado. Modo sem sandbox Docker.
    set "NEXUS_SKIP_DOCKER=1"
    goto :docker_done
)

if exist "%PROJECT_ROOT%\docker\docker-compose.yml" (
    echo [INFO] A iniciar servicos Docker...
    docker compose -f "%PROJECT_ROOT%\docker\docker-compose.yml" up -d
    if !errorlevel! neq 0 (
        echo [AVISO] docker compose up falhou. A continuar sem Docker.
        set "NEXUS_SKIP_DOCKER=1"
    ) else (
        echo [OK] Docker iniciado.
        timeout /t 3 > NUL 2>&1
        docker exec nexus-redis redis-cli ping > NUL 2>&1
        if !errorlevel! equ 0 (
            echo [OK] Redis a responder.
        ) else (
            echo [AVISO] Redis nao responde ao ping. Container pode estar a inicializar.
        )
    )
) else (
    echo [AVISO] docker\docker-compose.yml nao encontrado. A continuar sem Docker.
    set "NEXUS_SKIP_DOCKER=1"
)

:docker_done

REM ============================================================================
REM  [6/11] OLLAMA (opcional)
REM ============================================================================

echo ===== [6/11] Ollama =====

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
        timeout /t 5 > NUL 2>&1
    )
)

echo [INFO] Modelos Ollama:
ollama list 2> NUL

set "OLLAMA_MODELS=qwen2.5:0.5b qwen2.5:1.5b qwen2.5-coder:1.5b nomic-embed-text"
for %%M in (%OLLAMA_MODELS%) do (
    ollama show %%M > NUL 2>&1
    if !errorlevel! neq 0 (
        echo [INFO] A fazer pull de %%M...
        start "" ollama pull %%M
    )
)

:ollama_done

REM ============================================================================
REM  [7/11] PORTAS
REM ============================================================================

echo ===== [7/11] Verificacao de Portas =====

echo [INFO] A verificar portas 3000 e 8000...
for %%P in (3000 8000) do (
    netstat -ano -p tcp | findstr ":%%P " | findstr "LISTENING" > NUL 2>&1
    if !errorlevel! equ 0 (
        echo [AVISO] Porta %%P em uso. Use: iniciar.bat --parar
    ) else (
        echo [OK] Porta %%P livre.
    )
)

REM ============================================================================
REM  [8/11] BACKEND
REM ============================================================================

echo ===== [8/11] Iniciar Backend =====

echo [INFO] A iniciar Backend (FastAPI)...
start /B "NEXUS-BACKEND" cmd /c "cd /d "%PROJECT_ROOT%" && "%PYTHON_EXE%" %PYTHON_ARGS% run.py > logs\backend.log 2>&1"
timeout /t 3 > NUL 2>&1
echo [OK] Backend iniciado. Log: logs\backend.log

REM ============================================================================
REM  [9/11] FRONTEND
REM ============================================================================

echo ===== [9/11] Iniciar Frontend =====

echo [INFO] A iniciar Frontend (Next.js)...
if not exist "%PROJECT_ROOT%\frontend\node_modules" (
    echo [INFO] A instalar dependencias do frontend...
    pushd "%PROJECT_ROOT%\frontend"
    call npm install
    if !errorlevel! neq 0 exit /b 1
    popd
)

start /B "NEXUS-FRONTEND" cmd /c "cd /d "%PROJECT_ROOT%\frontend" && call npm run dev > ..\logs\frontend.log 2>&1"
timeout /t 3 > NUL 2>&1
echo [OK] Frontend iniciado. Log: logs\frontend.log

REM ============================================================================
REM  [10/11] HEALTHCHECK
REM ============================================================================

echo ===== [10/11] Healthcheck =====

echo [INFO] A aguardar backend...
set "HEALTH_RETRIES=0"
set "HEALTH_TIMEOUT=30"
:healthcheck_loop
set /a HEALTH_RETRIES+=1
curl -s "http://localhost:8000/health" > NUL 2>&1
if !errorlevel! equ 0 goto :healthcheck_ok
"%PYTHON_EXE%" %PYTHON_ARGS% -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" > NUL 2>&1
if !errorlevel! equ 0 goto :healthcheck_ok
if !HEALTH_RETRIES! geq !HEALTH_TIMEOUT! (
    echo [AVISO] Backend nao respondeu apos !HEALTH_TIMEOUT! tentativas. Verifique logs\backend.log
    goto :healthcheck_done
)
timeout /t 2 > NUL 2>&1
goto :healthcheck_loop

:healthcheck_ok
echo [OK] Backend responde em http://localhost:8000/health

:healthcheck_done

REM ============================================================================
REM  [11/11] NAVEGADOR
REM ============================================================================

echo ===== [11/11] Abrir Navegador =====

if "%NEXUS_SKIP_BROWSER%"=="0" (
    echo [INFO] A abrir navegador...
    start http://localhost:3000
)

echo.
echo =========================================
echo    NEXUS IDE - Iniciado!
echo =========================================
echo   IDE:      http://localhost:3000
echo   API:      http://localhost:8000
echo   Docs:     http://localhost:8000/docs
echo   Parar:    iniciar.bat --parar
echo.

if "%NEXUS_SKIP_PAUSE%"=="0" pause
exit /b 0

REM ============================================================================
REM  MODO SETUP (apenas instalar dependencias)
REM ============================================================================

:setup_only
echo =========================================
echo    NEXUS IDE - Modo Setup
echo =========================================
echo.

call :detect_python
if "%PYTHON_EXE%"=="" exit /b 1

echo.
echo [1/3] Backend...
"%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r backend\requirements.txt
if !errorlevel! neq 0 exit /b 1
echo [OK] Backend OK.

echo.
echo [2/3] Frontend...
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
echo [OK] Node.js encontrado.

pushd "%PROJECT_ROOT%\frontend"
call npm install
if !errorlevel! neq 0 exit /b 1
popd
echo [OK] Frontend OK.

echo.
echo [3/3] .env...
if not exist .env (
    copy /y .env.example .env > NUL
    echo [INFO] .env criado a partir de .env.example.
)
echo [OK] .env OK.

echo.
echo =========================================
echo    Setup concluido. Execute iniciar.bat
echo =========================================
echo.
exit /b 0

REM ============================================================================
REM  DETETAR PYTHON (subrotina)
REM ============================================================================

:detect_python
if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
    echo [OK] Python no venv: .venv\Scripts\python.exe
    goto :EOF
)
python -c "import sys; v=sys.version_info; sys.exit(0 if v.major==3 and v.minor>=12 else 1)" > NUL 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_EXE=python"
    echo [OK] Python no PATH
    goto :EOF
)
for %%V in (3.14 3.13 3.12) do (
    py -%%V -c "import sys" > NUL 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-%%V"
        echo [OK] Python via py launcher: %%V
        goto :EOF
    )
)
echo [ERRO] Python 3.12+ nao encontrado.
set "PYTHON_EXE="
goto :EOF

REM ============================================================================
REM  MODO STATUS
REM ============================================================================

:show_status
echo =========================================
echo    NEXUS IDE - Status dos Servicos
echo =========================================
echo.

netstat -ano -p tcp | findstr ":3000 " | findstr "LISTENING" > NUL 2>&1
if !errorlevel! equ 0 (
    echo  [OK] Frontend   : porta 3000 - a correr
) else (
    echo  [--] Frontend   : porta 3000 - parado
)

netstat -ano -p tcp | findstr ":8000 " | findstr "LISTENING" > NUL 2>&1
if !errorlevel! equ 0 (
    echo  [OK] Backend    : porta 8000 - a correr
) else (
    echo  [--] Backend    : porta 8000 - parado
)

docker --version > NUL 2>&1
if !errorlevel! equ 0 (
    docker ps --format "{{.Names}}" 2> NUL | findstr /V "^$" > NUL 2>&1
    if !errorlevel! equ 0 (
        echo  [OK] Docker     : contentores ativos
    ) else (
        echo  [--] Docker     : instalado mas sem contentores ativos
    )
) else (
    echo  [--] Docker     : nao instalado
)

docker exec nexus-redis redis-cli ping > NUL 2>&1
if !errorlevel! equ 0 (
    echo  [OK] Redis      : a responder
) else (
    echo  [--] Redis      : nao disponivel
)

ollama --version > NUL 2>&1
if !errorlevel! equ 0 (
    echo  [OK] Ollama     : instalado
    for %%M in (qwen2.5:0.5b qwen2.5:1.5b qwen2.5-coder:1.5b nomic-embed-text) do (
        ollama show %%M > NUL 2>&1
        if !errorlevel! equ 0 (
            echo               - %%M
        )
    )
) else (
    echo  [--] Ollama     : nao instalado
)

echo.
exit /b 0

REM ============================================================================
REM  MODO RESET
REM ============================================================================

:reset_all

echo ===== Parar servicos =====

docker --version > NUL 2>&1
if !errorlevel! equ 0 (
    if exist "%PROJECT_ROOT%\docker\docker-compose.yml" (
        docker compose -f "%PROJECT_ROOT%\docker\docker-compose.yml" down > NUL 2>&1
        echo [OK] Docker parado.
    )
)
for /f "tokens=5" %%a in ('netstat -ano -p tcp ^| findstr ":3000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F > NUL 2>&1
    echo [OK] Frontend ^(porta 3000^) encerrado.
)
for /f "tokens=5" %%a in ('netstat -ano -p tcp ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F > NUL 2>&1
    echo [OK] Backend ^(porta 8000^) encerrado.
)
echo [OK] Servicos parados.

echo.
echo ===== Limpar diretorios =====

if exist "%PROJECT_ROOT%\frontend\node_modules" (
    rmdir /s /q "%PROJECT_ROOT%\frontend\node_modules"
    echo [OK] node_modules removido.
)
if exist "%PROJECT_ROOT%\.venv" (
    rmdir /s /q "%PROJECT_ROOT%\.venv"
    echo [OK] .venv removido.
)
if exist "%PROJECT_ROOT%\frontend\.next" (
    rmdir /s /q "%PROJECT_ROOT%\frontend\.next"
    echo [OK] .next removido.
)
if exist "%PROJECT_ROOT%\backend\__pycache__" (
    rmdir /s /q "%PROJECT_ROOT%\backend\__pycache__"
    echo [OK] __pycache__ removido.
)

echo.
echo ===== Recriar ambiente =====

echo [INFO] A recriar .venv...
python -m venv "%PROJECT_ROOT%\.venv"
if !errorlevel! neq 0 (
    echo [ERRO] Nao foi possivel criar .venv.
    exit /b 1
)
echo [OK] .venv recriado.

echo [INFO] A instalar dependencias backend...
"%PROJECT_ROOT%\.venv\Scripts\python.exe" -m pip install -r "%PROJECT_ROOT%\backend\requirements.txt"
if !errorlevel! neq 0 exit /b 1
echo [OK] Dependencias backend instaladas.

echo [INFO] A instalar dependencias frontend...
pushd "%PROJECT_ROOT%\frontend"
call npm install
if !errorlevel! neq 0 exit /b 1
popd
echo [OK] Dependencias frontend instaladas.

if not exist "%PROJECT_ROOT%\.env" (
    copy /y "%PROJECT_ROOT%\.env.example" "%PROJECT_ROOT%\.env" > NUL
    echo [OK] .env recriado a partir de .env.example.
)

echo.
echo =========================================
echo    Reset concluido. A iniciar...
echo =========================================
echo.

goto :main_start

REM ============================================================================
REM  MODO DOCKER
REM ============================================================================

:start_docker
echo =========================================
echo    NEXUS IDE - Docker Compose
echo =========================================
docker info > NUL 2>&1
if !errorlevel! neq 0 (
    echo [ERRO] Docker nao acessivel. Ligue o Docker Desktop ou use: iniciar.bat --dev
    exit /b 1
)
if not exist "%PROJECT_ROOT%\docker\docker-compose.yml" (
    echo [ERRO] Ficheiro docker\docker-compose.yml nao encontrado.
    exit /b 1
)
docker compose -f "%PROJECT_ROOT%\docker\docker-compose.yml" up --build -d
if !errorlevel! neq 0 exit /b 1
echo.
echo [OK] Stack Docker iniciada.
echo   IDE:  http://localhost:3000
echo   API:  http://localhost:8000
echo   Parar: iniciar.bat --parar
echo.
if "%NEXUS_SKIP_PAUSE%"=="0" pause
exit /b 0

REM ============================================================================
REM  PARAR SERVICOS
REM ============================================================================

:stop_services
echo =========================================
echo    NEXUS IDE - A Parar
echo =========================================
echo.

docker --version > NUL 2>&1
if !errorlevel! equ 0 (
    if exist "%PROJECT_ROOT%\docker\docker-compose.yml" (
        docker compose -f "%PROJECT_ROOT%\docker\docker-compose.yml" down > NUL 2>&1
        echo [OK] Docker parado.
    )
)

for /f "tokens=5" %%a in ('netstat -ano -p tcp ^| findstr ":3000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F > NUL 2>&1
    echo [OK] Frontend ^(porta 3000^) encerrado.
)
for /f "tokens=5" %%a in ('netstat -ano -p tcp ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F > NUL 2>&1
    echo [OK] Backend ^(porta 8000^) encerrado.
)

echo.
echo [OK] Servicos parados.
if "%NEXUS_SKIP_PAUSE%"=="0" pause
exit /b 0

REM ============================================================================
REM  AJUDA
REM ============================================================================

:show_help
echo =========================================
echo    NEXUS IDE - Ajuda
echo =========================================
echo.
echo Uso: iniciar.bat [opcao]
echo.
echo  Opcao              Descricao
echo  -------            -------------------------------------------
echo  ^(sem opcao^)       Iniciar backend + frontend
echo  --dev              Modo leve (sem Docker nem Ollama)
echo  --docker           Stack completa via Docker Compose
echo  --setup            Apenas instalar dependencias (CI/clean install)
echo  --status           Verificar servicos em execucao e sair
echo  --reset            Parar + limpar node_modules/.venv + reinstalar
echo  --parar, --stop    Parar todos os servicos
echo  --skip-docker      Ignorar Docker durante o arranque
echo  --skip-ollama      Ignorar Ollama durante o arranque
echo  --skip-browser     Nao abrir navegador automaticamente
echo  --verificar        Iniciar sem browser nem pause (CI/testes)
echo  --help, -h         Mostrar esta ajuda
echo.
exit /b 0
