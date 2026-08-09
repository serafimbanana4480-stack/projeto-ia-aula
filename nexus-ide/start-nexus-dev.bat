@echo off
REM NEXUS IDE - modo DESENVOLVIMENTO do backend (hot-reload com ambito limitado).
REM
REM Usa este launcher so quando estas a editar codigo do backend a mao.
REM O reload esta limitado a backend/ e exclui explicitamente os diretorios
REM onde os proprios agentes escrevem (.nexus/, data/, logs/, backups) para nao
REM reiniciar o servidor a meio de uma tarefa da IA.
REM
REM Ver docs/SELFCHECK-evidence/repro-uvicorn-reload.txt para a reproducao do
REM bug que motivou esta separacao.
title NEXUS Launcher (dev)

set NEXUS_ALLOW_DEGRADED_STARTUP=1
start "NEXUS Backend (dev)" cmd /k "cd /d C:\Users\rodri\Desktop\nexus\nexus-ide && set NEXUS_ALLOW_DEGRADED_STARTUP=1 && .venv\Scripts\python.exe -m uvicorn backend.orchestrator.main:app --host 127.0.0.1 --port 8001 --reload --reload-dir backend --reload-exclude \".nexus/*\" --reload-exclude \"data/*\" --reload-exclude \"logs/*\" --reload-exclude \"*/__pycache__/*\" --reload-exclude \"backend/.nexus/*\""
start "NEXUS Frontend" cmd /k "cd /d C:\Users\rodri\Desktop\nexus\nexus-ide\frontend && npm run dev -- --hostname 127.0.0.1 --port 3001"

echo.
echo NEXUS (dev) a iniciar: Backend (':8001') e Frontend (':3001').
echo   ATENCAO: com hot-reload ativo, tarefas longas da IA podem ser
echo   interrompidas se editares ficheiros em backend/.
echo   Para uso normal usa start-nexus.bat (sem reload).
pause
