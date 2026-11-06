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

where pnpm >nul 2>&1
if errorlevel 1 (
    echo [ERRO] pnpm 10.34.9 nao encontrado. Instala essa versao antes de arrancar.
    exit /b 1
)
for /f %%v in ('pnpm --version') do set "PNPM_VERSION=%%v"
if not "%PNPM_VERSION%"=="10.34.9" (
    echo [ERRO] Esta IDE requer pnpm 10.34.9; encontrado: %PNPM_VERSION%.
    exit /b 1
)

if not exist "%ROOT%\frontend\node_modules" (
    echo [AVISO] node_modules nao encontrado em frontend\. A instalar dependencias...
    pushd "%ROOT%\frontend"
    call pnpm install --frozen-lockfile
    if errorlevel 1 (
        popd
        exit /b 1
    )
    popd
)

echo A abrir janela do backend...
start "NEXUS Backend" cmd /k "cd /d "%ROOT%" && "%PYEXE%" -m backend.orchestrator.main"

echo A aguardar alguns segundos antes de arrancar o frontend...
timeout /t 3 /nobreak >nul

echo A abrir janela do frontend...
start "NEXUS Frontend" cmd /k "cd /d "%ROOT%\frontend" && pnpm run dev"

echo.
echo ============================================================
echo  Backend  -^> http://localhost:8000
echo  Frontend -^> http://localhost:3000
echo.
echo  Cada servico corre na sua propria janela.
echo  Fecha essas janelas (ou Ctrl+C dentro delas) para parar.
echo ============================================================

endlocal
