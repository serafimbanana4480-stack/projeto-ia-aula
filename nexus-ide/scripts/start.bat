@echo off
setlocal

rem ============================================================
rem  NEXUS IDE - start.bat
rem  Inicia o backend (FastAPI/uvicorn) e o frontend (Next.js)
rem  cada um na sua propria janela de consola.
rem ============================================================

set "ROOT=%~dp0.."
set "VENV_PY=%ROOT%\.venv\Scripts\python.exe"
set "FALLBACK_PY=C:\Users\rodri\AppData\Local\Programs\Python\Python312\python.exe"

if exist "%VENV_PY%" (
    set "PYEXE=%VENV_PY%"
) else if exist "%FALLBACK_PY%" (
    set "PYEXE=%FALLBACK_PY%"
) else (
    set "PYEXE=python"
)

echo ============================================================
echo  NEXUS IDE - a iniciar backend + frontend
echo  Root:   %ROOT%
echo  Python: %PYEXE%
echo ============================================================
echo.

if not exist "%ROOT%\frontend\node_modules" (
    echo [AVISO] node_modules nao encontrado em frontend\. A instalar dependencias...
    pushd "%ROOT%\frontend"
    call npm install
    popd
)

echo A abrir janela do backend...
start "NEXUS Backend" cmd /k "cd /d "%ROOT%" && "%PYEXE%" -m backend.orchestrator.main"

echo A aguardar alguns segundos antes de arrancar o frontend...
timeout /t 3 /nobreak >nul

echo A abrir janela do frontend...
start "NEXUS Frontend" cmd /k "cd /d "%ROOT%\frontend" && npm run dev"

echo.
echo ============================================================
echo  Backend  -^> http://localhost:8000
echo  Frontend -^> http://localhost:3000
echo.
echo  Cada servico corre na sua propria janela.
echo  Fecha essas janelas (ou Ctrl+C dentro delas) para parar.
echo ============================================================

endlocal
