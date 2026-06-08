#!/usr/bin/env python
"""NEXUS IDE - Unified Control CLI and Launcher.

This script unifies the management, execution, testing, and diagnostics
of the multi-agent NEXUS IDE project under a single functional command-line utility.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT
FRONTEND_DIR = PROJECT_ROOT / "frontend"
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
DOCKER_COMPOSE_FILE = PROJECT_ROOT / "docker" / "docker-compose.yml"


def print_banner() -> None:
    banner = """
========================================================================
  N E X U S   I D E   --   U N I F I E D   C O N T R O L   P A N E L
========================================================================
        >> UNIFIED CONTROL PANEL & MULTI-AGENT ORCHESTRATOR <<
"""
    print("\033[96m" + banner + "\033[0m")


def check_port(port: int) -> bool:
    """Return True if port is in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_env() -> None:
    """Ensure the .env file exists, copy from .env.example if not."""
    if not ENV_FILE.exists():
        print(f"\033[93m[INFO] .env not found. Copying from {ENV_EXAMPLE.name}...\033[0m")
        if ENV_EXAMPLE.exists():
            ENV_FILE.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
            print("\033[92m[SUCCESS] .env file created successfully.\033[0m")
        else:
            print("\033[91m[ERROR] .env.example not found. Cannot create .env!\033[0m")


def run_diagnostics() -> None:
    """Verify system health, CUDA availability, and key package imports."""
    print("\n\033[94m=== SYSTEM DIAGNOSTICS ===\033[0m")
    
    # Python Version
    print(f"Python Version: {sys.version.split()[0]}")
    
    # PyTorch and CUDA
    try:
        import torch
        print(f"PyTorch Version: {torch.__version__}")
        print(f"CUDA (GPU Acceleration): {'\033[92mAVAILABLE\033[0m' if torch.cuda.is_available() else '\033[93mNOT AVAILABLE (using CPU)\033[0m'}")
    except ImportError:
        print("PyTorch: \033[91mNOT INSTALLED\033[0m")

    # AirLLM Availability
    try:
        import airllm
        print(f"AirLLM: \033[92mINSTALLED ({airllm.__version__ if hasattr(airllm, '__version__') else 'unknown version'})\033[0m")
    except ImportError:
        print("AirLLM: \033[91mNOT INSTALLED\033[0m")

    # Docker status
    try:
        res = subprocess.run(["docker", "ps"], capture_output=True, text=True, check=False)
        if res.returncode == 0:
            print("Docker: \033[92mRUNNING\033[0m")
        else:
            print("Docker: \033[91mINSTALLED BUT NOT RUNNING\033[0m")
    except FileNotFoundError:
        print("Docker: \033[91mNOT FOUND in PATH\033[0m")

    # Port checks
    services = {
        3000: "Next.js Frontend",
        8000: "FastAPI Backend",
        9090: "Prometheus Monitoring",
        6379: "Redis Cache",
    }
    print("\nPort Status:")
    for port, name in services.items():
        in_use = check_port(port)
        status = "\033[91mIN USE (Active)\033[0m" if in_use else "\033[92mFREE (Available)\033[0m"
        print(f"  - Port {port:<5} ({name}): {status}")


def start_docker() -> None:
    """Start Docker infrastructure (Redis, Prometheus)."""
    print("\n\033[94m[INFO] Starting Docker containers...\033[0m")
    try:
        subprocess.run(
            ["docker", "compose", "-f", str(DOCKER_COMPOSE_FILE), "up", "-d", "redis", "prometheus"],
            check=True,
        )
        print("\033[92m[SUCCESS] Docker infrastructure is starting/up.\033[0m")
    except subprocess.CalledProcessError as e:
        print(f"\033[91m[ERROR] Failed to start Docker Compose: {e}\033[0m")
    except FileNotFoundError:
        print("\033[93m[WARNING] 'docker' command not found. Skipping Docker infra.\033[0m")


