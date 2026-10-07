"""Deterministic stress suite for the NEXUS backend hot paths.

Thousands of fast, fully offline iterations over the five most critical
components, asserting invariants instead of single outcomes:

1. Triage fuzz            — ~5000 synthetic PT/EN messages into
                            ``runtime.triage.triage_request`` (pure function).
2. Event ordering fuzz    — ~3000 scrambled/duplicated/gapped events through
                            ``runtime.events.dedupe_and_order`` and a Python
                            port of ``frontend/lib/eventOrdering.ts``, plus
                            concurrent emission through ``RunEventStream``.
3. Registry timeout/breaker fuzz — 2000 successful dummy-tool executions,
                            300 consecutive failures driving the circuit
                            breaker open and its documented recovery path,
                            and the hard-timeout path.
4. Analyzer smoke massivo — 1500 direct ``analyze_project`` calls over a tiny
                            tmp fixture; identical calls must agree exactly.
5. Embeddings keyword fallback — 2500 offline ``_keyword_search`` queries over
                            a small in-memory index; no provider, no network.

Everything is seeded (``SEED``), so the suite is reproducible run to run.
Target wall time is well under three minutes. Iteration counts are reported
in the terminal summary section printed by ``conftest.py``.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from pathlib import Path

import pytest

import backend.tools.embeddings as embeddings_module
from backend.runtime.events import (
    RunEventStream,
    RuntimeEvent,
    RuntimeEventType,
    dedupe_and_order,
)
from backend.runtime.triage import RequestClass, TriageDecision, triage_request
from backend.tools.embeddings import CodeChunk, _keyword_search
from backend.tools.project_analyzer import analyze_project
from backend.tools.registry import (
    TOOL_MAX_CONSECUTIVE_FAILURES,
    ToolSpec,
    execute_tool,
    register_tool,
    reset_tool_failure,
    reset_tool_failures,
    tool_failure_count,
)

SEED = 20260825

TRIAGE_TOTAL_MESSAGES = 5000
TRIAGE_PER_CASE = 5

RUN_IDS = ("run-alpha", "run-beta", "run-gamma", "run-delta")
EVENT_ORDER_CASES = 110
EVENT_SEQS_PER_BATCH = 27
STREAM_CONCURRENCY_CASES = 20
STREAM_WORKERS = 3
STREAM_EMISSIONS_PER_WORKER = 30

REGISTRY_OK_EXECUTIONS = 2000
REGISTRY_OK_PER_CASE = 20
BREAKER_STREAK_CASES = 30
BREAKER_STREAK_EXECUTIONS = 10
TIMEOUT_PATH_CASES = 4
TIMEOUT_PATH_EXECUTIONS = 10
STRESS_TOOL_TIMEOUT_SECONDS = 0.02

ANALYZER_CALLS = 1500
ANALYZER_PER_CASE = 10

EMBED_SEARCHES = 2500
EMBED_PER_CASE = 10

pytestmark = pytest.mark.stress


def _count(request: pytest.FixtureRequest, key: str, amount: int = 1) -> None:
    counters: dict[str, int] = request.config._stress_counters
    counters[key] = counters.get(key, 0) + amount


# ---------------------------------------------------------------------------
# 1. Triage fuzz
# ---------------------------------------------------------------------------

_CONV_PT = (
    "olá", "oi tudo bem?", "obrigado pela ajuda", "que é um closure em python?",
    "explica como funciona async await", "quem escreveu este código?",
    "qual a diferença entre lista e tuplo?", "como se diz hello em português?",
    "o que achas do novo design?", "bom dia",
)
_CONV_EN = (
    "hey there", "thanks a lot", "what is a monad?", "explain how decorators work",
    "who invented python?", "which database should I pick?",
    "how does garbage collection work?", "good morning", "is this correct?",
    "tell me a joke",
)
_DIRECT_PT = (
    "corrige o bug no ficheiro main.py", "implementa a função parse_config no módulo utils",
    "adiciona um teste para o endpoint /health", "remove o import não usado em app.py",
    "corre os testes do backend", "renomeia a variável tmp para buffer em auth.py",
    "escreve documentação para a rota /login do projeto",
)
_DIRECT_EN = (
    "fix the failing test in test_api.py", "add a retry policy to the http client module",
    "create a migration for the users table", "refactor the auth service class",
    "run lint on the project code", "update the README with install steps",
)
_PLANNED_PT = (
    "audita o repositório todo, implementa as correções necessárias e valida com testes",
    "analisa o desempenho do pipeline, otimiza as queries lentas e documenta no relatório",
    "/plan migrar a base de dados, atualizar os modelos e escrever testes de regressão",
)
_PLANNED_EN = (
    "investigate the memory leak, fix the worker pool bug and validate coverage with tests",
    "map the api surface, implement versioned routes for missing endpoints and confirm tests",
)
_JUNK = (
    "", "   ", "\t\n  ", "?", "!!!", "...", "faz isso", "arranja isto", "do it", "go",
    "fix it", "continua", "ok", "certo", "olá 🤖", "🚀🔥💡", "a" * 300, "\n",
)
_EMOJIS = ("🚀", "🔥", "✅", "💡", "🙏", "👍", "😅", "🤖")
_MODES = ("auto", "auto", "auto", "auto", "auto", "auto", "agent", "chat", "coder", "plan")

_TRIAGE_POOLS = {
    "conv_pt": _CONV_PT,
    "conv_en": _CONV_EN,
    "direct_pt": _DIRECT_PT,
    "direct_en": _DIRECT_EN,
    "planned_pt": _PLANNED_PT,
    "planned_en": _PLANNED_EN,
    "junk": _JUNK,
}

_TRIAGE_DECISION_KEYS = {
    "class",
    "reason",
    "signals",
    "needs_planner",
    "max_iterations",
    "needs_clarification",
}


def _mutate(rng: random.Random, text: str) -> str:
    out = text
    if rng.random() < 0.25:
        out = out.upper()
    if rng.random() < 0.25:
        out = f"   {out}   "
    if rng.random() < 0.25:
        out = f"{out} {rng.choice(_EMOJIS)}{rng.choice(_EMOJIS)}"
    if rng.random() < 0.15:
        out = out.replace(" ", "  ", 1)
    if rng.random() < 0.10:
        out = f"{out}?!"
    return out


def _synthetic_triage_case(rng: random.Random) -> tuple[str, str, bool]:
    pool = _TRIAGE_POOLS[rng.choice(tuple(_TRIAGE_POOLS))]
    message = _mutate(rng, rng.choice(pool))
    mode = rng.choice(_MODES)
    has_project = rng.random() < 0.5
    return message, mode, has_project


_ALL_TRIAGE_MESSAGES = []


def _build_triage_messages() -> list[tuple[str, str, bool]]:
    rng = random.Random(SEED)
    return [_synthetic_triage_case(rng) for _ in range(TRIAGE_TOTAL_MESSAGES)]


_ALL_TRIAGE_MESSAGES = _build_triage_messages()
_TRIAGE_BATCHES = [
    tuple(_ALL_TRIAGE_MESSAGES[i : i + TRIAGE_PER_CASE])
    for i in range(0, len(_ALL_TRIAGE_MESSAGES), TRIAGE_PER_CASE)
]


def _assert_triage_invariants(message: str, mode: str, has_project: bool) -> TriageDecision:
    first = triage_request(message, requested_mode=mode, has_project=has_project)
    assert isinstance(first, TriageDecision)
    assert isinstance(first.request_class, RequestClass)
    assert isinstance(first.reason, str) and first.reason
    assert isinstance(first.signals, tuple)
    assert all(isinstance(signal, str) for signal in first.signals)
    assert isinstance(first.max_iterations, int) and first.max_iterations >= 0
    assert isinstance(first.force_verification, bool)
    assert isinstance(first.needs_clarification, bool)
    payload = first.to_dict()
    assert set(payload.keys()) == _TRIAGE_DECISION_KEYS
    second = triage_request(message, requested_mode=mode, has_project=has_project)
    assert first == second
    return first


@pytest.mark.parametrize(
    "batch", _TRIAGE_BATCHES, ids=[f"fuzz-{i}" for i in range(len(_TRIAGE_BATCHES))]
)
def test_stress_triage_fuzz(batch: tuple[tuple[str, str, bool], ...], request) -> None:
    for message, mode, has_project in batch:
        decision = _assert_triage_invariants(message, mode, has_project)
        assert decision.needs_planner == (decision.request_class is RequestClass.PLANNED)
        _count(request, "triage_fuzz_messages")


def test_triage_fuzz_corpus_covers_every_class() -> None:
    seen = {
        _assert_triage_invariants(message, mode, has_project).request_class
        for message, mode, has_project in _ALL_TRIAGE_MESSAGES[:400]
    }
    assert seen == set(RequestClass)


# ---------------------------------------------------------------------------
# 2. Event ordering fuzz
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _MirrorEvent:
    run_id: str
    seq: int
    event_id: str


class _RunEventBufferMirror:
    """Python port of ``frontend/lib/eventOrdering.ts::RunEventBuffer``."""

    def __init__(self) -> None:
        self.seen: set[str] = set()
        self.ordered: list[_MirrorEvent] = []
        self.run_id: str | None = None
        self.highest_seq = 0

    def push(self, event: RuntimeEvent) -> bool:
        if self.run_id is None:
            self.run_id = event.run_id
        elif event.run_id != self.run_id:
            return False
        if event.event_id in self.seen:
            return False
        self.seen.add(event.event_id)
        index = len(self.ordered)
        while index > 0 and self.ordered[index - 1].seq > event.seq:
            index -= 1
        self.ordered.insert(index, event)
        self.highest_seq = max(self.highest_seq, event.seq)
        return True

    def ordered_keys(self) -> list[tuple[str, int]]:
        return [(event.run_id, event.seq) for event in self.ordered]

    def missing_seqs(self) -> list[int]:
        present = {event.seq for event in self.ordered}
        return [seq for seq in range(1, self.highest_seq + 1) if seq not in present]


def _scrambled_event_batch(
    rng: random.Random, run_id: str, n_seqs: int
) -> tuple[list[RuntimeEvent], frozenset[int]]:
    dropped = {seq for seq in range(1, n_seqs + 1) if rng.random() < 0.08}
    batch: list[RuntimeEvent] = []
    for seq in range(1, n_seqs + 1):
        if seq in dropped:
            continue
        event = RuntimeEvent(
            run_id=run_id,
            seq=seq,
            type=RuntimeEventType.STATUS_UPDATE,
            event_id=f"{run_id}:{seq}",
            ts=1_000_000.0 + seq,
        )
        batch.append(event)
        if rng.random() < 0.18:
            batch.append(
                RuntimeEvent(
                    run_id=run_id,
                    seq=seq,
                    type=RuntimeEventType.STATUS_UPDATE,
                    event_id=event.event_id,
                    ts=event.ts,
                )
            )
    rng.shuffle(batch)
    return batch, frozenset(dropped)


def _build_event_batches() -> list[tuple[list[RuntimeEvent], frozenset[int]]]:
    rng = random.Random(SEED + 7)
    return [
        _scrambled_event_batch(rng, RUN_IDS[idx % len(RUN_IDS)], EVENT_SEQS_PER_BATCH)
        for idx in range(EVENT_ORDER_CASES)
    ]


_EVENT_BATCHES = _build_event_batches()


@pytest.mark.parametrize("case_idx", range(len(_EVENT_BATCHES)))
def test_stress_event_ordering_fuzz(case_idx: int, request) -> None:
    batch, expected_gaps = _EVENT_BATCHES[case_idx]
    ordered = dedupe_and_order(batch)
    keys = [event.order_key for event in ordered]
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))
    assert {event.event_id for event in ordered} == {event.event_id for event in batch}
    seqs_present = {event.seq for event in ordered}
    expected_present = set(range(1, EVENT_SEQS_PER_BATCH + 1)) - set(expected_gaps)
    assert seqs_present == expected_present
    mirror = _RunEventBufferMirror()
    for event in batch:
        mirror.push(event)
    assert mirror.ordered_keys() == keys
    highest_received = max(seqs_present)
    visible_gaps = [gap for gap in sorted(expected_gaps) if gap < highest_received]
    assert mirror.missing_seqs() == visible_gaps
    _count(request, "event_ordering_raw_events", len(batch))


def test_event_ordering_mixed_runs_isolated_per_run() -> None:
    rng = random.Random(SEED + 11)
    mixed: list[RuntimeEvent] = []
    for run_id in RUN_IDS[:2]:
        batch, _ = _scrambled_event_batch(rng, run_id, 15)
        mixed.extend(batch)
    rng.shuffle(mixed)
    ordered = dedupe_and_order(mixed)
    assert len({event.order_key for event in ordered}) == len(ordered)
    for run_id in RUN_IDS[:2]:
        group = [event.seq for event in ordered if event.run_id == run_id]
        assert group == sorted(group)
        mirror = _RunEventBufferMirror()
        for event in (event for event in mixed if event.run_id == run_id):
            mirror.push(event)
        assert [key[1] for key in mirror.ordered_keys()] == group
    guard = _RunEventBufferMirror()
    first = mixed[0]
    assert guard.push(first) is True
    foreign = next(event for event in mixed if event.run_id != first.run_id)
    assert guard.push(foreign) is False


@pytest.mark.parametrize("case_idx", range(STREAM_CONCURRENCY_CASES))
async def test_stress_stream_concurrent_emission_total_order(case_idx: int, request) -> None:
    stream = RunEventStream(f"stress-stream-{case_idx}")

    async def emit_burst(worker: int) -> None:
        for step in range(STREAM_EMISSIONS_PER_WORKER):
            stream.emit(RuntimeEventType.MESSAGE_DELTA, worker=worker, step=step)

    await asyncio.gather(*(emit_burst(worker) for worker in range(STREAM_WORKERS)))
    total = STREAM_WORKERS * STREAM_EMISSIONS_PER_WORKER
    history = stream.history()
    assert stream.last_seq == total
    assert [event.seq for event in history] == list(range(1, total + 1))
    assert len({event.event_id for event in history}) == total
    cut = case_idx % total
    replayed = stream.replay(after_seq=cut)
    assert [event.seq for event in replayed] == list(range(cut + 1, total + 1))
    _count(request, "stream_events_emitted", total)


# ---------------------------------------------------------------------------
# 3. Registry tool timeout/breaker fuzz
# ---------------------------------------------------------------------------

STRESS_TOOL_NAMES = ("stress_echo_tool", "stress_boom_tool", "stress_slow_tool")


@pytest.fixture()
def stress_registry(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    import backend.tools.registry as registry_module

    handler_calls = {"boom": 0, "slow": 0}

    async def echo_handler() -> dict[str, object]:
        return {"ok": True}

    async def boom_handler() -> dict[str, object]:
        handler_calls["boom"] += 1
        raise RuntimeError("stress boom")

    async def slow_handler() -> dict[str, object]:
        handler_calls["slow"] += 1
        await asyncio.sleep(5)

    monkeypatch.setattr(registry_module, "log_tool_execution", lambda **kwargs: "")
    specs = [
        ToolSpec(
            name="stress_echo_tool",
            description="stress suite ok tool",
            schema={"type": "object"},
            handler=echo_handler,
        ),
        ToolSpec(
            name="stress_boom_tool",
            description="stress suite failing tool",
            schema={"type": "object"},
            handler=boom_handler,
        ),
        ToolSpec(
            name="stress_slow_tool",
            description="stress suite slow tool",
            schema={"type": "object"},
            handler=slow_handler,
            timeout_seconds=STRESS_TOOL_TIMEOUT_SECONDS,
        ),
    ]
    for spec in specs:
        register_tool(spec)
    try:
        yield handler_calls
    finally:
        for name in STRESS_TOOL_NAMES:
            registry_module._registry.pop(name, None)
        reset_tool_failures()


@pytest.mark.parametrize("case_idx", range(REGISTRY_OK_EXECUTIONS // REGISTRY_OK_PER_CASE))
async def test_stress_registry_success_path(case_idx: int, stress_registry, request) -> None:
    session = f"stress-ok-{case_idx}"
    reset_tool_failures(session)
    for _ in range(REGISTRY_OK_PER_CASE):
        result = await execute_tool("stress_echo_tool", session, {})
        assert result["ok"] is True
        assert result["tool"] == "stress_echo_tool"
        assert result["error_category"] == "none"
        assert result["timed_out"] is False
        assert isinstance(result["duration_ms"], int)
        assert 0 <= result["duration_ms"] < 5000
        assert result["evidence"]["verified"] is True
        assert tool_failure_count("stress_echo_tool", session) == 0
        _count(request, "registry_success_executions")
    del stress_registry


@pytest.mark.parametrize("case_idx", range(BREAKER_STREAK_CASES))
async def test_stress_registry_breaker_opens_and_recovers(
    case_idx: int, stress_registry, request
) -> None:
    threshold = TOOL_MAX_CONSECUTIVE_FAILURES
    if threshold >= BREAKER_STREAK_EXECUTIONS:
        pytest.skip(f"NEXUS_TOOL_MAX_FAILURES={threshold} exceeds the fuzz budget")
    session = f"stress-breaker-{case_idx}"
    name = "stress_boom_tool"
    reset_tool_failures(session)
    for attempt in range(BREAKER_STREAK_EXECUTIONS):
        result = await execute_tool(name, session, {})
        assert result["ok"] is False
        if attempt < threshold:
            assert result["error_category"] == "tool"
            assert result["consecutive_failures"] == attempt + 1
            assert "circuit_open" not in result
        else:
            assert result.get("circuit_open") is True
        assert tool_failure_count(name, session) == min(attempt + 1, threshold)
        _count(request, "breaker_streak_executions")
    assert stress_registry["boom"] == threshold
    reset_tool_failure(name, session)
    recovered = await execute_tool(name, session, {})
    assert recovered["ok"] is False
    assert recovered["consecutive_failures"] == 1
    assert "circuit_open" not in recovered
    assert stress_registry["boom"] == threshold + 1
    _count(request, "breaker_recoveries")


@pytest.mark.parametrize("case_idx", range(TIMEOUT_PATH_CASES))
async def test_stress_registry_timeout_path(case_idx: int, stress_registry, request) -> None:
    threshold = TOOL_MAX_CONSECUTIVE_FAILURES
    if threshold >= TIMEOUT_PATH_EXECUTIONS:
        pytest.skip(f"NEXUS_TOOL_MAX_FAILURES={threshold} exceeds the fuzz budget")
    session = f"stress-timeout-{case_idx}"
    name = "stress_slow_tool"
    reset_tool_failures(session)
    for attempt in range(TIMEOUT_PATH_EXECUTIONS):
        result = await execute_tool(name, session, {})
        assert result["ok"] is False
        if attempt < threshold:
            assert result["timed_out"] is True
            assert result["exit_code"] == 124
            assert result["error_category"] == "timeout"
            assert result["duration_ms"] >= 0
            assert result["consecutive_failures"] == attempt + 1
        else:
            assert result.get("circuit_open") is True
        assert tool_failure_count(name, session) == min(attempt + 1, threshold)
        _count(request, "timeout_path_executions")
    reset_tool_failures(session)
    again = await execute_tool(name, session, {})
    assert again["timed_out"] is True
    assert stress_registry["slow"] == threshold + 1
    _count(request, "timeout_recoveries")


# ---------------------------------------------------------------------------
# 4. Analyzer smoke massivo
# ---------------------------------------------------------------------------

MINI_PROJECT_FILES = {
    ".gitignore": "__pycache__/\n*.pyc\n.env\n",
    "README.md": "# Stress Mini Project\n\nTiny fixture project for analyzer smoke runs.\n",
    "main.py": (
        "import sys\n\n\nclass App:\n"
        "    def run(self) -> int:\n        print('running')\n        return 0\n\n\n"
        "def main() -> int:\n    return App().run()\n\n\n"
        "if __name__ == '__main__':\n    sys.exit(main())\n"
    ),
    "utils.py": (
        "def parse_config(raw: str) -> dict:\n    return {'raw': raw}\n\n\n"
        "def format_name(name: str) -> str:\n    return name.strip().title()\n"
    ),
    "src/models.py": "class User:\n    def __init__(self, name: str) -> None:\n        self.name = name\n",
    "tests/test_main.py": "from main import main\n\n\ndef test_main() -> None:\n    assert main() == 0\n",
    "package.json": '{"name": "mini", "dependencies": {"react": "^18"}, "devDependencies": {"vitest": "^2"}}',
    "requirements.txt": "fastapi>=0.140\npytest>=8\npydantic>=2\n",
    "config.yaml": "level: debug\nretries: 3\n",
}


@pytest.fixture(scope="session")
def mini_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("stress_mini_project")
    for relative_path, content in MINI_PROJECT_FILES.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


@pytest.mark.parametrize("case_idx", range(ANALYZER_CALLS // ANALYZER_PER_CASE))
async def test_stress_analyzer_smoke(case_idx: int, mini_project: Path, request) -> None:
    reference = None
    for _ in range(ANALYZER_PER_CASE):
        report = await analyze_project(str(mini_project))
        assert isinstance(report, dict)
        assert "error" not in report
        assert report["total_files"] >= len(MINI_PROJECT_FILES)
        framework = report["framework"]
        assert isinstance(framework["primary"], str) and framework["primary"]
        assert framework["confidence"] in {"high", "medium", "low"}
        loc = report["lines_of_code"]
        assert loc["total_files"] > 0
        assert loc["total_lines_of_code"] > 0
        assert report["test_coverage"]["test_files_found"] is True
        assert report["scan_truncated"] is False
        assert report["scan_errors"] == []
        assert report["issue_count"] == len(report["issues"])
        assert 0 <= report["health_score"] <= 100
        if reference is None:
            reference = report
        else:
            assert report == reference
        _count(request, "analyzer_reports")


# ---------------------------------------------------------------------------
# 5. Embeddings keyword fallback massivo
# ---------------------------------------------------------------------------

_EMBED_DOCS = (
    ("auth_service.py", "def login(user, password):\n    token = issue_token(user)\n    return token\n"),
    ("config_loader.py", "def parse_config(path):\n    raw = read_text(path)\n    return load_yaml(raw)\n"),
    ("retry_client.py", "def fetch_with_retry(url):\n    try:\n        return http_get(url)\n    except error:\n        backoff()\n"),
    ("chat_hub.py", "async def broadcast(channel, message):\n    await websocket_send(channel, message)\n"),
    ("deploy.py", "def compose_build(service):\n    docker_compose_up(service)\n"),
    ("cache_store.py", "def cache_get(key):\n    ttl_check(key)\n    eviction_sweep()\n"),
    ("rate_limit.py", "def limit_requests(bucket):\n    refill_tokens(bucket)\n    enforce_ceiling()\n"),
    ("report.md", "# weekly report\n\ndeploy summary and retry statistics\n"),
)

_EMBED_QUERIES = (
    "login token auth",
    "parse yaml config",
    "retry backoff error",
    "websocket broadcast channel",
    "docker compose service",
    "cache ttl eviction",
    "token bucket refill",
    "deploy summary statistics",
)
_EMBED_UNKNOWN_QUERY = "zzz_unknown_term_quixotic"


@pytest.fixture()
def offline_embed_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "code_root"
    root.mkdir()
    store: dict[str, tuple[list[float], CodeChunk]] = {}
    for index, (name, content) in enumerate(_EMBED_DOCS):
        chunk = CodeChunk(
            file=str(root / name),
            start_line=1,
            end_line=len(content.splitlines()),
            content=content,
            language="python" if name.endswith(".py") else "markdown",
            symbol_type="function" if name.endswith(".py") else "",
            symbol_name=f"symbol_{index}",
            chunk_hash=f"hash-{index}",
        )
        store[f"{root / name}::function:symbol_{index}"] = ([], chunk)
    monkeypatch.setattr(embeddings_module, "_store", store)
    return root


@pytest.mark.parametrize("case_idx", range(EMBED_SEARCHES // EMBED_PER_CASE))
def test_stress_embeddings_keyword_fallback(case_idx: int, offline_embed_index: Path, request) -> None:
    query_pool = (*_EMBED_QUERIES, _EMBED_UNKNOWN_QUERY)
    for step in range(EMBED_PER_CASE):
        query = query_pool[(case_idx * EMBED_PER_CASE + step) % len(query_pool)]
        results = _keyword_search(query, k=5)
        first_pass = [(chunk.file, chunk.start_line, round(chunk.score, 6)) for chunk in results]
        repeat = _keyword_search(query, k=5)
        second_pass = [(chunk.file, chunk.start_line, round(chunk.score, 6)) for chunk in repeat]
        assert first_pass == second_pass
        assert len(results) <= 5
        for _, _, score in first_pass:
            assert 0.0 < score <= 1.0
        scoped = _keyword_search(query, k=5, project_path=str(offline_embed_index))
        third_pass = [(chunk.file, chunk.start_line, round(chunk.score, 6)) for chunk in scoped]
        assert third_pass == first_pass
        if query == _EMBED_UNKNOWN_QUERY:
            assert results == []
        else:
            assert results
        _count(request, "embed_keyword_searches")
