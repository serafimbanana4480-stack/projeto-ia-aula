@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

REM ============================================================================
REM NEXUS IDE - Start Script (Windows)
REM ============================================================================
REM Melhorias:
REM   - Detecao automatica do Python do venv (.venv\Scripts\python.exe)
REM   - Verificacao de pre-requisitos antes de continuar
REM   - Melhor logging com timestamps
REM   - Opcao de skip Docker/Ollama (modo dev leve)
REM   - Verificacao de portas livres
REM   - Error handling robusto
REM   - Suporte a Python 3.12, 3.13, 3.14
REM ============================================================================

cd /d "%~dp0"
set "PROJECT_ROOT=%CD%"

REM --- Variaveis de controlo ---
set "NEXUS_LOG=%PROJECT_ROOT%\start.log"
set "NEXUS_SKIP_DOCKER=0"
set "NEXUS_SKIP_OLLAMA=0"
set "NEXUS_SKIP_BROWSER=0"
set "NEXUS_DEV_MODE=0"
set "PYTHON_EXE="
set "PYTHON_ARGS="

REM --- Parse argumentos ---
:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--skip-docker" set "NEXUS_SKIP_DOCKER=1" & shift & goto :parse_args
if /I "%~1"=="--skip-ollama" set "NEXUS_SKIP_OLLAMA=1" & shift & goto :parse_args
if /I "%~1"=="--skip-browser" set "NEXUS_SKIP_BROWSER=1" & shift & goto :parse_args
if /I "%~1"=="--dev" set "NEXUS_DEV_MODE=1" & set "NEXUS_SKIP_DOCKER=1" & shift & goto :parse_args
if /I "%~1"=="--help" goto :show_help
if /I "%~1"=="-h" goto :show_help
echo [AVISO] Argumento desconhecido: %~1
shift
goto :parse_args
:args_done

echo ========================================
echo    NEXUS IDE - Iniciando Aplicacao
echo ========================================
echo.
echo [INFO] Log: %NEXUS_LOG%
echo [INFO] Modo: %NEXUS_DEV_MODE%
echo.

REM --- Iniciar log ---
echo [%date% %time%] NEXUS IDE Start > "%NEXUS_LOG%"
echo [%date% %time%] PROJECT_ROOT=%PROJECT_ROOT% >> "%NEXUS_LOG%"
echo [%date% %time%] SKIP_DOCKER=%NEXUS_SKIP_DOCKER% >> "%NEXUS_LOG%"
echo [%date% %time%] SKIP_OLLAMA=%NEXUS_SKIP_OLLAMA% >> "%NEXUS_LOG%"
echo [%date% %time%] DEV_MODE=%NEXUS_DEV_MODE% >> "%NEXUS_LOG%"

REM ============================================================================
REM 1. DETETAR PYTHON (prioridade: venv > python > py)
REM ============================================================================

echo [INFO] A detetar Python...
echo [%date% %time%] Detetando Python... >> "%NEXUS_LOG%"

REM 1.1 Tentar venv primeiro
if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
    echo [OK] Python detetado no venv: .venv\Scripts\python.exe
    echo [%date% %time%] Python venv detetado >> "%NEXUS_LOG%"
    goto :python_done
)

REM 1.2 Tentar 'python' no PATH
python -c "import sys; v=sys.version_info; sys.exit(0 if v.major==3 and v.minor>=12 else 1)" > NUL 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_EXE=python"
    echo [OK] Python detetado no PATH
    echo [%date% %time%] Python PATH detetado >> "%NEXUS_LOG%"
    goto :python_done
)

REM 1.3 Tentar 'py' launcher
for %%V in (3.14 3.13 3.12) do (
    py -%%V -c "import sys" > NUL 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-%%V"
        echo [OK] Python detetado via py launcher: %%V
        echo [%date% %time%] Python py -%%V detetado >> "%NEXUS_LOG%"
        goto :python_done
    )
)

echo [ERRO] Python 3.12+ nao encontrado.
echo        Instale Python ou crie um venv: python -m venv .venv
echo [%date% %time%] ERRO: Python nao encontrado >> "%NEXUS_LOG%"
exit /b 1

:python_done
echo [INFO] Usando: %PYTHON_EXE% %PYTHON_ARGS%
echo [%date% %time%] PYTHON_EXE=%PYTHON_EXE% >> "%NEXUS_LOG%"
echo.

REM ============================================================================
REM 2. VERIFICAR DEPENDENCIAS DO BACKEND
REM ============================================================================

