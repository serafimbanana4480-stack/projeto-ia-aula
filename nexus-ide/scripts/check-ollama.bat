@echo off
setlocal enabledelayedexpansion
echo ========================================
echo    NEXUS IDE - Ollama Check
echo ========================================
echo.

REM Paths configuraveis via variaveis de ambiente
if not defined OLLAMA_EXE set "OLLAMA_EXE=C:\Ollama\Ollama.exe"

REM Verificar se Ollama esta rodando
ollama list > NUL 2>&1
if !errorlevel! neq 0 (
    echo [INFO] Ollama nao esta rodando. Iniciando...
    if exist "%OLLAMA_EXE%" (
        start "" "%OLLAMA_EXE%"
    ) else (
        echo [AVISO] Ollama.exe nao encontrado em %OLLAMA_EXE%.
        echo         Verifique a instalacao ou defina OLLAMA_EXE para o caminho correto.
    )
    timeout /t 5 /nobreak > NUL
)

echo [INFO] Modelos disponiveis:
ollama list

REM Verificar modelos criticos conforme config/models.yaml
echo.
echo [INFO] Verificando modelos essenciais...

echo Modelo: llama3.1:8b (principal - usado pela maioria dos agentes)
ollama show llama3.1:8b > NUL 2>&1
if !errorlevel! equ 0 (
    echo   [OK] llama3.1:8b instalado
) else (
    echo   [INFO] llama3.1:8b nao instalado, fazendo pull...
    start "" ollama pull llama3.1:8b
)

echo Modelo: nomic-embed-text (embeddings/RAG)
ollama show nomic-embed-text > NUL 2>&1
if !errorlevel! equ 0 (
    echo   [OK] nomic-embed-text instalado
) else (
    echo   [INFO] nomic-embed-text nao instalado, fazendo pull...
    start "" ollama pull nomic-embed-text
)

echo.
echo [AVISO] O projeto NEXUS IDE usa principalmente llama3.1:8b para todos os agentes.
echo          Modelos adicionais podem ser configurados em config/models.yaml.
echo.
echo [OK] Verificacao concluida!
