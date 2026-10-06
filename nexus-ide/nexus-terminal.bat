@echo off
REM ─────────────────────────────────────────────────────────────────────
REM  NEXUS Terminal — irmão CLI do NEXUS Dashboard
REM
REM  O Dashboard corre no browser (localhost:3000).
REM  O Terminal corre aqui e partilha o mesmo backend, modelos e memória.
REM ─────────────────────────────────────────────────────────────────────
setlocal
set IDE=%~dp0
cd /d "%IDE%"

if not exist "%IDE%\.venv\Scripts\python.exe" (
    echo ERRO: falta %IDE%\.venv
    echo Cria com:  cd /d %IDE% ^&^& python -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -e .
    exit /b 1
)

if not defined NEXUS_DEFAULT_PASSWORD for /f "delims=" %%i in ('powershell -NoProfile -Command "-join ((65..90)+(97..122)+(48..57) | Get-Random -Count 16 | ForEach-Object {[char]$_})"') do set NEXUS_DEFAULT_PASSWORD=%%i
if not defined NEXUS_PASSWORD set NEXUS_PASSWORD=%NEXUS_DEFAULT_PASSWORD%
if not defined NEXUS_EMAIL set NEXUS_EMAIL=admin@nexus-ide.com

.venv\Scripts\python.exe scripts\nexus_terminal.py %*
