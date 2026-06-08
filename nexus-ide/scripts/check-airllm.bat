@echo off
REM NEXUS / LUSO AI — airllm model checker
REM Verifies that the required HuggingFace models are present in the
REM local cache (~/.cache/huggingface/hub). Triggers a download via
REM scripts/install-models.py if anything is missing.

setlocal enabledelayedexpansion

echo ========================================
echo    NEXUS IDE - airllm Model Check
echo ========================================
echo.

set "PYTHON_EXE="
set "PYTHON_ARGS="
python -c "import sys; v=sys.version_info; sys.exit(0 if v.major==3 and v.minor in (12,13) else 1)" > NUL 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_EXE=python"
) else (
    py -3.12 -c "import sys" > NUL 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3.12"
    ) else (
        py -3.13 -c "import sys" > NUL 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_EXE=py"
            set "PYTHON_ARGS=-3.13"
        ) else (
            echo [ERRO] Python 3.12 ou 3.13 nao encontrado.
            exit /b 1
        )
    )
)

echo [INFO] Verificando modelos airllm (HF cache)...
call %PYTHON_EXE% %PYTHON_ARGS% scripts\install-models.py
if !errorlevel! geq 1 (
    echo [AVISO] Alguns modelos falharam. Verifique logs acima.
)

echo.
echo ========================================
echo    Setup concluido!
echo ========================================
echo Modelos disponiveis em:
echo   %%USERPROFILE%%\.cache\huggingface\local-models
echo.
echo Aliases suportados (ver scripts\install-models.py):
echo   micro/nano  -^>  Qwen2.5-0.5B-Instruct
echo   fast/small  -^>  Qwen2.5-1.5B-Instruct
echo   coder       -^>  Qwen2.5-Coder-1.5B-Instruct
echo   reasoning   -^>  DeepSeek-R1-Distill-Qwen-1.5B
echo   embed       -^>  all-MiniLM-L6-v2
echo.

endlocal
