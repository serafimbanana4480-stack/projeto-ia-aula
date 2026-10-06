@echo off
title NEXUS Terminal
echo ==========================================================
echo   NEXUS Terminal
echo   irmao CLI do NEXUS Dashboard
echo ==========================================================
echo.
echo   O NEXUS Dashboard corre no browser (localhost:3000).
echo   O NEXUS Terminal corre aqui e partilha o mesmo backend.
echo.
echo   A abrir o terminal...
echo ==========================================================
cd /d "%~dp0nexus-ide"
call nexus-terminal.bat %*