echo [INFO] A verificar dependencias do backend...
echo [%date% %time%] Verificando dependencias backend... >> "%NEXUS_LOG%"

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import fastapi" > NUL 2>&1
if !errorlevel! neq 0 (
    echo [INFO] A instalar dependencias do backend...
    "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r backend\requirements.txt
    if !errorlevel! neq 0 (
        echo [ERRO] Falha ao instalar dependencias do backend.
        echo [%date% %time%] ERRO: pip install falhou >> "%NEXUS_LOG%"
        exit /b 1
    )
)
echo [OK] Dependencias do backend OK.
echo.

REM ============================================================================
REM 3. VERIFICAR NODE.JS E NPM
REM ============================================================================

echo [INFO] A verificar Node.js...
echo [%date% %time%] Verificando Node.js... >> "%NEXUS_LOG%"

node --version > NUL 2>&1
if !errorlevel! neq 0 (
    echo [ERRO] Node.js nao encontrado. Instale Node.js 20+.
    echo [%date% %time%] ERRO: Node.js nao encontrado >> "%NEXUS_LOG%"
    exit /b 1
)
echo [OK] Node.js encontrado.

call npm --version > NUL 2>&1
if !errorlevel! neq 0 (
    echo [ERRO] npm nao encontrado.
    echo [%date% %time%] ERRO: npm nao encontrado >> "%NEXUS_LOG%"
    exit /b 1
)
echo [OK] npm encontrado.
echo.

REM ============================================================================
REM 4. VERIFICAR .env
REM ============================================================================

echo [INFO] A verificar .env...

if not exist .env (
    echo [INFO] Criando .env a partir de .env.example...
    copy /y .env.example .env > NUL
    echo [AVISO] Edite o .env com as tuas configuracoes antes de reiniciar.
    echo [%date% %time%] .env criado de .env.example >> "%NEXUS_LOG%"
) else (
    echo [OK] .env encontrado.
)
echo.

REM ============================================================================
REM 5. DOCKER (opcional)
REM ============================================================================

if "%NEXUS_SKIP_DOCKER%"=="1" (
    echo [INFO] Docker ignorado ^(--skip-docker ou --dev^).
    echo [%date% %time%] Docker skipped >> "%NEXUS_LOG%"
    goto :docker_done
)

echo [INFO] A verificar Docker...
echo [%date% %time%] Verificando Docker... >> "%NEXUS_LOG%"

docker --version > NUL 2>&1
if !errorlevel! neq 0 (
    echo [AVISO] Docker nao encontrado. A iniciar em modo sem Docker ^(--dev^).
    echo         Instale Docker Desktop para sandbox completo.
    set "NEXUS_SKIP_DOCKER=1"
    echo [%date% %time%] AVISO: Docker nao encontrado, modo dev >> "%NEXUS_LOG%"
    goto :docker_done
)

for /f "tokens=*" %%a in ('docker --version') do set "DOCKER_VERSION=%%a"
echo [OK] %DOCKER_VERSION%

REM Verificar se Docker engine responde
docker info > NUL 2>&1
if !errorlevel! neq 0 (
    echo [INFO] A iniciar Docker Desktop...
    set "DOCKER_DESKTOP_EXE=C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if exist "!DOCKER_DESKTOP_EXE!" (
        start "" "!DOCKER_DESKTOP_EXE!"
        echo [INFO] Aguardando Docker Desktop (ate 60s)...
        set "DOCKER_WAIT=0"
        :docker_wait_loop
        timeout /t 3 /nobreak > NUL
        docker info > NUL 2>&1
        if !errorlevel! equ 0 goto :docker_ready
        set /a DOCKER_WAIT+=1
        if !DOCKER_WAIT! geq 20 (
            echo [AVISO] Docker nao ficou pronto. A continuar sem Docker.
            set "NEXUS_SKIP_DOCKER=1"
            echo [%date% %time%] AVISO: Docker timeout, modo dev >> "%NEXUS_LOG%"
            goto :docker_done
        )
        goto :docker_wait_loop
    ) else (
        echo [AVISO] Docker Desktop nao encontrado. A continuar sem Docker.
        set "NEXUS_SKIP_DOCKER=1"
        echo [%date% %time%] AVISO: Docker Desktop nao encontrado >> "%NEXUS_LOG%"
        goto :docker_done
    )
)

:docker_ready
echo [OK] Docker engine pronto.

