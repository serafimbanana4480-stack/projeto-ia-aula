"""Entry point for running the NEXUS IDE backend on Windows.

Using a dedicated script instead of ``python -m uvicorn`` avoids the
multiprocessing RuntimeError on Windows when ``--reload`` is enabled.
See: https://github.com/encode/uvicorn/issues/1558
"""

import os
import sys
from pathlib import Path

# Ensure project root is on PYTHONPATH so ``backend.*`` imports resolve
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure workspace/shell/python operations resolve relative paths from the project
# root instead of the directory where uvicorn was launched.
os.chdir(PROJECT_ROOT)

import uvicorn  # noqa: E402

if __name__ == "__main__":
    # reload=True causa RuntimeError/loops de subprocesso no Windows.
    # Usar reload=False por padrao; ativar reload apenas via variavel de ambiente.
    #
    # A porta e carregada a partir das definicoes da aplicacao (env BACKEND_PORT)
    # para respeitar o .env e nao ficar hardcoded, evitando conflitos com
    # processos que ja estejam a ouvir na porta 8000.
    from backend.config.settings import get_settings  # noqa: E402

    settings = get_settings()
    print(f"NEXUS backend a arrancar em http://{settings.backend_host}:{settings.backend_port} (reload={settings.backend_reload})")
    try:
        uvicorn.run(
            "backend.orchestrator.main:app",
            host=settings.backend_host,
            port=settings.backend_port,
            reload=settings.backend_reload,
        )
    except KeyboardInterrupt:
        print("Encerrado pelo utilizador")
        sys.exit(0)
