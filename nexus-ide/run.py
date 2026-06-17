"""Entry point for running the NEXUS IDE backend on Windows.

Using a dedicated script instead of ``python -m uvicorn`` avoids the
multiprocessing RuntimeError on Windows when ``--reload`` is enabled.
See: https://github.com/encode/uvicorn/issues/1558
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root is on PYTHONPATH so ``backend.*`` imports resolve
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure workspace/shell/python operations resolve relative paths from the project
# root instead of the directory where uvicorn was launched.
os.chdir(PROJECT_ROOT)


def _ts() -> str:
    import datetime

    return datetime.datetime.now().isoformat(timespec="seconds")


def log(msg: str, *, level: str = "INFO") -> None:
    print(json.dumps({"ts": _ts(), "level": level, "msg": msg}, ensure_ascii=False))


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((host, port))
            return True
        except OSError:
            return False


def find_pid_for_port(port: int) -> int | None:
    """Return the first PID listening on *port*, or ``None``."""
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"],
            shell=True,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        log(f"Falha ao executar netstat: {exc}", level="ERROR")
        return None

    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5:
            local = parts[1]
            state = parts[3]
            if state != "LISTENING":
                continue
            if ":" + str(port) in local:
                try:
                    return int(parts[4])
                except ValueError:
                    continue
    return None


def stop_service_on_port(port: int) -> bool:
    pid = find_pid_for_port(port)
    if pid is None:
        return False
    log(f"Parando processo {pid} na porta {port}...")
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            shell=True,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(1.5)
        return True
    except Exception as exc:
        log(f"Falha ao parar PID {pid}: {exc}", level="ERROR")
        return False


def wait_for_health(url: str, *, retries: int = 40, delay: float = 1.5) -> bool:
    log(f"Healthcheck: aguardando {url} (até {retries} tentativas)...")
    # Prefer urllib so we don't pull in requests just for this probe.
    import urllib.error
    import urllib.request

    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    log(f"Healthcheck OK em {attempt} tentativa(s): {url}")
                    return True
        except (urllib.error.URLError, OSError) as exc:
            if attempt % 5 == 0 or attempt == 1:
                log(f"Healthcheck aguardando... tentativa {attempt}/{retries}: {exc}")
        time.sleep(delay)
    return False


def main() -> int:
    import uvicorn  # noqa: E402

    # reload=True causa RuntimeError/loops de subprocesso no Windows.
    # Usar reload=False por padrao; ativar reload apenas via variavel de ambiente.
    #
    # A porta e carregada a partir das definicoes da aplicacao (env BACKEND_PORT)
    # para respeitar o .env e nao ficar hardcoded.
    from backend.config.settings import get_settings  # noqa: E402

    settings = get_settings()
    port = int(settings.backend_port)
    host = settings.backend_host or "0.0.0.0"
    health_url = f"http://127.0.0.1:{port}/health"

    if settings.environment == "production" and settings.debug:
        log(
            "AVISO: debug=true em producao — recomendado desativar para performance/seguranca.",
            level="WARNING",
        )

    log(f"NEXUS backend a arrancar em http://{host}:{port} (reload={settings.backend_reload})")

    if is_port_in_use(port):
        pid = find_pid_for_port(port)
        log(
            f"Porta {port} em uso (PID={pid}). NEXUS nao pode arrancar.",
            level="ERROR",
        )
        log(
            "Sugestao: pare o processo antes de continuar "
            f"(taskkill /PID {pid} /F) ou use iniciar.bat --parar.",
            level="ERROR",
        )
        return 2

    log("Nenhum processo detected na porta local — pronto para arrancar.")

    uvicorn_kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "reload": bool(settings.backend_reload),
    }
    if settings.backend_reload:
        log("Aviso: reload habilitado — multiplos workers nao estarao disponiveis no Windows.")
        uvicorn_kwargs["workers"] = 1

    log("A subir uvicorn...")
    try:
        uvicorn.run("backend.orchestrator.main:app", **uvicorn_kwargs)
    except KeyboardInterrupt:
        log("Encerramento solicitado pelo utilizador (KeyboardInterrupt).")
        return 0
    except OSError as exc:
        log(f"Falha de rede/IO ao subir uvicorn: {exc}", level="ERROR")
        return 3
    except Exception as exc:  # pragma: no cover - defensivo
        log(f"Erro inesperado ao subir backend: {exc}", level="ERROR")
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
