@echo off
echo [INFO] Verificando status Ollama...

REM Verificar se Ollama esta rodando
ollama list > /dev/null 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Ollama nao esta rodando. Iniciando...
    start "" "C:\Ollama\Ollama.exe"
    timeout /t 5 /nobreak > /dev/null
)

echo [INFO] Modelos disponiveis:
ollama list

REM Verificar modelos criticos
echo.
echo [INFO] Verificando modelos essenciais...
echo Modelo: qwen3.5:2b
ollama show qwen3.5:2b 2> /dev/null
if %errorlevel% equ 0 (
    echo   [OK] qwen3.5:2b instalado
) else (
    echo   [INFO] qwen3.5:2b nao instalado, fazendo pull...
    start "" ollama pull qwen3.5:2b
)

echo Modelo: qwen3.5:4b
ollama show qwen3.5:4b 2> /dev/null
if %errorlevel% equ 0 (
    echo   [OK] qwen3.5:4b instalado
) else (
    echo   [INFO] qwen3.5:4b nao instalado, fazendo pull...
    start "" ollama pull qwen3.5:4b
)

echo Modelo: qwen3.5:9b
ollama show qwen3.5:9b 2> /dev/null
if %errorlevel% equ 0 (
    echo   [OK] qwen3.5:9b instalado
) else (
    echo   [INFO] qwen3.5:9b nao instalado, fazendo pull...
    start "" ollama pull qwen3.5:9b
)

echo Modelo: qwen3.5:27b
ollama show qwen3.5:27b 2> /dev/null
if %errorlevel% equ 0 (
    echo   [OK] qwen3.5:27b instalado
) else (
    echo   [INFO] qwen3.5:27b nao instalado, fazendo pull...
    start "" ollama pull qwen3.5:27b
)

echo.
echo [OK] Verificacao concluida!
pause > /dev/null
