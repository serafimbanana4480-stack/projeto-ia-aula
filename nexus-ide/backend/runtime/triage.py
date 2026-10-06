"""Deterministic request triage: who should own this turn.

Phase 2 proved the planner was the single biggest source of dead time: a
16k-token generation had to finish (and validate) before a single tool ran.
Phase 3 removes it from the critical path for the requests that never needed
it.

Triage runs **before** any model call and uses only the text of the request,
so it costs microseconds and cannot itself delay
``TIME_TO_FIRST_ACTION``. It answers one question:

    Does this turn need a *plan*, or does it need an *agent that starts
    working*?

The default answer is ``DIRECT`` — the primary agent owns the task, calls
tools itself, and never spawns PLANNER/ARCHITECT/CODER. ``PLANNED`` is
reserved for requests that genuinely describe several dependent phases, and
``CONVERSATIONAL`` for turns where a tool would add nothing.

Escalation is one-way and late: a ``DIRECT`` run that discovers real
multi-phase work can still ask for delegation through
:class:`backend.runtime.spawn_policy.SpawnPolicy`. Starting planned and
discovering the task was trivial, by contrast, is unrecoverable — the user
has already waited.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "RequestClass",
    "TriageDecision",
    "triage_request",
]


class RequestClass(StrEnum):
    #: Answerable from the conversation. No tools, no project state.
    CONVERSATIONAL = "conversational"
    #: One agent, its tools, and a verification step. The default.
    DIRECT = "direct"
    #: Several dependent phases over a scope worth planning first.
    PLANNED = "planned"


@dataclass(frozen=True)
class TriageDecision:
    """Why this turn was routed the way it was — quotable in the UI."""

    request_class: RequestClass
    reason: str
    signals: tuple[str, ...] = ()
    #: Iteration budget for the primary loop. ``0`` means "runtime default".
    max_iterations: int = 0
    #: Run the verification phase even when no file was changed.
    force_verification: bool = False
    #: The request names no target and no scope ("faz", "arranja isto"). The
    #: honest move is one short clarifying question, not a project-wide sweep
    #: against a guess (audit 2026-08-16, P7).
    needs_clarification: bool = False

    @property
    def needs_planner(self) -> bool:
        return self.request_class is RequestClass.PLANNED

    @property
    def uses_tools(self) -> bool:
        return self.request_class is not RequestClass.CONVERSATIONAL

    def to_dict(self) -> dict[str, object]:
        return {
            "class": self.request_class.value,
            "reason": self.reason,
            "signals": list(self.signals),
            "needs_planner": self.needs_planner,
            "max_iterations": self.max_iterations,
            "needs_clarification": self.needs_clarification,
        }


def _words(pattern_words: tuple[str, ...]) -> re.Pattern[str]:
    """Word-boundary alternation. Substring matching produced false hits:
    ``testar`` inside ``contestar``, ``add`` inside ``address``."""
    escaped = sorted((re.escape(word) for word in pattern_words), key=len, reverse=True)
    return re.compile(r"(?<![\w-])(?:" + "|".join(escaped) + r")(?![\w-])", re.IGNORECASE)


# A phase marker is a verb that names a *stage* of work. Two or more distinct
# stages in one sentence is the signal that a plan may be worth its cost.
_PHASE_ANALYSE = _words(
    (
        "analisa", "analisar", "analise", "audita", "auditar", "auditoria",
        "investiga", "investigar", "diagnostica", "diagnosticar", "mapeia",
        "mapear", "levanta", "levantar",
        "analyse", "analyze", "audit", "investigate", "diagnose", "map",
    )
)
_PHASE_CHANGE = _words(
    (
        "implementa", "implementar", "corrige", "corrigir", "refatora",
        "refatorar", "reescreve", "reescrever", "migra", "migrar", "cria",
        "criar", "constroi", "construir", "adiciona", "adicionar", "remove",
        "remover", "integra", "integrar",
        "implement", "fix", "refactor", "rewrite", "migrate", "create",
        "build", "add", "remove", "integrate",
    )
)
_PHASE_VERIFY = _words(
    (
        "testa", "testar", "testes", "valida", "validar", "verifica",
        "verificar", "confirma", "confirmar", "cobertura",
        "test", "tests", "validate", "verify", "confirm", "coverage",
    )
)
_PHASE_REPORT = _words(
    (
        "documenta", "documentar", "reporta", "reportar", "relatorio",
        "relatório", "resume", "resumir", "sumariza", "sumarizar",
        "document", "report", "summarise", "summarize",
    )
)
_PHASE_RES = (_PHASE_ANALYSE, _PHASE_CHANGE, _PHASE_VERIFY, _PHASE_REPORT)
_PHASE_NAMES = ("analyse", "change", "verify", "report")

#: Any of these means the turn touches the project, so the primary agent
#: needs its tools even if the sentence is short.
_PROJECT_TARGET = _words(
    (
        "ficheiro", "ficheiros", "arquivo", "arquivos", "pasta", "diretoria",
        "diretorio", "diretório", "repositorio", "repositório", "projeto",
        "codigo", "código", "modulo", "módulo", "funcao", "função", "classe",
        "teste", "testes", "backend", "frontend", "endpoint", "rota", "api",
        "build", "lint", "bug", "erro", "excecao", "exceção", "stacktrace",
        "traceback", "log", "logs", "dependencia", "dependência",
        "file", "files", "folder", "directory", "repository", "project",
        "code", "module", "function", "class", "test", "tests", "route",
        "error", "exception", "dependency", "package",
    )
)

#: Verbs that imply the agent must *do* something, not just answer.
_ACTION_VERB = _words(
    (
        "corrige", "corrigir", "arranja", "arranjar", "implementa",
        "implementar", "cria", "criar", "escreve", "escrever", "adiciona",
        "adicionar", "remove", "remover", "apaga", "apagar", "altera",
        "alterar", "muda", "mudar", "atualiza", "atualizar", "refatora",
        "refatorar", "renomeia", "renomear", "corre", "correr", "executa",
        "executar", "testa", "testar", "instala", "instalar", "configura",
        "configurar", "analisa", "analisar", "audita", "auditar", "le",
        "ler", "abre", "abrir", "procura", "procurar", "encontra",
        "encontrar", "verifica", "verificar", "otimiza", "otimizar",
        "fix", "implement", "create", "write", "add", "remove", "delete",
        "change", "update", "refactor", "rename", "run", "execute", "test",
        "install", "configure", "analyse", "analyze", "audit", "read",
        "open", "search", "find", "check", "verify", "optimize", "make",
        "ver", "vê", "ve", "revê", "reve", "revisa", "revisar", "olha",
        "olhar", "inspeciona", "inspecionar", "review", "inspect", "look",
    )
)

#: Question openers. A question with no action verb is conversational.
_QUESTION_OPENER = _words(
    (
        "o", "que", "qual", "quais", "quando", "quem", "onde", "porque",
        "porquê", "porque", "como", "explica", "explicar", "diz", "dizer",
        "sabes", "consegues", "podes",
        "what", "which", "when", "who", "where", "why", "how", "explain",
        "tell", "do", "does", "can", "could", "is", "are", "should",
    )
)

#: Greetings, thanks and acknowledgements. "olá" used to be classified DIRECT,
#: which triggered a full project scan plus two model calls to say hello
#: (audit 2026-08-16, P7).
_SMALLTALK_RE = re.compile(
    r"^\s*(?:ol[áa]|oi|hey|hi|hello|bom\s+dia|boa\s+tarde|boa\s+noite|tudo\s+bem|"
    r"obrigad[oa]|thanks|thank\s+you|valeu|fixe|ok|okay|certo|perfeito|bo[am]\b|"
    r"(?:t[áa]s|est[áa]s)(?:\s+por)?\s+a[ií]|"
    r"tchau|adeus|bye|good\s+(?:morning|afternoon|evening|night))"
    r"[\s!.,;:)?]*$",
    re.IGNORECASE,
)

#: An explicit request for a plan, in words rather than a slash command.
_PLAN_REQUEST_RE = re.compile(
    r"\b(?:plano|planeamento|planejamento|roadmap|estrat[ée]gia|passo\s+a\s+passo|"
    r"plan|strategy|step[-\s]by[-\s]step)\b",
    re.IGNORECASE,
)

#: Referentless commands: an imperative with no object at all.
_AMBIGUOUS_RE = re.compile(
    r"^\s*(?:isso|isto|esse|essa|aquilo|faz|fa[çc]a|arranja\s+(?:isso|isto)?|"
    r"corrige\s+(?:isso|isto)?|continua|segue|vai|do\s+it|fix\s+(?:it|this)?|go)"
    r"[\s!.,;:?]*$",
    re.IGNORECASE,
)

_EXPLICIT_PLAN_RE = re.compile(r"^\s*/(?:plan|mission|swarm|auto_swarm)\b", re.IGNORECASE)
_EXPLICIT_DIRECT_RE = re.compile(r"^\s*/(?:do|fix|go|now)\b", re.IGNORECASE)

#: Modes the UI can pin. They win over any heuristic.
_MODE_TO_CLASS = {
    "chat": RequestClass.CONVERSATIONAL,
    "ask": RequestClass.CONVERSATIONAL,
    "fast": RequestClass.CONVERSATIONAL,
    "assisted": RequestClass.DIRECT,
    "coder": RequestClass.DIRECT,
    "debug": RequestClass.DIRECT,
    "reviewer": RequestClass.DIRECT,
    "analyst": RequestClass.DIRECT,
    "deep": RequestClass.DIRECT,
    "plan": RequestClass.PLANNED,
    "mission": RequestClass.PLANNED,
    "swarm": RequestClass.PLANNED,
    "auto_swarm": RequestClass.PLANNED,
}

#: Long, multi-phase requests are the only automatic route to the planner.
#: A request naming three distinct stages IS a multi-phase request, whatever
#: its length: "audita o repositório, implementa as correções, valida com
#: testes e escreve um relatório" is 11 words and four phases. Requiring 25
#: words made PLANNED practically unreachable, which left the whole planner
#: path dead in normal use (audit 2026-08-16, P7).
_PLANNED_MIN_WORDS = 10
_PLANNED_MIN_PHASES = 3
#: Two phases still need a plan when the request is substantial.
_PLANNED_TWO_PHASE_MIN_WORDS = 30


def triage_request(
    message: str,
    *,
    requested_mode: str = "auto",
    has_project: bool = False,
) -> TriageDecision:
    """Classify one user turn. Pure function: no I/O, no model call."""
    text = (message or "").strip()
    mode = (requested_mode or "auto").strip().lower()

    if not text:
        return TriageDecision(
            RequestClass.CONVERSATIONAL, "pedido vazio", ("empty",), max_iterations=1
        )

    if _EXPLICIT_PLAN_RE.match(text):
        return TriageDecision(
            RequestClass.PLANNED, "o utilizador pediu explicitamente um plano", ("explicit:/plan",)
        )
    if _EXPLICIT_DIRECT_RE.match(text):
        return TriageDecision(
            RequestClass.DIRECT,
            "o utilizador pediu execução imediata",
            ("explicit:/do",),
            force_verification=True,
        )

    if mode not in {"auto", "agent", ""} and mode in _MODE_TO_CLASS:
        pinned = _MODE_TO_CLASS[mode]
        return TriageDecision(
            pinned,
            f"modo fixado pela interface: {mode}",
            (f"mode:{mode}",),
            max_iterations=2 if pinned is RequestClass.CONVERSATIONAL else 0,
        )

    if _SMALLTALK_RE.match(text):
        return TriageDecision(
            RequestClass.CONVERSATIONAL,
            "saudação ou agradecimento: nada a executar",
            ("smalltalk",),
            max_iterations=1,
        )

    lowered = text.lower()
    word_count = len(text.split())
    phases = tuple(
        name for name, regex in zip(_PHASE_NAMES, _PHASE_RES, strict=True) if regex.search(lowered)
    )
    has_action = bool(_ACTION_VERB.search(lowered))
    has_target = bool(_PROJECT_TARGET.search(lowered))
    is_question = text.rstrip().endswith("?") or bool(
        _QUESTION_OPENER.match(lowered.lstrip("¿ ").split(" ", 1)[0])
    )

    signals: list[str] = [f"words:{word_count}"]
    signals.extend(f"phase:{name}" for name in phases)
    if has_action:
        signals.append("action_verb")
    if has_target:
        signals.append("project_target")
    if is_question:
        signals.append("question")
    if has_project:
        signals.append("project_selected")

    # Only a genuinely multi-phase, substantial request is worth a plan.
    if len(phases) >= _PLANNED_MIN_PHASES and word_count >= _PLANNED_MIN_WORDS:
        return TriageDecision(
            RequestClass.PLANNED,
            f"{len(phases)} fases distintas ({', '.join(phases)}) num pedido de "
            f"{word_count} palavras",
            tuple(signals),
        )

    if len(phases) >= 2 and word_count >= _PLANNED_TWO_PHASE_MIN_WORDS:
        return TriageDecision(
            RequestClass.PLANNED,
            f"pedido longo ({word_count} palavras) com {len(phases)} fases "
            f"({', '.join(phases)})",
            (*signals, "long_two_phase"),
        )

    # The user asking for a plan, in words, is as explicit as "/plan".
    if _PLAN_REQUEST_RE.search(lowered) and (word_count >= 8 or phases):
        return TriageDecision(
            RequestClass.PLANNED,
            "o utilizador pediu um plano por palavras",
            (*signals, "plan_request"),
        )

    # A bare imperative with no object: acting on a guess here is how a
    # one-word message turned into a project-wide sweep.
    if _AMBIGUOUS_RE.match(text) or (word_count <= 3 and not has_target and has_action):
        return TriageDecision(
            RequestClass.DIRECT,
            "pedido ambíguo sem alvo: pede uma clarificação curta antes de agir",
            (*signals, "ambiguous"),
            max_iterations=1,
            needs_clarification=True,
        )

    # A question with no action verb and no project target needs no tools.
    if is_question and not has_action and not has_target:
        return TriageDecision(
            RequestClass.CONVERSATIONAL,
            "pergunta informativa sem alvo no projeto",
            tuple(signals),
            max_iterations=2,
        )

    # Everything else: the primary agent owns it. This is the wide default,
    # and deliberately so — it is the only branch that starts working
    # immediately.
    reason = (
        "tarefa direta: o agente primário executa e verifica sem planeamento prévio"
        if has_action or has_target
        else "pedido curto sem sinais de planeamento; o agente primário responde e age se preciso"
    )
    return TriageDecision(
        RequestClass.DIRECT,
        reason,
        tuple(signals),
        force_verification=bool(phases and "verify" in phases),
    )
