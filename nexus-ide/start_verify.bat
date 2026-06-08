@echo off
echo [INFO] Modo de verificacao: a iniciar sem browser e sem pause.
setlocal
set "NEXUS_SKIP_BROWSER=1"
set "NEXUS_SKIP_PAUSE=1"
call "%~dp0start.bat"
