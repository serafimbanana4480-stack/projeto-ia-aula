@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ========================================
echo    NEXUS IDE - Parando Aplicacao
echo ========================================
echo.

REM Paths configuraveis via variaveis de ambiente
if not defined DOCKER_COMPOSE_FILE set "DOCKER_COMPOSE_FILE=docker\docker-compose.yml"
if not defined NEXUS_FRONTEND_PORT set "NEXUS_FRONTEND_PORT=3000"
if not defined NEXUS_BACKEND_PORT set "NEXUS_BACKEND_PORT=8000"

REM Parar servicos Docker (SEM -v para preservar volumes/dados)
echo [INFO] Parando servicos Docker...
docker compose -f "%DOCKER_COMPOSE_FILE%" down

REM Parar apenas processos especificos do NEXUS IDE
REM Procura por portas configuradas (frontend e backend)
echo [INFO] Procurando processos do NEXUS IDE nas portas %NEXUS_FRONTEND_PORT% e %NEXUS_BACKEND_PORT%...

REM Metodo 1: netstat para encontrar PIDs nas portas especificas
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%NEXUS_FRONTEND_PORT%" ^| findstr "LISTENING"') do (
    echo [INFO] Encerrando processo frontend (PID: %%a) na porta %NEXUS_FRONTEND_PORT%...
    taskkill /PID %%a /F > NUL 2>&1
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%NEXUS_BACKEND_PORT%" ^| findstr "LISTENING"') do (
    echo [INFO] Encerrando processo backend (PID: %%a) na porta %NEXUS_BACKEND_PORT%...
    taskkill /PID %%a /F > NUL 2>&1
)

REM Metodo 2: wmic para filtrar por ExecutablePath no diretorio do projeto
for /f "skip=1 tokens=2 delims=," %%p in ('wmic process where "name='python.exe'" get ProcessId^,ExecutablePath /format:csv 2^>NUL ^| findstr /I /C:"nexus-ide"') do (
    echo [INFO] Encerrando processo Python do NEXUS (PID: %%p)...
    taskkill /PID %%p /F > NUL 2>&1
)

for /f "skip=1 tokens=2 delims=," %%p in ('wmic process where "name='node.exe'" get ProcessId^,ExecutablePath /format:csv 2^>NUL ^| findstr /I /C:"nexus-ide"') do (
    echo [INFO] Encerrando processo Node do NEXUS (PID: %%p)...
    taskkill /PID %%p /F > NUL 2>&1
)

REM Metodo 3: PowerShell fallback para kill cirurgico (se wmic falhar)
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {$_.ExecutablePath -like '*nexus-ide*'} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" > NUL 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Where-Object {$_.ExecutablePath -like '*nexus-ide*'} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" > NUL 2>&1

echo [INFO] Limpeza concluida.
echo.
echo ========================================
echo    NEXUS IDE - Parado com Sucesso!
echo ========================================
echo.
pause
