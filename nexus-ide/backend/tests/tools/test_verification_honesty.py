"""P3 da auditoria 2026-08-16: nunca dar verde sem ter executado testes.

O defeito não era o pytest falhar — era o pytest **não arrancar** e o resultado
chegar ao utilizador como "0 passaram, 0 falharam ✓". Uma ferramenta que erra
em voz alta é usável com cuidado; uma que erra em silêncio e diz "Trabalho
concluído ✓" não é.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from backend.tools.interpreters import resolve_python_interpreter
from backend.tools.test_runner import run_tests


@pytest.mark.asyncio
async def test_missing_pytest_is_reported_as_not_run(monkeypatch, tmp_path) -> None:
    async def fake_run(args, cwd=None, timeout=600, interpreter=None):
        return (1, "", "/usr/bin/python: No module named pytest\n")

    monkeypatch.setattr("backend.tools.test_runner._run_pytest", fake_run)

    result = await run_tests(project_path=str(tmp_path))

    assert result["status"] == "not_run"
    assert result["ran"] is False
    assert result["executed"] is False
    assert result["ok"] is False
    assert result["passed"] == 0
    assert "não" in result["error"].lower() or "nao" in result["error"].lower()


@pytest.mark.asyncio
async def test_zero_collected_tests_is_reported_as_nothing_verified(
    monkeypatch, tmp_path
) -> None:
    """returncode 5 = "não há testes". Não é uma falha, mas também não é prova.

    A distinção importa: tratar "o projeto não tem testes" como verificação
    vermelha mandava o loop primário para um ciclo de recuperação — uma
    segunda inferência completa — em perguntas só de leitura.
    """

    async def fake_run(args, cwd=None, timeout=600, interpreter=None):
        return (5, "no tests ran in 0.01s", "")

    monkeypatch.setattr("backend.tools.test_runner._run_pytest", fake_run)

    result = await run_tests(project_path=str(tmp_path))

    assert result["status"] == "no_tests"
    assert result["no_tests_found"] is True
    assert result["executed"] is False
    assert result["passed"] == 0
    assert "não" in result["error"].lower() or "nao" in result["error"].lower()


@pytest.mark.asyncio
async def test_real_pass_is_still_green(monkeypatch, tmp_path) -> None:
    async def fake_run(args, cwd=None, timeout=600, interpreter=None):
        return (0, "===== 4 passed in 0.12s =====", "")

    monkeypatch.setattr("backend.tools.test_runner._run_pytest", fake_run)

    result = await run_tests(project_path=str(tmp_path))

    assert result["ok"] is True
    assert result["ran"] is True
    assert result["executed"] is True
    assert result["passed"] == 4


def test_interpreter_prefers_the_project_venv(tmp_path) -> None:
    venv_python = tmp_path / "venv" / ("Scripts" if sys.platform == "win32" else "bin")
    venv_python.mkdir(parents=True)
    binary = venv_python / ("python.exe" if sys.platform == "win32" else "python")
    binary.write_text("#!/bin/sh\n")

    assert resolve_python_interpreter(str(tmp_path)) == str(binary)


def test_interpreter_falls_back_to_the_running_one(tmp_path) -> None:
    # Nunca "python" do PATH: esse é o que não tinha pytest.
    resolved = resolve_python_interpreter(str(tmp_path))
    assert resolved == sys.executable
    assert Path(resolved).name != "python" or Path(resolved).is_absolute()


def test_env_override_wins(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NEXUS_PYTHON", "/opt/custom/python")
    assert resolve_python_interpreter(str(tmp_path)) == "/opt/custom/python"
