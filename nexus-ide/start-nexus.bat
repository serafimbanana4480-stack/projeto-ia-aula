@echo off
REM NEXUS IDE - arranca backend e frontend em janelas separadas (ficam abertas)
title NEXUS Launcher

REM Keep the backend port aligned with frontend/.env.local (NEXT_PUBLIC_API_URL).
REM
REM NAO usar --reload aqui. O NEXUS e um IDE cujos proprios agentes escrevem
REM ficheiros .py dentro desta arvore (workspace_backup.py:63 guarda backups no
REM git root; SelfImprovementLoop/AutonomousExecutionEngine correm no startup).
REM Com --reload, o watcher do uvicorn vigia a CWD inteira: assim que o agente
REM escreve um .py o servidor reinicia, o estado em memoria da sessao
REM (CancellationRegistry._entries) e apagado e a tarefa em curso nunca retoma.
REM Evidencia: docs/SELFCHECK-evidence/repro-uvicorn-reload.txt
REM
REM Para desenvolver o backend com hot-reload, usa start-nexus-dev.bat
REM (reload limitado a backend/, excluindo dirs escritos pelo agente).
set NEXUS_ALLOW_DEGRADED_STARTUP=1
start "NEXUS Backend" cmd /k "cd /d C:\Users\rodri\Desktop\nexus\nexus-ide && set NEXUS_ALLOW_DEGRADED_STARTUP=1 && .venv\Scripts\python.exe -m uvicorn backend.orchestrator.main:app --host 127.0.0.1 --port 8001"
start "NEXUS Frontend" cmd /k "cd /d C:\Users\rodri\Desktop\nexus\nexus-ide\frontend && npm run dev -- --hostname 127.0.0.1 --port 3001"

echo.
echo NEXUS a iniciar: Backend (':8001') e Frontend (':3001') em janelas separadas.
echo   Backend health:  http://localhost:8001/health
echo   Frontend:        http://localhost:3001
echo   (O backend usa 'uv run' — na PRIMEIRA vez o uv instala as dependencias; pode demorar minutos.)
echo Fecha as janelas para parar os servicos.
pause
