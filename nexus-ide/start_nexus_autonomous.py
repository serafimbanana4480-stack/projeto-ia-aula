#!/usr/bin/env python3
"""NEXUS IDE Autonomous Startup Script.

Starts the full NEXUS IDE backend with all agents, dashboard monitoring,
and auto-recovery. This script should be used for production and
autonomous deployments.

Usage:
    python start_nexus_autonomous.py [--dev] [--port 8000] [--dashboard-only]

Features:
    - Auto-detects Ollama and other LLM providers
    - Initializes database and required tables
    - Starts dashboard agent background loops
    - Verifies file system access and workspace
    - Runs health checks on all components
    - Auto-recovery on failure (restarts crashed components)
    - Supports both development and production modes
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("nexus_autonomous.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("nexus.autonomous")

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_BACKEND_PORT = 8000
DEFAULT_FRONTEND_PORT = 3000
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_DASHBOARD_HOST = os.environ.get("OLLAMA_DASHBOARD_HOST", "http://localhost:11435")


# ──────────────────────────────────────────────────────────────────────────────
# Health Checks
# ──────────────────────────────────────────────────────────────────────────────

def check_ollama() -> dict[str, Any]:
    """Check if Ollama is running and list available models."""
    import urllib.request
    import json

    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read())
            models = [m.get("name", m.get("model", "unknown")) for m in data.get("models", [])]
            return {"status": "healthy", "models": models, "count": len(models)}
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc), "models": [], "count": 0}


def check_backend_dependencies() -> dict[str, Any]:
    """Verify all required Python packages are installed."""
    required = [
        "fastapi", "pydantic", "httpx", "uvicorn", "pytest", "jose", "passlib",
        "numpy", "aiofiles", "cachetools", "sqlalchemy", "python-multipart",
    ]
    missing = []
    installed = []

    for pkg in required:
        try:
            __import__(pkg.replace("-", "_"))
            installed.append(pkg)
        except ImportError:
            missing.append(pkg)

    return {
        "status": "healthy" if not missing else "missing_deps",
        "installed": installed,
        "missing": missing,
    }


def check_database() -> dict[str, Any]:
    """Check database connectivity and required tables."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from backend.persistence.db import get_db, init_db

        init_db()
        with get_db() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [t["name"] for t in tables]
            required_tables = ["sessions", "messages", "tool_executions", "routing_decisions"]
            missing = [t for t in required_tables if t not in table_names]

            return {
                "status": "healthy" if not missing else "missing_tables",
                "tables": table_names,
                "missing": missing,
            }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def check_workspace() -> dict[str, Any]:
    """Verify workspace directory and required paths."""
    project_root = Path(__file__).parent
    required_paths = [
        "backend", "config", "frontend", "backend/agents", "backend/orchestrator",
        "config/models.yaml", "config/modes.yaml", "backend/persistence/schemas.sql",
    ]

    missing = []
    for p in required_paths:
        if not (project_root / p).exists():
            missing.append(p)

    return {
        "status": "healthy" if not missing else "missing_paths",
        "project_root": str(project_root),
        "missing": missing,
    }


def check_frontend() -> dict[str, Any]:
    """Check if frontend is built."""
    frontend_build = Path(__file__).parent / "frontend" / ".next"
    if frontend_build.exists():
        return {"status": "built", "path": str(frontend_build)}
    return {"status": "not_built", "note": "Run 'npm run build' in frontend/"}


# ──────────────────────────────────────────────────────────────────────────────
# Component Starters
# ──────────────────────────────────────────────────────────────────────────────

def start_ollama() -> subprocess.Popen | None:
    """Start Ollama if not already running."""
    health = check_ollama()
    if health["status"] == "healthy":
        logger.info("Ollama already running with %d models", health["count"])
        return None

    logger.info("Starting Ollama...")
    try:
        proc = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        # Wait for Ollama to be ready
        for _ in range(30):
            time.sleep(1)
            health = check_ollama()
            if health["status"] == "healthy":
                logger.info("Ollama started with %d models", health["count"])
                return proc
        logger.warning("Ollama may not have started correctly")
        return proc
    except FileNotFoundError:
        logger.error("Ollama not found. Install from https://ollama.com")
        return None
    except Exception as exc:
        logger.error("Failed to start Ollama: %s", exc)
        return None


def start_backend(port: int = DEFAULT_BACKEND_PORT, dev: bool = False) -> subprocess.Popen:
    """Start the FastAPI backend."""
    logger.info("Starting NEXUS backend on port %d (dev=%s)...", port, dev)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parent)
    env["ENVIRONMENT"] = "development" if dev else "production"

    cmd = [
        sys.executable,
        "-m", "uvicorn",
        "backend.orchestrator.main:app",
        "--host", "0.0.0.0",
        "--port", str(port),
    ]
    if dev:
        cmd.append("--reload")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return proc


