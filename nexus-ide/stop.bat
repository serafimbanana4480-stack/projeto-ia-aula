@echo off
setlocal enabledelayedexpansion

echo ========================================
echo    NEXUS IDE - Parando Aplicacao
echo ========================================
echo.

echo [INFO] Parando servicos Docker...
call cd nexus-ide && call docker-compose down
cd ..

echo [INFO] Parando processos em background...
taskkill /F /IM uvicorn.exe > /dev/null 2>&1
taskkill /F /IM node.exe > /dev/null 2>&1

echo [INFO] Limpeando temporarios...
call cd nexus-ide && call make clean
cd ..

echo.
echo ========================================
echo    NEXUS IDE - Parado com Sucesso!
echo ========================================
echo.
echo Pressione qualquer tecla para continuar...
pause > /dev/null
