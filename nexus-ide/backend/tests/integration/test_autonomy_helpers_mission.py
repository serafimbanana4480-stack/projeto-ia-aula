"""Fase 1 — scaffolding for the long-autonomy mission.

Owned by the autonomy-mission workstream together with
``test_autonomy_mission_long.py``. It holds the three things the mission needs
that are not the mission itself:

* the deliberately defective mini-project the mission must repair;
* the scripted provider that plays the model (with the injected failures);
* read-only SQLite readers, so the test asserts against what the durable run
  state actually persisted instead of what the stream reported.

Everything here is inert on its own: no test collects it, and importing it has
no side effects.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# ── the mission contract ────────────────────────────────────────────────────

#: The mission goal. Kept on one line: it is what the run must remember, and
#: the resume assertion compares it verbatim.
MISSION_GOAL = (
    "Analisa este projeto, cria plano, executa as correções nos defeitos "
    "conhecidos, corre os testes, corrige o que falhar e produz REPORT.md com "
    "a evidência do que foi feito."
)

#: The requirements the mission must satisfy. They are asserted against
#: durable evidence by the test, not handed to the lane (see the test file for
#: why that distinction matters).
MISSION_REQUIREMENTS: tuple[str, ...] = (
    "defeito 1: calc.add corrigido e verificado pelos testes",
    "defeito 2: asserção errada em tests/test_calc.py corrigida",
    "defeito 3: import circular entre pipeline e report eliminado",
    "testes do projeto passam",
    "relatório produzido em REPORT.md com evidência",
)

MISSION_SESSION = "mission-session"

REPORT_NAME = "REPORT.md"

#: The plan the scripted model declares. ``todo_write`` persists it as
#: ``run_state.plan_json``, which is what makes the plan resumable.
MISSION_PLAN_ITEMS: tuple[dict[str, str], ...] = (
    {"content": "inspecionar o projeto e listar os defeitos", "priority": "high"},
    {"content": "corrigir calc.add (devolve None)", "priority": "high"},
    {"content": "corrigir a asserção errada em tests/test_calc.py", "priority": "high"},
    {"content": "quebrar o import circular pipeline <-> report", "priority": "high"},
    {"content": "correr a suite e corrigir o que falhar", "priority": "normal"},
    {"content": "escrever REPORT.md com a evidência", "priority": "normal"},
)

# ── the deliberately defective project ──────────────────────────────────────
#
# Four defects, three of them plain bugs and one gate that no code change can
# release. The gate is what forces the loop's verification back-edge: the run
# has to fail once, come back with the failure as feedback, and only then make
# progress. That is the "task designed to fail once and demand a replan" of the
# mission brief.

CONFTEST_CONTENT = '''\
"""Make the project root importable for the suite.

pytest inserts this file's own directory on ``sys.path``, which is what lets
``tests/test_calc.py`` do ``from calc import add``.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
'''

BROKEN_CALC_CONTENT = '''\
"""Mini calculator used by the autonomy mission."""


def add(a, b):
    # DEFEITO 1: devolve sempre None em vez da soma.
    return None


def multiply(a, b):
    return a * b
'''

FIXED_CALC_CONTENT = '''\
"""Mini calculator used by the autonomy mission."""


def add(a, b):
    return a + b


def multiply(a, b):
    return a * b
'''

BROKEN_TEST_CONTENT = '''\
"""Suite of the mission project."""

from calc import add


def test_add():
    # DEFEITO 2: asserção errada — 2 + 3 é 5, não 6.
    assert add(2, 3) == 6


def test_multiply():
    assert multiply(2, 3) == 6
'''

FIXED_TEST_CONTENT = '''\
"""Suite of the mission project."""

from calc import add, multiply


def test_add():
    assert add(2, 3) == 5


def test_multiply():
    assert multiply(2, 3) == 6
'''

BROKEN_PIPELINE_CONTENT = '''\
"""Text pipeline of the mission project."""

# DEFEITO 3: import no topo do módulo cria um ciclo com report.
from report import render


def transform(text):
    return render(text).upper()
