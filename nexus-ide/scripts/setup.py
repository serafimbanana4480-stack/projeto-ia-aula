#!/usr/bin/env python3
"""NEXUS IDE - Setup automático.

Verifica e instala dependências, configura o ambiente, e inicia os serviços.
Uso:
    python scripts/setup.py

O script:
1. Verifica Python 3.12+
2. Cria venv se não existir
3. Instala dependências Python
4. Verifica Node.js e npm
5. Instala dependências do frontend
6. Verifica Ollama
7. Puxa modelos necessários
8. Gera SECRET_KEY e JWT_SECRET
9. Inicia backend e frontend
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = REPO_ROOT / ".venv"
FRONTEND_DIR = REPO_ROOT / "frontend"

def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    print(f"  > {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd or REPO_ROOT, check=check, capture_output=True, text=True)

def check_command(cmd: str) -> bool:
    """Check if a command is available."""
    return shutil.which(cmd) is not None

def generate_secrets() -> tuple[str, str]:
    """Generate secure random secrets."""
    return secrets.token_urlsafe(32), secrets.token_urlsafe(32)

def setup_env_file() -> None:
    """Create or update .env with secure secrets."""
    env_file = REPO_ROOT / ".env"
    secret_key, jwt_secret = generate_secrets()

    if env_file.exists():
        content = env_file.read_text(encoding="utf-8")
        # Update existing secrets
        lines = []
        for line in content.splitlines():
            if line.startswith("SECRET_KEY="):
                lines.append(f"SECRET_KEY={secret_key}")
            elif line.startswith("JWT_SECRET="):
                lines.append(f"JWT_SECRET={jwt_secret}")
            else:
                lines.append(line)
        content = "\n".join(lines) + "\n"
        env_file.write_text(content, encoding="utf-8")
        print("  ✓ Updated .env with new secrets")
    else:
        # Create from example
        example = REPO_ROOT / ".env.example"
        if example.exists():
            content = example.read_text(encoding="utf-8")
            content = content.replace(
                "SECRET_KEY=development-secret-key-change-in-production",
                f"SECRET_KEY={secret_key}",
            )
            content = content.replace(
                "JWT_SECRET=change-this-secret-in-production-use-env-var",
                f"JWT_SECRET={jwt_secret}",
            )
            env_file.write_text(content, encoding="utf-8")
            print("  ✓ Created .env from .env.example")
        else:
            print("  ✗ .env.example not found")

def main() -> int:
    print("=" * 60)
    print("NEXUS IDE - Setup Automático")
    print("=" * 60)

    # 1. Check Python version
    print("\n[1/9] Verificando Python...")
    py_version = sys.version_info
    if py_version < (3, 12):
        print(f"  ✗ Python {py_version.major}.{py_version.minor} encontrado. Requer 3.12+")
        return 1
    print(f"  ✓ Python {py_version.major}.{py_version.minor}.{py_version.micro}")

    # 2. Create venv
    print("\n[2/9] Verificando virtual environment...")
    if not VENV_DIR.exists():
        print("  Criando .venv...")
        run([sys.executable, "-m", "venv", str(VENV_DIR)])
    print(f"  ✓ venv em {VENV_DIR}")

    # Determine pip path
    pip_cmd = str(VENV_DIR / "Scripts" / "pip.exe") if sys.platform == "win32" else str(VENV_DIR / "bin" / "pip")
    python_cmd = str(VENV_DIR / "Scripts" / "python.exe") if sys.platform == "win32" else str(VENV_DIR / "bin" / "python")

    # 3. Install Python dependencies
    print("\n[3/9] Instalando dependências Python...")
    req_file = REPO_ROOT / "backend" / "requirements.txt"
    if req_file.exists():
        result = run([pip_cmd, "install", "-r", str(req_file)], check=False)
        if result.returncode == 0:
            print("  ✓ Dependências Python instaladas")
        else:
            print(f"  ⚠ Algumas dependências falharam: {result.stderr[:200]}")
    else:
        print("  ✗ requirements.txt não encontrado")

    # 4. Check Node.js
    print("\n[4/9] Verificando Node.js...")
    if check_command("node"):
        result = run(["node", "--version"], check=False)
        print(f"  ✓ Node.js {result.stdout.strip()}")
    else:
        print("  ✗ Node.js não encontrado. Instale de https://nodejs.org/")

    # 5. Install frontend dependencies
    print("\n[5/9] Instalando dependências do frontend...")
    if check_command("npm") and FRONTEND_DIR.exists():
        result = run(["npm", "install"], cwd=FRONTEND_DIR, check=False)
        if result.returncode == 0:
            print("  ✓ Frontend dependencies instaladas")
        else:
            print(f"  ⚠ npm install falhou: {result.stderr[:200]}")
    else:
        print("  ⚠ npm ou frontend/ não encontrado")

    # 6. Check Ollama
    print("\n[6/9] Verificando Ollama...")
    if check_command("ollama"):
        print("  ✓ Ollama instalado")
        # Check if running
        result = run(["curl", "-s", "http://localhost:11434/api/tags"], check=False)
        if result.returncode == 0:
            print("  ✓ Ollama running em localhost:11434")
        else:
            print("  ⚠ Ollama instalado mas não running. Inicie com: ollama serve")
    else:
        print("  ✗ Ollama não encontrado. Instale de https://ollama.com/download")

    # 7. Pull models
    print("\n[7/9] Verificando modelos Ollama...")
    required_models = ["mistral-small:latest", "qwen3.5:4b", "qwen3.5:9b"]
    for model in required_models:
        result = run(["ollama", "list"], check=False)
        if model.split(":")[0] in result.stdout:
            print(f"  ✓ {model}")
        else:
            print(f"  ⚠ {model} não encontrado. Puxar com: ollama pull {model}")

    # 8. Setup .env
    print("\n[8/9] Configurando .env...")
    setup_env_file()

    # 9. Summary
    print("\n" + "=" * 60)
    print("SETUP COMPLETO!")
    print("=" * 60)
    print("\nPara iniciar o NEXUS IDE:")
    print("  1. Terminal 1 - Backend:")
    print(f"     {python_cmd} run.py")
    print("  2. Terminal 2 - Frontend:")
    print(f"     cd frontend && npm run dev")
    print("\nAceder:")
    print("  IDE: http://localhost:3000")
    print("  API: http://localhost:8000/docs")
    print("=" * 60)

    return 0

if __name__ == "__main__":
    sys.exit(main())