REM Iniciar servicos Docker se docker-compose.yml existir
if exist "docker\docker-compose.yml" (
    echo [INFO] A iniciar servicos Docker...
    docker compose -f "docker\docker-compose.yml" up -d
    if !errorlevel! neq 0 (
        echo [AVISO] docker compose up falhou. A continuar...
        echo [%date% %time%] AVISO: docker compose up falhou >> "%NEXUS_LOG%"
    ) else (
        echo [OK] Servicos Docker iniciados.
        echo [%date% %time%] Docker services started >> "%NEXUS_LOG%"
    )
) else (
    echo [AVISO] docker-compose.yml nao encontrado.
)

:docker_done
echo.

REM ============================================================================
REM 6. OLLAMA (opcional)
REM ============================================================================

if "%NEXUS_SKIP_OLLAMA%"=="1" (
    echo [INFO] Ollama ignorado ^(--skip-ollama^).
    echo [%date% %time%] Ollama skipped >> "%NEXUS_LOG%"
    goto :ollama_done
)

echo [INFO] A verificar Ollama...
echo [%date% %time%] Verificando Ollama... >> "%NEXUS_LOG%"

ollama --version > NUL 2>&1
if !errorlevel! neq 0 (
    echo [AVISO] Ollama nao encontrado. A continuar sem modelos locais.
    echo         Instale Ollama em https://ollama.com
    set "NEXUS_SKIP_OLLAMA=1"
    echo [%date% %time%] AVISO: Ollama nao encontrado >> "%NEXUS_LOG%"
    goto :ollama_done
)

echo [OK] Ollama encontrado.

REM Verificar se Ollama responde
ollama list > NUL 2>&1
if !errorlevel! neq 0 (
    echo [INFO] A iniciar Ollama...
    set "OLLAMA_EXE=C:\Ollama\Ollama.exe"
    if exist "!OLLAMA_EXE!" (
        start "" "!OLLAMA_EXE!"
        timeout /t 5 /nobreak > NUL
    ) else (
        echo [AVISO] Ollama.exe nao encontrado.
    )
)

REM Verificar modelos essenciais
if exist "scripts\check-ollama.bat" (
    call scripts\check-ollama.bat
) else (
    echo [AVISO] scripts\check-ollama.bat nao encontrado.
)

:ollama_done
echo.

REM ============================================================================
REM 7. VERIFICAR PORTAS
REM ============================================================================

echo [INFO] A verificar portas...
echo [%date% %time%] Verificando portas... >> "%NEXUS_LOG%"

for %%P in (3000 8000 9090) do (
    netstat -ano | findstr ":%%P " | findstr "LISTENING" > NUL 2>&1
    if !errorlevel! equ 0 (
        echo [AVISO] Porta %%P ja esta em uso.
        for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%P " ^| findstr "LISTENING"') do (
            echo         PID: %%a
        )
    ) else (
        echo [OK] Porta %%P livre.
    )
)
echo.

REM ============================================================================
REM 8. INICIAR BACKEND
REM ============================================================================

echo [INFO] A iniciar Backend (FastAPI)...
echo [%date% %time%] Iniciando backend... >> "%NEXUS_LOG%"

REM Verificar se backend ja esta a correr
tasklist /FI "IMAGENAME eq python.exe" 2>NUL | findstr /I "run.py" > NUL 2>&1
if !errorlevel! equ 0 (
    echo [AVISO] Backend ja parece estar a correr.
    echo         Use stop.bat primeiro se quiser reiniciar.
)

start /B "NEXUS-BACKEND" cmd /c "cd /d "%PROJECT_ROOT%" && "%PYTHON_EXE%" %PYTHON_ARGS% run.py > backend.log 2>&1"
REM Nota: start /B errorlevel nao e fiavel; healthcheck verifica se subiu
timeout /t 3 /nobreak > NUL 2>&1
echo [OK] Backend iniciado (PID ver tasklist).
echo [INFO] Log: backend.log
echo.

REM ============================================================================
REM 9. INICIAR FRONTEND
REM ============================================================================

echo [INFO] A iniciar Frontend (Next.js)...
echo [%date% %time%] Iniciando frontend... >> "%NEXUS_LOG%"

if not exist "%PROJECT_ROOT%\frontend\node_modules\.bin\next" (
    echo [INFO] A instalar dependencias do frontend...
    cd /d "%PROJECT_ROOT%\frontend"
    call npm install
    if !errorlevel! neq 0 (
        echo [ERRO] npm install falhou.
        echo [%date% %time%] ERRO: npm install falhou >> "%NEXUS_LOG%"
        exit /b 1
    )
    cd /d "%PROJECT_ROOT%"
)

