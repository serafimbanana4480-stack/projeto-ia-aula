"""Regressão: o servidor de desenvolvimento não pode usar --reload sem âmbito.

Contexto (bug P0 encontrado em 2026-07-27)
------------------------------------------
O NEXUS é um IDE cujos próprios agentes escrevem ficheiros ``.py`` dentro da
árvore do projeto:

* ``backend/core/workspace_backup.py:63`` guarda backups em
  ``<git_root>/.nexus/backups/``;
* o ``SelfImprovementLoop`` e o ``AutonomousExecutionEngine``
  (``backend/orchestrator/main.py:239-257``) arrancam com a app e produzem
  alterações de código.

O ``uvicorn --reload`` sem ``--reload-dir`` vigia a CWD inteira e recarrega a
qualquer alteração em ``*.py``. Resultado reproduzido em
``docs/SELFCHECK-evidence/repro-uvicorn-reload.txt``::

    3) IA a trabalhar 3s: {"pid":13,"runs":{"run-1":3}}
    >>> a IA escreve um .py no workspace <<<
    WARNING:  WatchFiles detected changes in 'agent_output.py'. Reloading...
    INFO:     Shutting down
    INFO:     Started server process [20]
    4) logo a seguir:     {"pid":20,"runs":{}}
    5) +6s, IA retomou?:  {"pid":20,"runs":{}}

Ou seja: a sessão reinicia, o estado em memória
(``CancellationRegistry._entries``, ``backend/orchestrator/cancellation.py:46``)
é apagado, e como não existe qualquer rotina de ``resume``/``recover``, a IA
nunca retoma o trabalho.

Estes testes travam a regressão ao nível da configuração de arranque.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Ficheiros que arrancam o uvicorn em modo de desenvolvimento.
LAUNCHERS = [
    REPO_ROOT / "start-nexus.bat",
    REPO_ROOT / "Makefile",
]

# --reload é aceitável desde que o âmbito esteja limitado por --reload-dir.
_RELOAD = re.compile(r"--reload(?![-\w])")
_RELOAD_DIR = re.compile(r"--reload-dir[= ]")


def _uvicorn_lines(text: str) -> list[str]:
    """Linhas que invocam o uvicorn, ignorando comentários."""
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("#") or stripped.upper().startswith("REM "):
            continue
        if "uvicorn" in stripped:
            lines.append(stripped)
    return lines


@pytest.mark.parametrize("launcher", LAUNCHERS, ids=lambda p: p.name)
def test_launcher_does_not_use_unscoped_reload(launcher: Path) -> None:
    """--reload sem --reload-dir mata as tarefas em curso da própria IA."""
    if not launcher.exists():
        pytest.skip(f"{launcher.name} não existe")

    text = launcher.read_text(encoding="utf-8", errors="replace")
    offenders = [
        line
        for line in _uvicorn_lines(text)
        if _RELOAD.search(line) and not _RELOAD_DIR.search(line)
    ]

    assert not offenders, (
        f"{launcher.name} arranca o uvicorn com --reload sem --reload-dir.\n"
        "O watcher vigia a CWD inteira; quando o agente escreve um .py o "
        "servidor reinicia e perde o estado da sessão em memória.\n"
        "Linhas ofensivas:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("launcher", LAUNCHERS, ids=lambda p: p.name)
def test_reload_scope_excludes_agent_written_dirs(launcher: Path) -> None:
    """Se houver --reload-dir, não pode apanhar dirs escritos pelo agente."""
    if not launcher.exists():
        pytest.skip(f"{launcher.name} não existe")

    text = launcher.read_text(encoding="utf-8", errors="replace")
    # Dirs onde o próprio agente escreve — nunca devem estar sob watch.
    forbidden = (".nexus", "data", "logs")

    for line in _uvicorn_lines(text):
        for match in re.finditer(r"--reload-dir[= ]([^\s\"']+)", line):
            scope = match.group(1).strip("./\\")
            assert scope not in forbidden, (
                f"{launcher.name}: --reload-dir {scope} vigia um diretório "
                "onde o próprio agente escreve — provoca reload em loop."
            )


def test_next_dev_and_build_use_separate_output_directories() -> None:
    """A production build must not corrupt a concurrently running dev server."""
    frontend = REPO_ROOT / "frontend"
    if not (frontend / "node_modules" / "next").is_dir():
        pytest.skip("dependências do frontend não instaladas (node_modules/next)")
    script = """
import configFactory from './next.config.mjs';
import {
  PHASE_DEVELOPMENT_SERVER,
  PHASE_PRODUCTION_BUILD,
} from 'next/constants.js';
const dev = configFactory(PHASE_DEVELOPMENT_SERVER);
const build = configFactory(PHASE_PRODUCTION_BUILD);
console.log(JSON.stringify({ dev: dev.distDir, build: build.distDir }));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=frontend,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    dirs = json.loads(result.stdout)
    assert dirs["dev"] != dirs["build"], (
        "next dev e next build partilham a mesma distDir; se correrem em "
        "paralelo, removem manifests/chunks um do outro e a UI devolve 500"
    )
    assert dirs == {"dev": ".next-dev", "build": ".next"}


def test_frontend_never_puts_bearer_tokens_in_sse_query_strings() -> None:
    """Bearer tokens in URLs leak through history, proxies and access logs."""
    for relative_path in (
        Path("frontend/hooks/useSSE.ts"),
        Path("frontend/stores/metricsStore.ts"),
    ):
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "encodeURIComponent(token)" not in source
        assert "?token=" not in source