'''

FIXED_PIPELINE_CONTENT = '''\
"""Text pipeline of the mission project."""


def transform(text):
    # O ciclo foi quebrado com um import local: report só é necessário aqui.
    from report import render

    return render(text).upper()
'''

REPORT_MODULE_CONTENT = '''\
"""Render helpers for the mission project."""

from pipeline import transform


def render(text):
    return "[report] " + transform(text)
'''

PROBE_TEST_CONTENT = '''\
"""The gate no code change can release.

The operator releases it by creating PROBE_OK in the project root. The suite is
red until that file exists, which is what makes the mission fail once and come
back for a second cycle.
"""

from pathlib import Path

PROBE = Path(__file__).resolve().parents[1] / "PROBE_OK"


def test_probe_gate():
    assert PROBE.exists(), "PROBE_OK missing in project root"
'''

NOTES_CONTENT = """\
# Mission project

Deliberate defects, one per file:

1. `calc.py::add` returns `None`.
2. `tests/test_calc.py` asserts the wrong sum.
3. `pipeline.py` imports `report` at module level (`report` imports `pipeline`).
4. Gate: the suite stays red until `PROBE_OK` exists in the project root. It is
   released by writing the file, not by changing code.
"""

#: Tool-argument payloads. They are shared constants because the resume
#: assertion compares the replayed call's idempotency key, which is a hash of
#: exactly these arguments.
CALC_FIX_ARGS: dict[str, Any] = {"path": "calc.py", "content": FIXED_CALC_CONTENT}
TEST_FIX_ARGS: dict[str, Any] = {
    "path": "tests/test_calc.py",
    "content": FIXED_TEST_CONTENT,
}
PIPELINE_FIX_ARGS: dict[str, Any] = {
    "path": "pipeline.py",
    "content": FIXED_PIPELINE_CONTENT,
}
PROBE_ARGS: dict[str, Any] = {"path": "PROBE_OK", "content": "released\n"}
SRC_LIST_ARGS: dict[str, Any] = {"path": "src"}
RUN_TESTS_ARGS: dict[str, Any] = {"project_path": "", "fail_fast": True}


def build_defective_project(root: Path) -> dict[str, Path]:
    """Write the mission project into *root* and return its files."""
    files: dict[str, Path] = {
        "calc.py": root / "calc.py",
        "tests/test_calc.py": root / "tests" / "test_calc.py",
        "tests/test_probe.py": root / "tests" / "test_probe.py",
        "pipeline.py": root / "pipeline.py",
        "report.py": root / "report.py",
        "conftest.py": root / "conftest.py",
        "notes.md": root / "notes.md",
    }
    contents = {
        "calc.py": BROKEN_CALC_CONTENT,
        "tests/test_calc.py": BROKEN_TEST_CONTENT,
        "tests/test_probe.py": PROBE_TEST_CONTENT,
        "pipeline.py": BROKEN_PIPELINE_CONTENT,
        "report.py": REPORT_MODULE_CONTENT,
        "conftest.py": CONFTEST_CONTENT,
        "notes.md": NOTES_CONTENT,
    }
    for key, path in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents[key], encoding="utf-8")
    return files


def missing_defects(root: Path) -> list[str]:
    """Which deliberate defects are still open in *root* right now."""
    open_defects: list[str] = []
    if "return None" in (root / "calc.py").read_text(encoding="utf-8"):
        open_defects.append("defeito 1: calc.add devolve None")
    # The broken assertion is on ``add`` — ``multiply(2, 3) == 6`` is correct
    # and stays in the fixed file, so match the specific expression.
    if "add(2, 3) == 6" in (root / "tests" / "test_calc.py").read_text(encoding="utf-8"):
        open_defects.append("defeito 2: asserção errada em tests/test_calc.py")
    pipeline = (root / "pipeline.py").read_text(encoding="utf-8")
    import_at = pipeline.find("from report import")
    def_at = pipeline.find("def transform")
    if import_at != -1 and def_at != -1 and import_at < def_at:
        open_defects.append("defeito 3: import circular pipeline <-> report")
    return open_defects
