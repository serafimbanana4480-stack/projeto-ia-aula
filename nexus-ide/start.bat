@echo off
setlocal enabledelayedexpansion

echo ========================================
echo    NEXUS IDE - Iniciando Aplicacao
echo ========================================
echo.

REM Verificar se Docker esta rodando
docker ps > /dev/null 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Docker nao esta rodando!
    echo Por favor, inicie o Docker Desktop primeiro.
    pause
    exit /b 1
)

REM Verificar configuracao de ambiente
if not exist nexus-ide\.env (
    echo [INFO] Criando arquivo .env...
    copy /y nexus-ide\.env.example nexus-ide\.env > /dev/null
    echo.
    echo Copie o arquivo nexus-ide\.env para editar as variaveis de ambiente.
    echo.
)

REM Iniciar Ollama (se necessario)
echo [INFO] Verificando modelos Ollama...
call nexus-ide\scripts\check-ollama.bat

REM Iniciar servicos Docker
echo [INFO] Iniciando stack Docker...
cd nexus-ide
call docker-compose up -d
cd ..

REM Esperar pelos servicos a iniciarem
echo [INFO] A aguardar inicializacao dos servicos...
timeout /t 30 /nobreak > /dev/null

REM Verificar se tudo esta rodando
echo [INFO] Verificando status dos servicos...
call nexus-ide\scripts\healthcheck.bat

REM Iniciar backend e frontend em background
echo [INFO] Iniciando Backend e Frontend...
start /B cmd /c "cd nexus-ide && call make backend"
start /B cmd /c "cd nexus-ide && call make frontend"

REM Abrir navegador
echo [INFO] Abrindo navegador para http://localhost:3000...
start http://localhost:3000

REM Mostrar mensagens de status
echo.
echo ========================================
echo    NEXUS IDE - Iniciado com Sucesso!
echo ========================================
echo.
echo Servicos em http://localhost:
echo   - IDE:      3000
echo   - API Docs: 8000/docs
echo   - Prometheus:9090
echo   - Dashboard:3000/dashboard
echo.
echo Pressione qualquer tecla para finalizar...
pause > /dev/null
