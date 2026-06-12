@echo off
setlocal
cd /d "C:\Users\rodri\Desktop\PROJETO IA AULA GIT CLONE\projeto-ia-aula\nexus-ide"

REM Kill any existing python processes for this project (best effort)
taskkill /F /IM python.exe /FI "WINDOWTITLE eq NEXUS-BACKEND" >nul 2>&1
taskkill /F /IM node.exe /FI "WINDOWTITLE eq NEXUS-FRONTEND" >nul 2>&1

timeout /t 2 /nobreak >nul

REM Start backend
start "NEXUS-BACKEND" /MIN cmd /c "cd /d "%CD%" && .venv\Scripts\python.exe run.py > backend.log 2>&1"

REM Start frontend
start "NEXUS-FRONTEND" /MIN cmd /c "cd /d "%CD%\frontend" && npm run dev > frontend.log 2>&1"

REM Wait for backend health
set RETRIES=0
:health_loop
set /a RETRIES+=1
curl -s http://localhost:8000/health >nul 2>&1
if %errorlevel% equ 0 goto :done
timeout /t 2 /nobreak >nul
if %RETRIES% lss 30 goto :health_loop
:done

echo NEXUS backend and frontend started.
exit /b 0
