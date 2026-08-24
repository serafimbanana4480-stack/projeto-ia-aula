@echo off
title NEXUS IDE - arranque
set RAIZ=C:\Users\rodri\Desktop\nexus
set IDE=%RAIZ%\nexus-ide

echo ==========================================================
echo   NEXUS IDE - arranque
echo ==========================================================
echo.

echo [1/6] Manutencao do git (uma vez, rapido)...
cd /d "%RAIZ%"
if exist ".git\index.lock" del /f /q ".git\index.lock"
if exist ".git\HEAD.lock" del /f /q ".git\HEAD.lock"
git worktree prune >nul 2>&1
git branch -D accidental-rubidium >nul 2>&1
git branch -D modest-auroraceratops >nul 2>&1
git gc --prune=now --quiet >nul 2>&1
for /f %%b in ('git rev-parse --abbrev-ref HEAD') do echo       branch: %%b
echo.

echo [2/6] Limpar bytecode obsoleto e verificar ambiente...
cd /d "%IDE%\backend"
for /d /r %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" >nul 2>&1
cd /d "%IDE%"
if not exist "%IDE%\.venv\Scripts\python.exe" goto sem_venv
if not exist "%IDE%\frontend\node_modules" goto sem_node
if not exist "%IDE%\.env" goto sem_env
echo       .venv OK / node_modules OK / .env OK
echo.

echo [3/6] Libertar portas 8000 e 3000 se estiverem ocupadas...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do taskkill /F /PID %%p >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":3000 .*LISTENING"') do taskkill /F /PID %%p >nul 2>&1
echo       ok
echo.

echo [4/6] Arrancar o backend (127.0.0.1:8000)...
start "NEXUS Backend" cmd /k "cd /d %IDE% && .venv\Scripts\python.exe -m uvicorn backend.orchestrator.main:app --host 127.0.0.1 --port 8000"
echo       a aguardar que o backend responda...
set /a tent=0
:esperar
set /a tent+=1
timeout /t 3 /nobreak >nul
curl -s -o nul -w "" http://127.0.0.1:8000/health >nul 2>&1
if not errorlevel 1 goto backend_ok
if %tent% GEQ 20 goto backend_lento
goto esperar
:backend_ok
echo       backend a responder em http://127.0.0.1:8000/health
goto seguir
:backend_lento
echo       backend ainda nao respondeu (ve a janela "NEXUS Backend")
:seguir
echo.

echo [5/6] Arrancar o frontend (localhost:3000)...
start "NEXUS Frontend" cmd /k "cd /d %IDE%\frontend && npm run dev"
timeout /t 15 /nobreak >nul
echo       ok
echo.

echo [6/6] Abrir o browser...
start "" "http://localhost:3000"
echo.
echo ==========================================================
echo   NEXUS a correr.
echo     backend  -> http://127.0.0.1:8000  (janela "NEXUS Backend")
echo     frontend -> http://localhost:3000  (janela "NEXUS Frontend")
echo   Para parar: fecha as duas janelas.
echo ==========================================================
pause
exit /b 0

:sem_venv
echo   ERRO: falta %IDE%\.venv
echo   Corre:  cd /d %IDE% ^&^& python -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -e .
pause
exit /b 1

:sem_node
echo   ERRO: falta %IDE%\frontend\node_modules
echo   Corre:  cd /d %IDE%\frontend ^&^& npm install
pause
exit /b 1

:sem_env
echo   ERRO: falta %IDE%\.env  (copia de .env.example e poe as chaves)
pause
exit /b 1