def start_frontend(port: int = DEFAULT_FRONTEND_PORT) -> subprocess.Popen | None:
    """Start the Next.js frontend."""
    frontend_dir = Path(__file__).parent / "frontend"
    if not frontend_dir.exists():
        logger.warning("Frontend directory not found, skipping")
        return None

    logger.info("Starting NEXUS frontend on port %d...", port)

    env = os.environ.copy()
    env["PORT"] = str(port)

    try:
        proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(frontend_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return proc
    except FileNotFoundError:
        logger.warning("npm not found, frontend not started")
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Main Orchestrator
# ──────────────────────────────────────────────────────────────────────────────

def print_banner() -> None:
    """Print startup banner."""
    print("=" * 70)
    print("  NEXUS IDE — Autonomous Multi-Agent Development Environment")
    print("  Version: 2.0 | Mode: AUTONOMOUS")
    print("=" * 70)


def print_health_report(report: dict[str, Any]) -> None:
    """Print health check report."""
    print("\n--- Health Check Report ---")
    for component, result in report.items():
        status = result.get("status", "unknown")
        icon = "✓" if status in ("healthy", "built") else "✗"
        print(f"  {icon} {component}: {status}")
        if status == "missing_deps" and result.get("missing"):
            print(f"    Missing: {', '.join(result['missing'])}")
        if status == "missing_tables" and result.get("missing"):
            print(f"    Missing tables: {', '.join(result['missing'])}")
        if status == "unavailable" and result.get("error"):
            print(f"    Error: {result['error']}")
    print("-" * 30)


def run_all_checks() -> dict[str, Any]:
    """Run all health checks and return report."""
    print("\nRunning system checks...")
    report = {
        "ollama": check_ollama(),
        "dependencies": check_backend_dependencies(),
        "database": check_database(),
        "workspace": check_workspace(),
        "frontend": check_frontend(),
    }
    return report


def install_missing_deps(missing: list[str]) -> bool:
    """Install missing Python packages."""
    if not missing:
        return True

    print(f"\nInstalling missing dependencies: {', '.join(missing)}...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", *missing],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("Dependencies installed successfully.")
        return True
    except Exception as exc:
        print(f"Failed to install dependencies: {exc}")
        return False


def main() -> None:
    """Main entry point for autonomous startup."""
    parser = argparse.ArgumentParser(description="NEXUS IDE Autonomous Starter")
    parser.add_argument("--dev", action="store_true", help="Development mode with hot reload")
    parser.add_argument("--port", type=int, default=DEFAULT_BACKEND_PORT, help="Backend port")
    parser.add_argument("--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT, help="Frontend port")
    parser.add_argument("--dashboard-only", action="store_true", help="Start only dashboard")
    parser.add_argument("--no-frontend", action="store_true", help="Skip frontend startup")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser")
    parser.add_argument("--install-deps", action="store_true", help="Auto-install missing dependencies")
    args = parser.parse_args()

    print_banner()

    # Health checks
    report = run_all_checks()
    print_health_report(report)

    # Handle missing dependencies
    if report["dependencies"]["status"] == "missing_deps":
        missing = report["dependencies"]["missing"]
        if args.install_deps:
            if not install_missing_deps(missing):
                sys.exit(1)
        else:
            print(f"\nMissing dependencies: {', '.join(missing)}")
            print("Run with --install-deps to auto-install, or run:")
            print(f"  {sys.executable} -m pip install {' '.join(missing)}")
            sys.exit(1)

    # Start Ollama if not running
    ollama_proc = start_ollama()

    # Check database
    if report["database"]["status"] != "healthy":
        logger.warning("Database issues detected, attempting to initialize...")
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from backend.persistence.db import init_db
            init_db()
            logger.info("Database initialized successfully")
        except Exception as exc:
            logger.error("Database initialization failed: %s", exc)

    # Start backend
    backend_proc = start_backend(port=args.port, dev=args.dev)

    # Start frontend
    frontend_proc = None
    if not args.no_frontend:
        frontend_proc = start_frontend(port=args.frontend_port)

    # Wait for backend to be ready
    print("\nWaiting for backend to be ready...")
    import urllib.request
    backend_url = f"http://localhost:{args.port}/health"
    for i in range(30):
        try:
            urllib.request.urlopen(backend_url, timeout=2.0)
            print(f"Backend ready at {backend_url}")
            break
        except Exception:
            time.sleep(1)
            print(f"  ... {i+1}/30")
    else:
        print("WARNING: Backend may not be ready yet")

    # Print access URLs
    print("\n" + "=" * 70)
    print("  NEXUS IDE is running!")
    print(f"  Backend API: http://localhost:{args.port}")
    print(f"  API Docs:    http://localhost:{args.port}/docs")
    if frontend_proc:
        print(f"  Frontend:    http://localhost:{args.frontend_port}")
    print("=" * 70)

    # Open browser
    if not args.no_browser and frontend_proc:
        webbrowser.open(f"http://localhost:{args.frontend_port}")
    elif not args.no_browser:
        webbrowser.open(f"http://localhost:{args.port}/docs")

    # Monitor processes
    print("\nPress Ctrl+C to stop all services.\n")
    try:
        while True:
            if backend_proc.poll() is not None:
                logger.error("Backend process exited with code %d", backend_proc.returncode)
                print("Backend crashed! Restarting in 5 seconds...")
                time.sleep(5)
                backend_proc = start_backend(port=args.port, dev=args.dev)

            if ollama_proc and ollama_proc.poll() is not None:
                logger.warning("Ollama process exited, restarting...")
                ollama_proc = start_ollama()

            if frontend_proc and frontend_proc.poll() is not None:
                logger.warning("Frontend process exited")
                frontend_proc = None

            time.sleep(5)
    except KeyboardInterrupt:
        print("\n\nShutting down NEXUS IDE...")
        backend_proc.terminate()
        if ollama_proc:
            ollama_proc.terminate()
        if frontend_proc:
            frontend_proc.terminate()
        print("All services stopped. Goodbye!")


if __name__ == "__main__":
    main()