def stop_docker() -> None:
    """Stop Docker infrastructure."""
    print("\n\033[94m[INFO] Stopping Docker containers...\033[0m")
    try:
        subprocess.run(
            ["docker", "compose", "-f", str(DOCKER_COMPOSE_FILE), "down"],
            check=True,
        )
        print("\033[92m[SUCCESS] Docker infrastructure stopped.\033[0m")
    except Exception as e:
        print(f"\033[91m[ERROR] Failed to stop Docker Compose: {e}\033[0m")


async def run_services() -> None:
    """Start Backend, Frontend and monitor them."""
    ensure_env()
    start_docker()
    
    print("\n\033[94m[INFO] Launching Backend & Frontend services...\033[0m")
    
    # Locate virtual environment python
    venv_py = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    python_cmd = str(venv_py) if venv_py.exists() else "python"
    
    backend_proc = None
    frontend_proc = None
    
    try:
        # Start Backend (FastAPI via run.py)
        print("\033[94m[LAUNCH] Backend service starting on http://localhost:8000...\033[0m")
        backend_proc = subprocess.Popen(
            [python_cmd, "run.py"],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Start Frontend (Next.js)
        print("\033[94m[LAUNCH] Frontend service starting on http://localhost:3000...\033[0m")
        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        frontend_proc = subprocess.Popen(
            [npm_cmd, "run", "dev"],
            cwd=str(FRONTEND_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        print("\n\033[92m[READY] Both servers started. Press Ctrl+C to terminate all services.\033[0m")
        print("\033[94mAccess points:\033[0m")
        print("  - \033[92mIDE:\033[0m        http://localhost:3000")
        print("  - \033[92mAPI Docs:\033[0m   http://localhost:8000/docs")
        print("  - \033[92mDashboard:\033[0m  http://localhost:3000/dashboard")
        
        # Simple loop to forward logs or check status
        while True:
            await asyncio.sleep(1)
            # Check if any process died
            if backend_proc.poll() is not None:
                print("\033[91m[CRASH] Backend service terminated unexpectedly!\033[0m")
                break
            if frontend_proc.poll() is not None:
                print("\033[91m[CRASH] Frontend service terminated unexpectedly!\033[0m")
                break
                
    except KeyboardInterrupt:
        print("\n\033[93m[INFO] Shutting down services...\033[0m")
    finally:
        if backend_proc:
            backend_proc.terminate()
            backend_proc.wait()
            print("[INFO] Backend stopped.")
        if frontend_proc:
            frontend_proc.terminate()
            frontend_proc.wait()
            print("[INFO] Frontend stopped.")
        stop_docker()


def run_e2e_tests() -> None:
    """Run E2E validation script."""
    ensure_env()
    print("\n\033[94m=== RUNNING MISSION CONTROL E2E TESTS ===\033[0m")
    venv_py = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    python_cmd = str(venv_py) if venv_py.exists() else "python"
    
    # Run mission control test
    res = subprocess.run([python_cmd, "mission_control_e2e_test.py"], cwd=str(PROJECT_ROOT))
    if res.returncode == 0:
        print("\033[92m[PASS] Mission Control E2E validation passed.\033[0m")
    else:
        print("\033[91m[FAIL] E2E validation failed.\033[0m")


def main() -> None:
    print_banner()
    
    parser = argparse.ArgumentParser(description="NEXUS IDE Management Utility")
    parser.add_argument(
        "action",
        choices=["start", "diagnose", "test", "stop-docker"],
        help="Action to perform",
        default="start",
        nargs="?"
    )
    
    args = parser.parse_args()
    
    if args.action == "diagnose":
        run_diagnostics()
    elif args.action == "test":
        run_e2e_tests()
    elif args.action == "stop-docker":
        stop_docker()
    elif args.action == "start":
        asyncio.run(run_services())


if __name__ == "__main__":
    main()
