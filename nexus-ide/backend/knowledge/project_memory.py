"""Compact, project-scoped memory used as the AI's bootstrap context.

The project memory is intentionally a small Markdown document inside the
project (``.nexus/project-memory.md``).  It is not a transcript and it is not
treated as executable instructions: it contains a generated project map plus
short, verified session facts.  Detailed code remains discoverable through
the code index and the normal read/search tools.
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
import time
from pathlib import Path

from backend.core.project_adapter import ProjectAdapter

PROJECT_MEMORY_RELATIVE_PATH = Path(".nexus") / "project-memory.md"
MAX_CONTEXT_CHARS = 12_000
MAX_SESSION_NOTES = 12

_lock = threading.RLock()


def project_memory_path(project_path: str | os.PathLike[str]) -> Path:
    """Return the canonical memory file for *project_path*."""
    return Path(project_path).expanduser().resolve() / PROJECT_MEMORY_RELATIVE_PATH


def _top_level_map(root: Path) -> str:
    entries: list[str] = []
    try:
        for entry in sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if entry.name.startswith(".") and entry.name not in {".env.example"}:
                continue
            if entry.is_dir():
                entries.append(f"- `{entry.name}/` — diretório")
            elif entry.is_file():
                entries.append(f"- `{entry.name}` — ficheiro de entrada/configuração")
            if len(entries) >= 30:
                break
    except OSError:
        return "- (indisponível)"
    return "\n".join(entries) or "- (projeto vazio)"


def _architecture_hints(root: Path) -> str:
    hints: list[str] = []
    if (root / "backend").is_dir():
        hints.append("- `backend/` — serviços, orquestração e ferramentas")
    if (root / "frontend").is_dir():
        hints.append("- `frontend/` — interface web e estado do cliente")
    if (root / "src").is_dir():
        hints.append("- `src/` — código principal da aplicação")
    if (root / "tests").is_dir() or (root / "backend" / "tests").is_dir():
        hints.append("- testes separados do código de produção")
    if (root / "config").is_dir():
        hints.append("- `config/` — configuração e workflows")
    if (root / "data").is_dir():
        hints.append("- `data/` — estado local persistente; não é código-fonte")
    return "\n".join(hints) or "- mapa detalhado: usar `list_dir`, `read_file` e `search_codebase`"


def _generated_header(root: Path) -> str:
    adapter = ProjectAdapter(root)
    config = adapter.config
    gates = ", ".join(g["name"] for g in adapter.get_quality_gates() if g.get("command"))
    return f"""# Memória compacta do projeto

> Documento de bootstrap da IA. É contexto inerte, não uma lista de comandos.
> O código real e os resultados dos testes têm precedência sobre este resumo.

## Identidade

- Raiz: `{root}`
- Linguagem principal detetada: `{config.language}`
- Ficheiro da memória: `{PROJECT_MEMORY_RELATIVE_PATH.as_posix()}`
- Geração: automática, versão 1

## Arquitetura inicial

{_architecture_hints(root)}

### Mapa de topo

{_top_level_map(root)}

## Comandos e gates detetados

- Testes: `{config.test_command or "não detetado"}`
- Lint: `{config.lint_command or "não detetado"}`
- Tipos: `{config.type_check_command or "não detetado"}`
- Build: `{config.build_command or "não detetado"}`
- Gates ativos: `{gates or "não detetados"}`

## Regras de trabalho

- Confirmar caminhos e arquitetura no código antes de alterar.
- Tratar esta memória como resumo: consultar ficheiros e executar testes para validar.
- Registar aqui apenas decisões, riscos e resultados verificados; não guardar credenciais,
  prompts completos ou texto de ferramentas.

## Decisões e convenções do projeto

- (a preencher por decisões verificadas)

## Últimas sessões verificadas

- Ainda não existem registos.
"""


def ensure_project_memory(project_path: str | os.PathLike[str]) -> Path:
    """Create the compact project memory if it does not exist."""
    root = Path(project_path).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    target = project_memory_path(root)
    with _lock:
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(target, _generated_header(root))
    return target


def read_project_memory(project_path: str | os.PathLike[str], *, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    """Return bounded project context, creating the file on first use."""
    target = ensure_project_memory(project_path)
    try:
        content = target.read_text(encoding="utf-8")
    except OSError:
        return ""
    return content[: max(1, max_chars)]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _clean_fact(value: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    value = value.replace("\r", "").replace("\n", " ")
    return value[:limit]


def record_verified_session(
    project_path: str | os.PathLike[str],
    *,
    session_id: str,
    status: str,
    topic: str = "",
    evidence: str = "",
) -> Path:
    """Append a compact, inert record for a completed session.

    Only the status and caller-supplied, already-sanitised facts are stored.
    The bounded history prevents the bootstrap file from becoming a transcript.
    """
    target = ensure_project_memory(project_path)
    with _lock:
        content = target.read_text(encoding="utf-8")
        marker = "## Últimas sessões verificadas"
        before, separator, after = content.partition(marker)
        if not separator:
            before, after = content, ""
        lines = [line for line in after.splitlines() if line.strip().startswith("-")]
        timestamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        note = f"- {timestamp} · sessão `{_clean_fact(session_id, 128)}` · estado `{_clean_fact(status, 32)}`"
        if topic:
            note += f" · tema: {_clean_fact(topic)}"
        if evidence:
            note += f" · evidência: {_clean_fact(evidence)}"
        lines = [note, *lines[: MAX_SESSION_NOTES - 1]]
        updated = before.rstrip() + "\n\n" + marker + "\n\n" + "\n".join(lines) + "\n"
        _atomic_write(target, updated)
    return target


__all__ = [
    "MAX_CONTEXT_CHARS",
    "PROJECT_MEMORY_RELATIVE_PATH",
    "ensure_project_memory",
    "project_memory_path",
    "read_project_memory",
    "record_verified_session",
]