start /B "NEXUS-FRONTEND" cmd /c "cd /d "%PROJECT_ROOT%\frontend" && call npm run dev > frontend.log 2>&1"
REM Nota: start /B errorlevel nao e fiavel; verificar via healthcheck
timeout /t 3 /nobreak > NUL 2>&1
echo [OK] Frontend iniciado.
echo [INFO] Log: frontend\frontend.log
echo.

REM ============================================================================
REM 10. HEALTHCHECK
REM ============================================================================

echo [INFO] A aguardar backend ficar pronto...
echo [%date% %time%] Healthcheck iniciado... >> "%NEXUS_LOG%"

set "HEALTH_RETRIES=0"
set "HEALTH_MAX=30"

:healthcheck_loop
set /a HEALTH_RETRIES+=1

REM Tentar curl primeiro, depois fallback para python
curl -s "http://localhost:8000/health" > NUL 2>&1
if !errorlevel! equ 0 (
    echo [OK] Backend respondeu em http://localhost:8000/health
    echo [%date% %time%] Healthcheck OK >> "%NEXUS_LOG%"
    goto :healthcheck_done
)

REM Fallback: usar python para healthcheck
"%PYTHON_EXE%" %PYTHON_ARGS% -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" > NUL 2>&1
if !errorlevel! equ 0 (
    echo [OK] Backend respondeu (via Python).
    echo [%date% %time%] Healthcheck OK (Python) >> "%NEXUS_LOG%"
    goto :healthcheck_done
)

if !HEALTH_RETRIES! geq !HEALTH_MAX! (
    echo [AVISO] Backend nao respondeu apos %HEALTH_MAX% tentativas.
    echo         Verifique backend.log para erros.
    echo [%date% %time%] AVISO: Healthcheck timeout >> "%NEXUS_LOG%"
    goto :healthcheck_done
)

timeout /t 2 /nobreak > NUL
goto :healthcheck_loop

:healthcheck_done
echo.

REM ============================================================================
REM 11. ABRIR NAVEGADOR
REM ============================================================================

if "%NEXUS_SKIP_BROWSER%"=="1" (
    echo [INFO] Browser ignorado ^(--skip-browser^).
) else (
    echo [INFO] A abrir navegador...
    start http://localhost:3000
)
echo.

REM ============================================================================
REM 12. STATUS FINAL
REM ============================================================================

echo ========================================
echo    NEXUS IDE - Iniciado!
echo ========================================
echo.
echo Servicos:
echo   - IDE:        http://localhost:3000
echo   - API:        http://localhost:8000
echo   - API Docs:   http://localhost:8000/docs
echo   - Health:     http://localhost:8000/health
echo   - Prometheus: http://localhost:9090 (se Docker ativo)
echo.
echo Logs:
echo   - Geral:      %NEXUS_LOG%
echo   - Backend:    backend.log
echo   - Frontend:   frontend\frontend.log
echo.
echo Comandos:
echo   - stop.bat    - Parar todos os servicos
echo   - start.bat   - Reiniciar
echo.

if "%NEXUS_SKIP_DOCKER%"=="1" (
    echo [AVISO] Modo sem Docker ativo. Sandbox de codigo limitado.
)
if "%NEXUS_SKIP_OLLAMA%"=="1" (
    echo [AVISO] Modo sem Ollama ativo. Modelos locais nao disponiveis.
)

echo [%date% %time%] NEXUS IDE iniciado com sucesso >> "%NEXUS_LOG%"

if not defined NEXUS_SKIP_PAUSE (
    echo.
    pause
)

exit /b 0

REM ============================================================================
REM HELP
REM ============================================================================
:show_help
echo Uso: start.bat [opcoes]
echo.
echo Opcoes:
echo   --dev           Modo desenvolvimento (ignora Docker e Ollama)
echo   --skip-docker   Ignorar Docker
echo   --skip-ollama   Ignorar Ollama
echo   --skip-browser  Nao abrir navegador
echo   --help, -h      Mostrar esta ajuda
echo.
echo Exemplos:
echo   start.bat                    Iniciar completo
echo   start.bat --dev              Iniciar sem Docker/Ollama
echo   start.bat --skip-browser     Iniciar sem abrir navegador
echo.
exit /b 0
