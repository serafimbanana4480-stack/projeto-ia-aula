"""
NEXUS IDE — AI Suggestions Engine

Endpoint e motor para sugestões inline de código estilo GitHub Copilot.
Gera completions contextuais baseados no código atual, linguagem detectada
e histórico de edição.

Integra-se com o LLM backend existente via interface genérica.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


# ── Models ──────────────────────────────────────────────────


@dataclass
class CursorContext:
    """Contexto do cursor no editor."""

    line: int
    column: int
    filename: str
    language: str


@dataclass
class SuggestionRequest:
    """Pedido de sugestão vindo do editor."""

    prefix: str  # código antes do cursor
    suffix: str  # código depois do cursor
    cursor: CursorContext
    recent_edits: list[str] = field(default_factory=list)


@dataclass
class CodeSuggestion:
    """Uma sugestão individual gerada."""

    text: str
    confidence: float  # 0.0–1.0
    kind: Literal["completion", "inline", "block"]
    language: str
    start_line: int
    end_line: int
    explanation: str = ""


@dataclass
class SuggestionResponse:
    """Resposta ao pedido de sugestão."""

    suggestions: list[CodeSuggestion]
    model_used: str = ""
    latency_ms: float = 0.0


# ── Language Detection ─────────────────────────────────────

_EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".r": "r",
    ".sh": "bash",
    ".sql": "sql",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
}


def detect_language(filename: str) -> str:
    """Detecta linguagem a partir do nome do ficheiro."""
    ext = Path(filename).suffix.lower()
    return _EXTENSION_MAP.get(ext, "text")


# ── Prompt Engineering ─────────────────────────────────────

_SYSTEM_PROMPT = """You are an expert code assistant. Given the code context, generate concise, correct, and idiomatic code completions.
Rules:
- Only output code; no explanations unless requested.
- Match the existing code style.
- Respect indentation.
- If completing a function, provide the full function body.
- Do not repeat the prefix already provided."""


def build_prompt(req: SuggestionRequest, max_prefix: int = 2000, max_suffix: int = 500) -> str:
    """Constrói o prompt para o LLM a partir do contexto do editor."""
    prefix = req.prefix[-max_prefix:] if len(req.prefix) > max_prefix else req.prefix
    suffix = req.suffix[:max_suffix] if len(req.suffix) > max_suffix else req.suffix

    lang = req.cursor.language or detect_language(req.cursor.filename)

    prompt_parts = [
        f"Language: {lang}",
        f"File: {req.cursor.filename}",
        "",
        "<|prefix|>",
        prefix,
        "<|suffix|>",
        suffix,
        "<|fim_middle|>",  # fill-in-the-middle marker
    ]

    return "\n".join(prompt_parts)


def parse_suggestions(raw: str, req: SuggestionRequest) -> list[CodeSuggestion]:
    """Extrai sugestões estruturadas do output do LLM."""
    suggestions: list[CodeSuggestion] = []
    lang = req.cursor.language or detect_language(req.cursor.filename)

    # Split by common separators
    blocks = re.split(r"\n---\n|\n```\n", raw.strip())
    blocks = [b.strip().strip("`").strip() for b in blocks if b.strip()]

    for i, block in enumerate(blocks[:3]):  # max 3 suggestions
        lines = block.splitlines()
        start = req.cursor.line
        end = start + len(lines) - 1

        suggestion = CodeSuggestion(
            text=block,
            confidence=max(0.5, 0.95 - i * 0.15),  # decay confidence
            kind="inline" if len(lines) == 1 else "block",
            language=lang,
            start_line=start,
            end_line=end,
        )
        suggestions.append(suggestion)

    return suggestions


# ── Suggestion Engine ───────────────────────────────────────


class AISuggestionEngine:
    """
    Motor de sugestões de código com caching e rate limiting básico.
    """

    def __init__(self, model_backend: Any | None = None):
        self.model = model_backend
        self._cache: dict[str, SuggestionResponse] = {}
        self._cache_hits = 0
        self._cache_misses = 0

    def _cache_key(self, req: SuggestionRequest) -> str:
        """Gera chave de cache determinística."""
        data = req.prefix + "||" + req.suffix + "||" + str(req.cursor.line)
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    async def generate(
        self,
        req: SuggestionRequest,
        max_suggestions: int = 3,
        temperature: float = 0.2,
        use_cache: bool = True,
    ) -> SuggestionResponse:
        """
        Gera sugestões de código para o contexto fornecido.

        Se um backend LLM estiver configurado, usa-o; senão,
        retorna sugestões baseadas em heurísticas simples.
        """
        import time

        start = time.perf_counter()

        key = self._cache_key(req)
        if use_cache and key in self._cache:
            self._cache_hits += 1
            logger.debug("Cache hit for suggestion key %s", key)
            return self._cache[key]

        self._cache_misses += 1

        # Fallback se não há LLM
        if self.model is None:
            suggestions = self._heuristic_suggestions(req)
            response = SuggestionResponse(
                suggestions=suggestions,
                model_used="heuristic",
                latency_ms=(time.perf_counter() - start) * 1000,
            )
            if use_cache:
                self._cache[key] = response
            return response

        # LLM path
        prompt = build_prompt(req)
        try:
            raw_output = await self._call_llm(prompt, temperature)
            suggestions = parse_suggestions(raw_output, req)
            suggestions = suggestions[:max_suggestions]
        except Exception:
            logger.exception("LLM suggestion failed, falling back to heuristic")
            suggestions = self._heuristic_suggestions(req)

        latency = (time.perf_counter() - start) * 1000

        response = SuggestionResponse(
            suggestions=suggestions,
            model_used=getattr(self.model, "model_name", "unknown"),
            latency_ms=latency,
        )

        if use_cache:
            self._cache[key] = response

        return response

    async def _call_llm(self, prompt: str, temperature: float) -> str:
        """Chama o backend LLM. Interface genérica."""
        # Assumimos que o modelo tem um método `generate` ou `chat`
        if hasattr(self.model, "generate"):
            return await self.model.generate(prompt, temperature=temperature)
        elif hasattr(self.model, "chat"):
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            return await self.model.chat(messages, temperature=temperature)
        raise RuntimeError("LLM backend has no 'generate' or 'chat' method")

    def _heuristic_suggestions(self, req: SuggestionRequest) -> list[CodeSuggestion]:
        """Sugestões baseadas em heurísticas quando LLM não está disponível."""
        lang = req.cursor.language or detect_language(req.cursor.filename)
        prefix = req.prefix
        suggestions: list[CodeSuggestion] = []

        # Python: complete function/class/if/try/else/elif
        if lang == "python":
            stripped = prefix.rstrip()
            if stripped.endswith(":"):
                len(prefix) - len(prefix.lstrip())
                next_indent = "    " if stripped.startswith((" ", "\t")) else "    "
                suggestions.append(
                    CodeSuggestion(
                        text=next_indent + "pass",
                        confidence=0.85,
                        kind="inline",
                        language=lang,
                        start_line=req.cursor.line,
                        end_line=req.cursor.line,
                    )
                )
            elif re.search(r"def\s+\w+\([^)]*\)\s*$", prefix):
                suggestions.append(
                    CodeSuggestion(
                        text='    """\n    TODO: document this function\n    """\n    pass',
                        confidence=0.7,
                        kind="block",
                        language=lang,
                        start_line=req.cursor.line,
                        end_line=req.cursor.line + 3,
                    )
                )

        # JS/TS: complete arrow function / async
        elif lang in ("javascript", "typescript"):
            if re.search(r"const\s+\w+\s*=\s*\(?[^)]*\)?\s*=>\s*$", prefix):
                suggestions.append(
                    CodeSuggestion(
                        text=" {\n    \n};",
                        confidence=0.75,
                        kind="block",
                        language=lang,
                        start_line=req.cursor.line,
                        end_line=req.cursor.line + 2,
                    )
                )

        # Generic: close brackets
        last_char = prefix[-1:] if prefix else ""
        pairs = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
        if last_char in pairs:
            suggestions.append(
                CodeSuggestion(
                    text=pairs[last_char],
                    confidence=0.99,
                    kind="inline",
                    language=lang,
                    start_line=req.cursor.line,
                    end_line=req.cursor.line,
                )
            )

        return suggestions

    def clear_cache(self) -> None:
        """Limpa cache de sugestões."""
        self._cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0

    def cache_stats(self) -> dict[str, Any]:
        """Estatísticas do cache."""
        total = self._cache_hits + self._cache_misses
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "total": total,
            "hit_rate": self._cache_hits / total if total else 0.0,
            "entries": len(self._cache),
        }


# ── FastAPI Router (opcional, para integração) ──────────────

try:
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/ai/suggestions", tags=["AI Suggestions"])
    _engine: AISuggestionEngine | None = None

    def set_engine(engine: AISuggestionEngine) -> None:
        global _engine
        _engine = engine

    @router.post("/complete", response_model=SuggestionResponse)
    async def complete_code(request: SuggestionRequest) -> SuggestionResponse:
        if _engine is None:
            raise HTTPException(status_code=503, detail="Suggestion engine not initialized")
        return await _engine.generate(request)

    @router.get("/cache/stats")
    async def cache_stats() -> dict[str, Any]:
        if _engine is None:
            raise HTTPException(status_code=503, detail="Suggestion engine not initialized")
        return _engine.cache_stats()

    @router.delete("/cache")
    async def clear_cache() -> dict[str, str]:
        if _engine is None:
            raise HTTPException(status_code=503, detail="Suggestion engine not initialized")
        _engine.clear_cache()
        return {"status": "cleared"}

except ImportError:
    # FastAPI não instalado — router não disponível
    router = None  # type: ignore


# ── Instância global padrão ─────────────────────────────────

suggestion_engine = AISuggestionEngine()


# ── Demo ────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    async def demo():
        req = SuggestionRequest(
            prefix='def fibonacci(n):\n    """Return nth Fibonacci number."""\n    ',
            suffix="\n\n# main",
            cursor=CursorContext(line=3, column=4, filename="math.py", language="python"),
        )
        resp = await suggestion_engine.generate(req)
        for s in resp.suggestions:
            print(f"[{s.kind}] confidence={s.confidence:.2f}")
            print(s.text)
            print("---")

    asyncio.run(demo())
