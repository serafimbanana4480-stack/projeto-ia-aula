@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

cd /d "%~dp0"
set "PROJECT_ROOT=%CD%"
set "STOP_LOG=%PROJECT_ROOT%\stop.log"

REM --- Parse argumentos ---
:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--force" set "FORCE_MODE=1" & shift & goto :parse_args
if /I "%~1"=="--help" goto :show_help
if /I "%~1"=="-h" goto :show_help
echo [AVISO] Argumento desconhecido: %~1
shift
goto :parse_args
:args_done

echo ========================================
echo    NEXUS IDE - Parando Aplicacao
echo ========================================
echo.

REM --- Iniciar log ---
echo [%date% %time%] NEXUS IDE Stop > "%STOP_LOG%"

REM ============================================================================
REM 1. PARAR SERVICOS DOCKER
REM ============================================================================

echo [INFO] A verificar Docker...
echo [%date% %time%] Verificando Docker... >> "%STOP_LOG%"

docker --version > NUL 2>&1
if !errorlevel! equ 0 (
    if exist "docker\docker-compose.yml" (
        echo [INFO] A parar servicos Docker...
        call docker compose -f "docker\docker-compose.yml" down
        if !errorlevel! equ 0 (
            echo [OK] Servicos Docker parados.
            echo [%date% %time%] Docker services stopped >> "%STOP_LOG%"
        ) else (
            echo [AVISO] docker compose down falhou.
            echo [%date% %time%] AVISO: docker compose down falhou >> "%STOP_LOG%"
        )
    ) else (
        echo [INFO] docker-compose.yml nao encontrado.
    )
) else (
    echo [INFO] Docker nao encontrado.
    echo [%date% %time%] Docker nao encontrado >> "%STOP_LOG%"
)
echo.

REM ============================================================================
REM 2. PARAR PROCESSOS NAS PORTAS
REM ============================================================================

echo [INFO] A procurar processos nas portas 3000 e 8000...
echo [%date% %time%] Procurando processos... >> "%STOP_LOG%"

set "FOUND=0"

REM Metodo 1: netstat para encontrar PIDs nas portas especificas
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000 " ^| findstr "LISTENING"') do (
    echo [INFO] A encerrar processo frontend ^(PID: %%a^) na porta 3000...
    taskkill /PID %%a /F > NUL 2>&1
    if !errorlevel! equ 0 (
        echo [OK] Frontend ^(PID: %%a^) encerrado.
        set "FOUND=1"
    ) else (
        echo [AVISO] Falha ao encerrar frontend ^(PID: %%a^).
    )
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo [INFO] A encerrar processo backend ^(PID: %%a^) na porta 8000...
    taskkill /PID %%a /F > NUL 2>&1
    if !errorlevel! equ 0 (
        echo [OK] Backend ^(PID: %%a^) encerrado.
        set "FOUND=1"
    ) else (
        echo [AVISO] Falha ao encerrar backend ^(PID: %%a^).
    )
)

REM ============================================================================
REM 3. PARAR PROCESSOS DO PROJETO (wmic)
REM ============================================================================

echo [INFO] A procurar processos Python/Node no diretorio do projeto...

for /f "skip=1 tokens=2 delims=," %%p in ('wmic process where "name='python.exe'" get ProcessId^,ExecutablePath /format:csv 2^>NUL ^| findstr /I /C:"nexus-ide"') do (
    echo [INFO] A encerrar processo Python do NEXUS ^(PID: %%p^)...
    taskkill /PID %%p /F > NUL 2>&1
    if !errorlevel! equ 0 (
        echo [OK] Python ^(PID: %%p^) encerrado.
        set "FOUND=1"
    )
)

for /f "skip=1 tokens=2 delims=," %%p in ('wmic process where "name='node.exe'" get ProcessId^,ExecutablePath /format:csv 2^>NUL ^| findstr /I /C:"nexus-ide"') do (
    echo [INFO] A encerrar processo Node do NEXUS ^(PID: %%p^)...
    taskkill /PID %%p /F > NUL 2>&1
    if !errorlevel! equ 0 (
        echo [OK] Node ^(PID: %%p^) encerrado.
        set "FOUND=1"
    )
)

REM ============================================================================
REM 4. MODO FORCE (matar todos os python/node do projeto)
REM ============================================================================

if "%FORCE_MODE%"=="1" (
    echo [INFO] Modo FORCE ativo. A procurar todos os processos relacionados...
    for /f "skip=1 tokens=2 delims=," %%p in ('wmic process where "name='python.exe'" get ProcessId^,ExecutablePath /format:csv 2^>NUL ^| findstr /I /C:"nexus-ide"') do (
        taskkill /PID %%p /F > NUL 2>&1
    )
    for /f "skip=1 tokens=2 delims=," %%p in ('wmic process where "name='node.exe'" get ProcessId^,ExecutablePath /format:csv 2^>NUL ^| findstr /I /C:"nexus-ide"') do (
        taskkill /PID %%p /F > NUL 2>&1
    )
    echo [OK] Modo FORCE concluido.
)

REM ============================================================================
REM 5. VERIFICACAO FINAL
REM ============================================================================

echo.
if "%FOUND%"=="1" (
    echo [OK] Processos encerrados.
    echo [%date% %time%] Processos encerrados >> "%STOP_LOG%"
) else (
    echo [INFO] Nenhum processo do NEXUS IDE encontrado.
    echo [%date% %time%] Nenhum processo encontrado >> "%STOP_LOG%"
)

echo.
echo ========================================
echo    NEXUS IDE - Parado com Sucesso!
echo ========================================
echo.
echo Log: %STOP_LOG%
echo.

if not defined NEXUS_SKIP_PAUSE (
    pause
)

exit /b 0

REM ============================================================================
REM HELP
REM ============================================================================
:show_help
echo Uso: stop.bat [opcoes]
echo.
echo Opcoes:
echo   --force    Forcar encerramento de todos os processos do projeto
echo   --help, -h Mostrar esta ajuda
echo.
exit /b 0
