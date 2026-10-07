"""NEXUS Terminal — Claude-Code style agentic CLI for NEXUS IDE.

This is the *terminal* sibling of the NEXUS Dashboard (the web UI on
``localhost:3000``). It deliberately stays out of the dashboard's way:

* the dashboard is the visual workspace, browser-only, for humans who
  prefer a GUI;
* the terminal is the keyboard-first loop, for the same humans (or
  scripts) when they want to drive NEXUS from a shell, pipe to it, or
  drive a long-running agentic session in the background.

It is a thin client of the NEXUS backend (``/api/chat`` SSE) plus the
already-tested ``VibeDirector`` for persistent workers and the
``project_context`` module for project memory.  All intelligence stays
on the server; the terminal focuses on giving the user a fast, pretty
agentic loop with visible thinking, visible tool calls, visible
advisor notes and a clear separation between background workers and
the main conversation.

Design goals:

* show *what the agent is thinking* inline, but compactly, so the
  user never loses context;
* show *every tool call* as a small, distinct card with name, args
  and result preview;
* show *every advisor note* (nit / concern / blocker) coloured and
  clearly distinct from the main response;
* show *workers* with state, tier, model, turn count, last preview,
  and let the user ``/agents``, ``/send``, ``/wait``, ``/kill`` them
  without leaving the prompt;
* support slash commands in the Claude-Code style (``/help``,
  ``/tree``, ``/files``, ``/grep``, ``/open``, ``/diff``, ``/patch``,
  ``/run``, ``/agents``, ``/spawn``, ``/send``, ``/wait``, ``/kill``,
  ``/remember``, ``/model``, ``/status``, ``/clear``, ``/exit``);
* never block the input on a long-running chat — the agent streams
  tokens to a live region while the next command can be queued.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import shlex
import subprocess
import sys
import textwrap
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Ensure UTF-8 I/O on Windows shells that default to cp1252 — the NEXUS
# Terminal uses box-drawing characters and emoji that would otherwise
# crash the renderer.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import httpx
from rich import box
from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.spinner import Spinner
from rich.style import Style
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from backend.orchestrator.infinity.model_roles import resolve_role  # noqa: E402
from backend.orchestrator.infinity.project_context import (  # noqa: E402
    index_project,
    remember_project_fact,
    search_project_context,
)
from backend.orchestrator.infinity.terminal_protocol import (  # noqa: E402
    parse_command,
    parse_spawn,
    parse_target,
    parse_wait,
)
from backend.orchestrator.infinity.vibe_director import (  # noqa: E402
    VibeDirector,
    WorkerSession,
    WorkerState,
)

DEFAULT_API_CANDIDATES = (
    "http://127.0.0.1:8001",
    "http://127.0.0.1:8000",
)

# ── theme ───────────────────────────────────────────────────────────────
THEME = {
    "primary": "violet",
    "accent": "magenta",
    "user": "bright_cyan",
    "agent": "bright_white",
    "thinking": "grey58",
    "tool": "cyan",
    "tool_ok": "green",
    "tool_err": "red",
    "advisor_nit": "blue",
    "advisor_concern": "yellow",
    "advisor_blocker": "red",
    "router": "magenta",
    "worker_fast": "cyan",
    "worker_good": "violet",
    "muted": "grey50",
    "code": "bright_white on grey11",
    "selection": "black on violet",
}

BANNER_LINES = (
    "  ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗",
    "  ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝",
    "  ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗",
    "  ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║",
    "  ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║",
    "  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝",
)


# ─────────────────────────────────────────────────────────────────────────
# small helpers
# ─────────────────────────────────────────────────────────────────────────


def _shorten(text: str, limit: int = 240) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _now_str() -> str:
    return time.strftime("%H:%M:%S")


def _wrap(text: str, width: int = 96) -> str:
    return "\n".join(textwrap.wrap(text, width=width, drop_whitespace=False)) or ""


def _jsonify_args(args: Any) -> str:
    """Render tool arguments as compact JSON for inline display."""
    if args is None or args == "":
        return ""
    if isinstance(args, str):
        return args
    try:
        return json.dumps(args, ensure_ascii=False, default=str)[:1200]
    except (TypeError, ValueError):
        return str(args)


def _stringify_result(result: Any) -> str:
    if result is None or result == "":
        return ""
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)[:1500]
    except (TypeError, ValueError):
        return str(result)


# ─────────────────────────────────────────────────────────────────────────
# streaming renderer — keeps a *live* thinking / tool / token region
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class StreamRenderer:
    """Owns the live renderable the terminal shows during a chat turn.

    The renderable is built fresh on every refresh so the user sees a
    cohesive narrative: thinking → tool call → result → advisor note →
    streaming answer.
    """

    console: Console
    spinner_frames: tuple[str, ...] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    _frame: int = 0
    _spinner_text: str = "NEXUS a pensar"
    _thinking: list[str] = field(default_factory=list)
    _tools: list[tuple[str, str, str, str, str]] = field(default_factory=list)  # (status, name, args, result, call_id)
    _advisors: list[tuple[str, str]] = field(default_factory=list)  # (severity, note)
    _routing: str = ""
    _answer: str = ""
    _answer_started: bool = False
    _final_message: str = ""
    _live: Live | None = None
    _tick_task: asyncio.Task[None] | None = None
    _done: bool = False
    _last_refresh: float = 0.0
    _started_at: float = field(default_factory=time.monotonic)
    _token_count: int = 0
    _tool_seq: int = 0

    async def __aenter__(self) -> "StreamRenderer":
        self._live = Live(
            self._render(),
            console=self.console,
            transient=True,
            refresh_per_second=12,
            redirect_stdout=False,
            redirect_stderr=False,
        )
        self._live.__enter__()
        self._tick_task = asyncio.create_task(self._tick())
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._done = True
        if self._tick_task is not None:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._live is not None:
            try:
                self._live.__exit__(exc_type, exc, tb)
            except Exception:
                pass

    async def _tick(self) -> None:
        try:
            while not self._done:
                await asyncio.sleep(0.08)
                self._frame += 1
                self._maybe_refresh()
        except asyncio.CancelledError:
            return

    def _maybe_refresh(self) -> None:
        now = time.time()
        if now - self._last_refresh < 0.06:
            return
        self._last_refresh = now
        if self._live is not None:
            try:
                self._live.update(self._render())
            except Exception:
                pass

    # ── ingest ──────────────────────────────────────────────────────────
    def set_routing(self, primary: str, mode: str) -> None:
        self._routing = f"{primary} · {mode}"

    def append_thinking(self, content: str) -> None:
        if not content:
            return
        self._thinking.append(content)
        self._maybe_refresh()

    def add_tool(self, name: str, args: str, status: str = "running",
                 call_id: str | None = None) -> None:
        # use call_id (event_id) when present so two calls of the same
        # tool are not collapsed — only the older `name` fallback remains
        # for legacy events that don't carry an id.
        cid = call_id or f"#{self._tool_seq}"
        self._tool_seq += 1
        self._tools.append((status, name, args, "", cid))
        self._maybe_refresh()

    def finish_tool(self, name: str, result: str, status: str = "ok",
                    call_id: str | None = None) -> None:
        target_index: int | None = None
        if call_id:
            for index, entry in enumerate(self._tools):
                if entry[4] == call_id and entry[3] == "":
                    target_index = index
                    break
        if target_index is None:
            # most-recent unfinished call to the same name
            for index in range(len(self._tools) - 1, -1, -1):
                if self._tools[index][1] == name and self._tools[index][3] == "":
                    target_index = index
                    break
        if target_index is None:
            self._tool_seq += 1
            self._tools.append((status, name, "", result or "", f"#{self._tool_seq}"))
            self._maybe_refresh()
            return
        old = self._tools[target_index]
        self._tools[target_index] = (status, old[1], old[2], result or "", old[4])
        self._maybe_refresh()

    def add_advisor(self, severity: str, note: str) -> None:
        self._advisors.append((severity, note))
        self._maybe_refresh()

    def append_token(self, token: str) -> None:
        if not token:
            return
        if not self._answer_started and token.strip():
            self._answer_started = True
        self._answer += token
        self._token_count += 1
        self._maybe_refresh()

    def set_final(self, message: str) -> None:
        self._final_message = message

    def token_count(self) -> int:
        return self._token_count

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._started_at) * 1000)

    # ── render ──────────────────────────────────────────────────────────
    def _render(self) -> RenderableType:
        spinner_char = self.spinner_frames[self._frame % len(self.spinner_frames)]
        parts: list[RenderableType] = []

        if self._routing:
            parts.append(
                Text.assemble(
                    (f"{spinner_char} ", THEME["primary"]),
                    (f"router → {self._routing}", THEME["router"]),
                )
            )

        if self._thinking and not self._answer_started:
            latest = self._thinking[-1]
            display = _shorten(latest, 320)
            parts.append(
                Text.assemble(
                    (f"{spinner_char} thinking… ", THEME["thinking"]),
                    (display, THEME["thinking"]),
                )
            )

        for severity, note in self._advisors:
            colour = {
                "nit": THEME["advisor_nit"],
                "concern": THEME["advisor_concern"],
                "blocker": THEME["advisor_blocker"],
            }.get(severity, "yellow")
            parts.append(
                Padding(
                    Panel(
                        Text(_wrap(note, 92), style=colour),
                        title=f"advisor · {severity}",
                        title_align="left",
                        border_style=colour,
                        padding=(0, 1),
                    ),
                    (0, 0, 0, 2),
                )
            )

        for index, (status, name, args, result, call_id) in enumerate(self._tools, start=1):
            border = (
                THEME["tool_ok"] if status == "ok"
                else THEME["tool_err"] if status == "error"
                else THEME["tool"]
            )
            title = f"tool #{index} · {name} · {call_id}"
            if status == "running":
                title = f"{spinner_char} {title}"
            elif status == "ok":
                title = f"✓ {title}"
            else:
                title = f"✗ {title}"
            body = self._render_tool_body(args, result, status)
            parts.append(
                Padding(
                    Panel(
                        body,
                        title=title,
                        title_align="left",
                        border_style=border,
                        padding=(0, 1),
                    ),
                    (0, 0, 0, 2),
                )
            )

        if self._answer:
            subtitle = (
                f"tokens≈{self._token_count} · {self.elapsed_ms() / 1000:.1f}s"
                if self._token_count or self.elapsed_ms() > 500
                else ""
            )
            parts.append(
                Padding(
                    Panel(
                        Text(self._answer, style=THEME["agent"]),
                        title=f"{spinner_char} NEXUS" if not self._final_message else "NEXUS",
                        subtitle=subtitle or None,
                        title_align="left",
                        border_style=THEME["primary"],
                        padding=(0, 1),
                    ),
                    (0, 0, 0, 2),
                )
            )
        elif self._routing and not self._answer:
            parts.append(
                Text.assemble(
                    (f"{spinner_char} ", THEME["primary"]),
                    ("à espera do primeiro token…", THEME["muted"]),
                )
            )

        if self._final_message and not self._answer:
            parts.append(Text(self._final_message, style="red"))

        return Group(*parts) if parts else Text("")

    @staticmethod
    def _render_tool_body(args: str, result: str, status: str) -> RenderableType:
        """Build the body of a tool card; render JSON args with syntax."""
        body: list[RenderableType] = []
        if args:
            # try JSON pretty-print if it parses
            pretty_args: str | None = None
            try:
                parsed = json.loads(args)
                pretty_args = json.dumps(parsed, indent=2, ensure_ascii=False)[:1200]
            except (ValueError, TypeError):
                pretty_args = None
            if pretty_args is not None:
                body.append(Text("args:", style="bold"))
                body.append(
                    Syntax(
                        pretty_args, "json", theme="monokai",
                        background_color="default", word_wrap=True,
                    )
                )
            else:
                body.append(
                    Text.assemble(
                        ("args: ", "bold"),
                        (_shorten(args, 240), THEME["muted"]),
                    )
                )
        if result:
            if body:
                body.append(Text(""))
            body.append(Text("result:", style="bold"))
            body.append(
                Text(_shorten(str(result), 320), style=THEME["muted"])
            )
        if not body and status != "running":
            return Text("(no output)", style=THEME["muted"])
        if not body:
            return Text("(a executar…)", style=THEME["muted"])
        return Group(*body)


# ─────────────────────────────────────────────────────────────────────────
# input prompt — small, themed, history-aware
# ─────────────────────────────────────────────────────────────────────────


def _readline_history_path() -> Path:
    base = Path(os.environ.get("NEXUS_TERMINAL_HOME") or Path.home() / ".nexus")
    base.mkdir(parents=True, exist_ok=True)
    return base / "terminal-history.txt"


def _load_history() -> list[str]:
    path = _readline_history_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return lines[-512:]


def _save_history(history: Iterable[str]) -> None:
    path = _readline_history_path()
    try:
        items = list(history)[-512:]
        path.write_text("\n".join(items) + "\n", encoding="utf-8")
    except OSError:
        pass


def _input_with_history(prompt: str, history: list[str]) -> str:
    """Read a single line with optional readline history on Windows / POSIX."""
    try:
        import readline  # type: ignore
    except ImportError:
        return input(prompt)

    readline.set_history_length(1024)
    for item in history:
        try:
            readline.add_history(item)
        except Exception:
            pass
    try:
        return input(prompt)
    finally:
        try:
            current = readline.get_current_history_length()
            for index in range(current):
                item = readline.get_history_item(index + 1)
                if item is not None and (not history or history[-1] != item):
                    history.append(item)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────
# main terminal
# ─────────────────────────────────────────────────────────────────────────


class NexusTerminal:
    """Rich REPL and HTTP bridge for one terminal session."""

    def __init__(self, args: argparse.Namespace) -> None:
        # Force UTF-8 on the rich console so box-drawing characters and
        # emoji render in legacy Windows terminals (cp1252 by default).
        self.console = Console(
            force_terminal=True,
            legacy_windows=False,
            safe_box=False,
            emoji=True,
            highlight=False,
        )
        self.session_id = (
            args.session.strip()
            or f"terminal-{uuid.uuid4().hex[:16]}"
        )
        self.project_path = str(Path(args.project).expanduser().resolve())
        self.api_url = (args.api_url or os.environ.get("NEXUS_API_URL", "")).rstrip("/")
        self.token = args.token or os.environ.get("NEXUS_ACCESS_TOKEN", "")
        self.requested_model = args.model or os.environ.get("NEXUS_TERMINAL_MODEL", "")
        self.max_agents = max(1, min(int(args.max_agents), 20))
        self.verbose = bool(args.verbose)
        self.offline = bool(args.offline)
        self.skip_scan = bool(args.no_scan)
        self.client: httpx.AsyncClient | None = None
        self.project_index: dict[str, Any] | None = None
        self._shutdown = False
        self._busy = False
        self._history: list[str] = _load_history()
        self._last_turn: dict[str, Any] | None = None
        self._last_routing: dict[str, Any] = {}
        self._session_started_at: float = time.time()
        self._turns: int = 0
        self._total_tokens: int = 0
        self._last_error: str | None = None

        tier_models = {
            "fast": resolve_role("smol").model_id,
            "good": resolve_role("slow").model_id,
        }
        self.director = VibeDirector(
            session_id=self.session_id,
            runner=self._run_worker,
            tier_models=tier_models,
            on_update=self._on_worker_update,
        )

    # ── lifecycle ───────────────────────────────────────────────────────
    async def run(self) -> int:
        self._print_banner()
        if not Path(self.project_path).is_dir():
            self.console.print(
                f"[red]Projeto não encontrado:[/red] {self.project_path}"
            )
            return 2

        if not self.offline:
            try:
                await self._connect_and_authenticate()
            except (httpx.HTTPError, RuntimeError) as exc:
                self.console.print(f"[red]Backend indisponível:[/red] {exc}")
                self.console.print(
                    "Inicia o backend do Nexus ou usa [cyan]--offline[/cyan] "
                    "para explorar/indexar o projeto sem chat."
                )
                return 2

        if not self.skip_scan:
            await self._scan_project()

        self._print_ready_hint()
        try:
            while not self._shutdown:
                try:
                    line = await asyncio.to_thread(self._read_line)
                except (EOFError, KeyboardInterrupt):
                    self.console.print()
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                self._remember_history(stripped)
                if stripped.startswith("/"):
                    await self._handle_command(stripped)
                else:
                    try:
                        await self._chat(stripped)
                    except asyncio.CancelledError:
                        self.console.print(
                            "[yellow]turno cancelado — podes continuar a escrever.[/yellow]"
                        )
                        self._busy = False
                    except (httpx.HTTPError, RuntimeError) as exc:
                        self.console.print(
                            f"[red]erro no chat:[/red] {exc}"
                        )
                        self._last_error = f"{type(exc).__name__}: {exc}"
                        self._busy = False
        finally:
            _save_history(self._history)
            self.director.kill_all()
            if self.client is not None:
                await self.client.aclose()
        return 0

    def _read_line(self) -> str:
        folder = Path(self.project_path).name or self.project_path
        prompt = (
            f"\n[bold {THEME['primary']}]nexus[/bold {THEME['primary']}]"
            f"[{THEME['muted']}]:[/]"
            f"[bold {THEME['accent']}]{folder}[/bold {THEME['accent']}]"
            f"[{THEME['muted']}]› [/]"
        )
        try:
            return _input_with_history(prompt, self._history)
        except (EOFError, KeyboardInterrupt):
            raise

    def _remember_history(self, line: str) -> None:
        if not self._history or self._history[-1] != line:
            self._history.append(line)

    def _print_banner(self) -> None:
        banner = Text("\n".join(BANNER_LINES), style=f"bold {THEME['primary']}")
        subtitle = Text(
            "terminal · agentes persistentes · pensamento visível · memória de projeto",
            style=THEME["muted"],
        )
        meta = Text.assemble(
            ("sessão ", THEME["muted"]),
            (self.session_id, THEME["accent"]),
            ("  ·  projeto ", THEME["muted"]),
            (self.project_path, "white"),
        )
        self.console.print(Align.center(banner))
        self.console.print(Align.center(subtitle))
        self.console.print(Align.center(meta))
        self.console.print(
            Panel(
                Text.assemble(
                    ("Este é o ", THEME["muted"]),
                    ("NEXUS Terminal", f"bold {THEME['primary']}"),
                    (" — irmão CLI do ", THEME["muted"]),
                    ("NEXUS Dashboard", f"bold {THEME['accent']}"),
                    (
                        ". O dashboard corre no browser (localhost:3000); este terminal "
                        "corre aqui e partilha o mesmo backend, memória e modelos.",
                        THEME["muted"],
                    ),
                ),
                border_style=THEME["primary"],
                padding=(0, 2),
            )
        )

    def _print_ready_hint(self) -> None:
        self.console.print(
            Text.assemble(
                ("Pronto. ", "green"),
                ("Escreve um prompt ou ", THEME["muted"]),
                ("/help", f"bold {THEME['primary']}"),
                (" para ver comandos. ", THEME["muted"]),
                ("/status", f"bold {THEME['primary']}"),
                (" mostra o estado da sessão.", THEME["muted"]),
            )
        )

    # ── backend connection ─────────────────────────────────────────────
    async def _connect_and_authenticate(self) -> None:
        candidates = [self.api_url] if self.api_url else list(DEFAULT_API_CANDIDATES)
        last_error = "sem resposta de health"
        for candidate in candidates:
            try:
                client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=4.0))
                response = await client.get(f"{candidate}/health")
                if response.status_code < 500:
                    self.client = client
                    self.api_url = candidate
                    break
                last_error = f"HTTP {response.status_code} em {candidate}/health"
                await client.aclose()
            except httpx.HTTPError as exc:
                last_error = f"{candidate}: {exc}"
        else:
            raise RuntimeError(last_error)

        await self._authenticate()
        self.console.print(
            Text.assemble(
                ("● ligado a ", "green"),
                (self.api_url, "white"),
            )
        )

    async def _authenticate(self) -> None:
        if self.client is None:
            raise RuntimeError("cliente HTTP não inicializado")
        if self.token:
            response = await self.client.get(
                f"{self.api_url}/api/auth/me",
                headers=self._headers(),
            )
            if response.is_success:
                return
            self.token = ""

        # Single-password auth: the backend's default user only requires the
        # shared NEXUS_DEFAULT_PASSWORD (5748 by default). NEXUS_EMAIL
        # overrides the implicit default address when the deploy uses a
        # non-default admin email.
        email = (
            os.environ.get("NEXUS_EMAIL", "").strip()
            or os.environ.get("NEXUS_DEFAULT_EMAIL", "admin@nexus-ide.com")
        )
        password = (
            os.environ.get("NEXUS_PASSWORD", "")
            or os.environ.get("NEXUS_DEFAULT_PASSWORD", "5748")
        )
        if not password:
            password = await asyncio.to_thread(getpass.getpass, "Password NEXUS: ")
        response = await self.client.post(
            f"{self.api_url}/api/auth/login",
            json={"email": email, "password": password},
        )
        if not response.is_success:
            detail = self._response_detail(response)
            raise RuntimeError(f"login recusado ({response.status_code}): {detail}")
        payload = response.json()
        self.token = str(payload.get("access_token") or "")
        if not self.token:
            raise RuntimeError("o login não devolveu access_token")

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @staticmethod
    def _response_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
            return str(payload.get("detail") or payload)
        except (ValueError, TypeError):
            return response.text[:500]

    # ── project context ─────────────────────────────────────────────────
    async def _scan_project(self, *, force: bool = False) -> None:
        with self.console.status("[cyan]A ler o projeto e a atualizar a memória…[/cyan]", spinner="dots"):
            try:
                self.project_index = await index_project(
                    self.project_path,
                    force_reindex=force,
                )
            except (OSError, RuntimeError) as exc:
                self.console.print(f"[yellow]Scan não concluído:[/yellow] {exc}")
                return
        result = self.project_index
        status = str(result.get("status") or "unknown")
        color = "green" if status == "indexed" else "yellow" if status == "partial" else "red"
        self.console.print(
            Text.assemble(
                ("● projeto ", "green"),
                (status, f"bold {color}"),
                (
                    f"  ·  {result.get('files_discovered', 'NOT_MEASURED')} descobertos",
                    THEME["muted"],
                ),
                (
                    f"  ·  {result.get('indexable_files', 'NOT_MEASURED')} indexáveis",
                    THEME["muted"],
                ),
                (
                    f"  ·  {result.get('chunks_indexed', 'NOT_MEASURED')} chunks",
                    THEME["muted"],
                ),
            )
        )
        analysis = result.get("analysis") or {}
        framework = (analysis.get("framework") or {}).get("primary", "NOT_DETECTED")
        loc = (analysis.get("lines_of_code") or {}).get("total_lines_of_code", "NOT_MEASURED")
        self.console.print(
            Text.assemble(
                ("framework ", THEME["muted"]),
                (str(framework), "white"),
                ("  ·  linhas ", THEME["muted"]),
                (str(loc), "white"),
                ("  ·  code-index ", THEME["muted"]),
                (str(result.get("code_index_status", "NOT_MEASURED")), "white"),
            )
        )
        for warning in result.get("warnings") or []:
            self.console.print(f"[yellow]Aviso:[/yellow] {warning}")
        if result.get("scan_truncated"):
            self.console.print(
                "[yellow]O analisador marcou o scan como parcial; "
                "não vou afirmar que todos os ficheiros foram lidos.[/yellow]"
            )

    async def _find(self, query: str) -> None:
        if not query.strip():
            self.console.print("[yellow]Usa: /find <pergunta sobre o projeto>[/yellow]")
            return
        with self.console.status("[cyan]A pesquisar no índice…[/cyan]", spinner="dots"):
            context = await search_project_context(query, self.project_path)
        if not context:
            self.console.print("[dim]Sem contexto indexado para essa pesquisa.[/dim]")
            return
        self.console.print(
            Panel(
                Markdown(context[:6_000]),
                title="memória e código relevantes",
                border_style=THEME["accent"],
                padding=(0, 1),
            )
        )

    # ── chat ─────────────────────────────────────────────────────────────
    async def _chat(
        self,
        message: str,
        *,
        session_id: str | None = None,
        model: str = "",
        display: bool = True,
        max_retries: int = 2,
    ) -> str:
        if self.client is None:
            raise RuntimeError("chat indisponível em modo offline")
        payload = {
            "message": message,
            "session_id": session_id or self.session_id,
            "mode": "auto",
            "model": model or self.requested_model,
            "project_path": self.project_path,
            "autonomous": True,
        }
        if display:
            self._busy = True
            self._print_user_prompt(message)

        output: list[str] = []
        error: str | None = None
        renderer = StreamRenderer(self.console)
        try:
            attempt = 0
            while True:
                attempt += 1
                output = []
                error = None
                try:
                    async with renderer:
                        async with self.client.stream(
                            "POST",
                            f"{self.api_url}/api/chat",
                            headers={
                                **self._headers(),
                                "Content-Type": "application/json",
                            },
                            json=payload,
                        ) as response:
                            if response.status_code == 401:
                                raise RuntimeError(
                                    "token expirado; define NEXUS_ACCESS_TOKEN novamente"
                                )
                            if not response.is_success:
                                raise RuntimeError(
                                    f"chat HTTP {response.status_code}: "
                                    f"{self._response_detail(response)}"
                                )
                            async for line in response.aiter_lines():
                                if not line.startswith("data:"):
                                    continue
                                try:
                                    event = json.loads(line[5:].strip())
                                except ValueError:
                                    continue
                                event_type = str(event.get("type") or "")
                                if event_type == "error":
                                    error = str(
                                        event.get("content") or "erro desconhecido"
                                    )
                                self._consume_event(
                                    event, event_type, renderer,
                                    output, display,
                                )
                                if event_type == "done":
                                    break
                    break  # clean exit from async-with renderer
                except httpx.HTTPError as exc:
                    error = str(exc)
                    if attempt <= max_retries:
                        if display:
                            self.console.print(
                                f"[yellow]⚠ transporte caiu ({exc}); "
                                f"a tentar outra vez ({attempt}/{max_retries})…[/yellow]"
                            )
                        await asyncio.sleep(0.4 * attempt)
                        continue
                    renderer.set_final(error)
                    break
        except asyncio.CancelledError:
            self._busy = False
            raise
        except Exception as exc:  # noqa: BLE001 — chat must never crash REPL
            error = f"{type(exc).__name__}: {exc}"
            self._last_error = error
        finally:
            self._busy = False

        if error:
            self._last_error = error if display else "chat worker failed"
            if display:
                self.console.print(
                    Panel(
                        Text(error, style="red"),
                        title="NEXUS · erro",
                        border_style="red",
                        padding=(0, 1),
                    )
                )
            else:
                raise RuntimeError("chat worker failed")
            return f"[NEXUS ERROR] {error}"

        full = "".join(output).strip()
        if display:
            self._last_turn = {
                "tokens": renderer.token_count(),
                "elapsed_ms": renderer.elapsed_ms(),
                "tools": sum(1 for t in renderer._tools if t[0] != "running"),
                "advisors": len(renderer._advisors),
                "answer_chars": len(full),
                "ts": time.time(),
            }
            self._turns += 1
            self._total_tokens += self._last_turn["tokens"]
        if display and full:
            self.console.print(
                Panel(
                    Markdown(full),
                    title="NEXUS",
                    subtitle=(
                        f"~{self._last_turn['tokens']} tokens · "
                        f"{self._last_turn['elapsed_ms'] / 1000:.1f}s"
                        if self._last_turn
                        else None
                    ),
                    border_style=THEME["primary"],
                    padding=(0, 1),
                )
            )
        return full

    def _consume_event(
        self,
        event: dict[str, Any],
        event_type: str,
        renderer: "StreamRenderer",
        output: list[str],
        display: bool,
    ) -> None:
        """Single dispatch table — every recognised event is one branch."""
        if event_type == "routing":
            routing = event.get("routing") or {}
            renderer.set_routing(
                str(routing.get("primary_agent") or "NEXUS"),
                str(routing.get("thinking_mode") or "auto"),
            )
            self._last_routing = dict(routing) if isinstance(routing, dict) else {}
            return
        if event_type == "agent_started":
            if display:
                self.console.print(
                    Text.assemble(
                        ("● ", THEME["primary"]),
                        (str(event.get("agent") or "NEXUS"), "white"),
                        (" a trabalhar", THEME["muted"]),
                    )
                )
            return
        if event_type == "agent_finished":
            if display:
                self.console.print(
                    Text.assemble(
                        ("✓ ", "green"),
                        (str(event.get("agent") or "NEXUS"), "green"),
                        (" terminou", THEME["muted"]),
                    )
                )
            return
        if event_type == "thinking":
            if display:
                renderer.append_thinking(str(event.get("content") or ""))
            return
        if event_type == "tool_call":
            if not display:
                return
            renderer.add_tool(
                str(event.get("tool_name") or "tool"),
                _jsonify_args(event.get("tool_args") or event.get("arguments")),
                call_id=str(event.get("event_id") or "") or None,
            )
            return
        if event_type == "tool_result":
            if not display:
                return
            renderer.finish_tool(
                str(event.get("tool_name") or "tool"),
                _stringify_result(event.get("tool_result") or event.get("result")),
                status="ok",
                call_id=str(event.get("event_id") or "") or None,
            )
            return
        if event_type == "tool_error":
            if not display:
                return
            renderer.finish_tool(
                str(event.get("tool_name") or "tool"),
                str(event.get("tool_error") or event.get("error") or ""),
                status="error",
                call_id=str(event.get("event_id") or "") or None,
            )
            return
        if event_type == "advisor_note":
            if not display:
                return
            note = str(
                event.get("content")
                or event.get("note")
                or event.get("data", {}).get("note")
                or ""
            )
            severity = str(
                event.get("severity")
                or event.get("data", {}).get("severity")
                or "concern"
            )
            if note:
                renderer.add_advisor(severity, note)
            return
        if event_type == "token":
            token = str(event.get("content") or "")
            output.append(token)
            if display and token:
                renderer.append_token(token)
            return
        if event_type == "error":
            error_text = str(event.get("content") or "erro desconhecido")
            renderer.set_final(error_text)
            # store in closure via mutable ref already exists; just
            # continue and let the loop finish on `done` to show
            # any partial answer before the final error panel.
            return
        if event_type == "done":
            return
        # unknown event types are kept visible but not blocking
        if display and self.verbose:
            self.console.print(f"[dim]… evento desconhecido: {event_type}[/dim]")

    def _print_user_prompt(self, message: str) -> None:
        self.console.print(
            Panel(
                Text(message, style=THEME["user"]),
                title="tu",
                title_align="right",
                border_style=THEME["user"],
                padding=(0, 1),
            )
        )

    async def _run_worker(self, worker: WorkerSession, message: str) -> str:
        prompt = (
            "És um worker especialista do NEXUS Terminal. Trabalha apenas no "
            f"projeto em {self.project_path}. Usa ferramentas reais quando "
            "necessário, distingue factos medidos de hipóteses e devolve um "
            "resultado curto com evidência e bloqueios. Não afirmes que outro "
            "agente executou algo.\n\nTarefa delegada:\n"
            f"{message}"
        )
        model = worker.model_id or (self.requested_model if worker.tier == "good" else "")
        return await self._chat(
            prompt,
            session_id=f"{self.session_id}-{worker.id}",
            model=model,
            display=False,
        )

    def _on_worker_update(self, worker: WorkerSession, action: str) -> None:
        if action == "spawned":
            tier_color = THEME["worker_fast"] if worker.tier == "fast" else THEME["worker_good"]
            self.console.print(
                Text.assemble(
                    ("● worker ", "green"),
                    (worker.id, f"bold {tier_color}"),
                    (" · ", THEME["muted"]),
                    (worker.name, "white"),
                    (" · tier ", THEME["muted"]),
                    (worker.tier, tier_color),
                    (" · modelo ", THEME["muted"]),
                    (worker.model_id or "auto", "white"),
                )
            )
        elif action == "queued":
            self.console.print(
                Text.assemble(
                    ("… ", "yellow"),
                    (f"{worker.id} tem {worker.queued_count} mensagem(ns) em fila", "yellow"),
                )
            )
        elif action == "turn_started":
            self.console.print(
                Text.assemble(
                    ("● ", THEME["primary"]),
                    (f"{worker.id} a executar turno", "white"),
                )
            )
        elif action == "turn_completed":
            preview = _shorten(worker.last_result or "", 260)
            self.console.print(
                Text.assemble(
                    ("✓ ", "green"),
                    (f"{worker.id} terminou", "green"),
                    (f"  {preview}" if preview else "", THEME["muted"]),
                )
            )
        elif action == "killed":
            self.console.print(
                Text.assemble(
                    ("✗ ", "red"),
                    (f"{worker.id} terminado", "red"),
                )
            )
        elif action == "idle" and self.verbose:
            self.console.print(f"[dim]{worker.id} idle[/dim]")

    # ── commands ────────────────────────────────────────────────────────
    async def _handle_command(self, line: str) -> None:
        command = parse_command(line)
        if command is None:
            return
        name = command.name
        args = command.arguments
        if name in {"help", "?"}:
            self._print_help()
        elif name in {"exit", "quit", "q"}:
            self._shutdown = True
        elif name == "clear":
            self.console.clear()
        elif name == "project":
            await self._change_project(args)
        elif name in {"scan", "index"}:
            await self._scan_project(force=name == "index")
        elif name in {"find", "search"}:
            await self._find(args)
        elif name in {"tree", "files"}:
            self._show_tree(args)
        elif name == "open":
            self._open_file(args)
        elif name == "grep":
            self._grep_project(args)
        elif name == "diff":
            self._show_diff(args)
        elif name == "patch":
            await self._apply_patch(args)
        elif name == "run":
            self._run_shell(args)
        elif name in {"agents", "workers"}:
            self._print_workers()
        elif name == "result":
            self._print_worker_result(args)
        elif name == "spawn":
            self._spawn_worker(args)
        elif name == "send":
            self._send_worker(args)
        elif name == "wait":
            await self._wait_workers(args)
        elif name == "kill":
            self._kill_worker(args)
        elif name in {"remember", "memo"}:
            await self._remember(args)
        elif name == "model":
            self._set_model(args)
        elif name == "status":
            self._print_status()
        elif name == "history":
            self._print_history(args)
        elif name == "metrics":
            self._print_metrics()
        elif name == "retry":
            await self._retry_last()
        elif name == "ctx":
            self._show_last_context()
        elif name == "logs":
            self._print_logs(args)
        else:
            self.console.print(
                f"[yellow]Comando desconhecido:[/yellow] /{name}. Usa /help."
            )

    # ── file / shell commands ───────────────────────────────────────────
    def _show_tree(self, args: str) -> None:
        depth, root = self._parse_depth_and_path(args, default_depth=3)
        root_path = Path(root) if root else Path(self.project_path)
        if not root_path.is_dir():
            self.console.print(f"[red]Pasta não encontrada:[/red] {root_path}")
            return
        tree = self._build_tree(root_path, depth)
        self.console.print(
            Panel(
                tree,
                title=f"tree · {root_path} · depth={depth}",
                border_style=THEME["accent"],
                padding=(0, 1),
            )
        )

    def _build_tree(self, root: Path, depth: int) -> Tree:
        tree = Tree(
            Text(str(root), style=f"bold {THEME['primary']}"),
            guide_style=THEME["muted"],
        )
        self._populate_tree(tree, root, depth, current=0)
        return tree

    def _populate_tree(self, tree: Tree, root: Path, depth: int, current: int) -> None:
        if current >= depth:
            return
        try:
            entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError as exc:
            tree.add(Text(f"(erro: {exc})", style="red"))
            return
        for entry in entries:
            if entry.name.startswith(".") and entry.name not in {".env", ".env.example"}:
                continue
            if entry.name in {"__pycache__", "node_modules", ".next", ".venv", "dist", "build", "artifacts"}:
                tree.add(Text(f"↳ {entry.name}/  (ignorada)", style=THEME["muted"]))
                continue
            if entry.is_dir():
                branch = tree.add(
                    Text.assemble(
                        ("▸ ", THEME["primary"]),
                        (entry.name + "/", "white"),
                    )
                )
                self._populate_tree(branch, entry, depth, current + 1)
            else:
                try:
                    size = entry.stat().st_size
                    size_text = self._format_size(size)
                except OSError:
                    size_text = "?"
                tree.add(
                    Text.assemble(
                        ("· ", THEME["muted"]),
                        (entry.name, "white"),
                        (f"   {size_text}", THEME["muted"]),
                    )
                )

    @staticmethod
    def _format_size(size: int) -> str:
        units = ("B", "KB", "MB", "GB")
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:,.0f} {unit}" if unit == "B" else f"{value:,.1f} {unit}"
            value /= 1024
        return f"{value:,.1f} GB"

    def _open_file(self, args: str) -> None:
        path = self._resolve_project_path(args)
        if path is None:
            return
        if not path.exists():
            self.console.print(f"[red]Não existe:[/red] {path}")
            return
        if path.is_dir():
            self.console.print(
                f"[yellow]{path} é uma pasta. Usa /tree <pasta> para navegar.[/yellow]"
            )
            return
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            self.console.print(f"[yellow]Ficheiro binário — não foi aberto:[/yellow] {path}")
            return
        except OSError as exc:
            self.console.print(f"[red]Erro a ler:[/red] {exc}")
            return
        syntax = self._syntax_for(path, content)
        self.console.print(
            Panel(
                syntax,
                title=str(path.relative_to(self.project_path)),
                subtitle=f"{len(content):,} chars · {content.count(chr(10)) + 1} linhas",
                border_style=THEME["accent"],
                padding=(0, 1),
            )
        )

    def _syntax_for(self, path: Path, content: str) -> RenderableType:
        try:
            lexer = Syntax.guess_lexer(str(path), content)
        except Exception:
            lexer = "text"
        return Syntax(
            content,
            lexer,
            theme="monokai",
            line_numbers=True,
            word_wrap=False,
            background_color="default",
        )

    def _grep_project(self, args: str) -> None:
        try:
            parts = shlex.split(args)
        except ValueError as exc:
            self.console.print(f"[yellow]Argumentos inválidos:[/yellow] {exc}")
            return
        if not parts:
            self.console.print(
                "[yellow]Usa: /grep <padrão> [--ext py,ts] [--path subpasta] "
                "[--ignore-case] [--max N][/yellow]"
            )
            return
        pattern = parts[0]
        extensions: set[str] = set()
        subpath: str | None = None
        ignore_case = False
        max_results = 200
        iterator = iter(parts[1:])
        for token in iterator:
            if token == "--ext":
                try:
                    extensions = {
                        f".{value.lstrip('.').lower()}" for value in next(iterator).split(",")
                    }
                except StopIteration:
                    pass
            elif token == "--path":
                try:
                    subpath = next(iterator)
                except StopIteration:
                    pass
            elif token in {"--ignore-case", "-i"}:
                ignore_case = True
            elif token == "--max":
                try:
                    max_results = int(next(iterator))
                except (StopIteration, ValueError):
                    pass
        search_root = (
            (Path(self.project_path) / subpath).resolve()
            if subpath
            else Path(self.project_path)
        )
        if not search_root.is_dir():
            self.console.print(f"[red]Pasta não encontrada:[/red] {search_root}")
            return
        compiled = re_compile(pattern, ignore_case)
        if compiled is None:
            return
        table = Table(
            title=f"grep · {pattern} · {search_root}",
            box=box.SIMPLE_HEAVY,
            border_style=THEME["accent"],
        )
        table.add_column("ficheiro", style="white")
        table.add_column("linha", justify="right", style="cyan")
        table.add_column("match", style="white")
        found = 0
        for path in search_root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in {"__pycache__", "node_modules", ".next", ".venv", "dist", "build", "artifacts"} for part in path.parts):
                continue
            if extensions and path.suffix.lower() not in extensions:
                continue
            try:
                with path.open("r", encoding="utf-8", errors="ignore") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if compiled.search(line):
                            table.add_row(
                                str(path.relative_to(search_root)),
                                str(line_number),
                                _shorten(line.rstrip(), 200),
                            )
                            found += 1
                            if found >= max_results:
                                break
            except OSError:
                continue
            if found >= max_results:
                break
        if found:
            self.console.print(table)
        else:
            self.console.print("[dim]Sem matches.[/dim]")
        self.console.print(
            Text.assemble(
                (f"{found} resultado(s)", THEME["muted"]),
                (f" (limite {max_results})" if found >= max_results else "", THEME["muted"]),
            )
        )

    def _show_diff(self, args: str) -> None:
        try:
            parts = shlex.split(args) if args.strip() else []
        except ValueError as exc:
            self.console.print(f"[yellow]Argumentos inválidos:[/yellow] {exc}")
            return
        if not parts or parts[0] in {"help", "?"}:
            self.console.print(
                Text(
                    "Usa:\n"
                    "  /diff <ficheiro>                — diff contra HEAD\n"
                    "  /diff <ficheiro> <base>         — diff contra outro ficheiro/base\n"
                    "  /diff staged                    — diff staged vs working tree",
                    style=THEME["muted"],
                )
            )
            return
        if parts[0] == "staged":
            self._git_diff(["--staged"])
            return
        target = self._resolve_project_path(parts[0])
        if target is None or len(parts) > 1 and not parts[1]:
            return
        if not target.exists():
            self.console.print(f"[red]Não existe:[/red] {target}")
            return
        if len(parts) == 1:
            self._git_diff(["--", str(target.relative_to(self.project_path))])
            return
        base = Path(parts[1])
        if not base.is_absolute():
            base = (Path(self.project_path) / base).resolve()
        if not base.exists():
            self.console.print(f"[red]Base não existe:[/red] {base}")
            return
        # use git diff if both look like project-relative and we're in a git repo
        try:
            output = subprocess.run(
                ["git", "diff", "--no-color", "--", str(target.relative_to(self.project_path))],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            output = None
        if output is not None and output.returncode in (0, 1) and output.stdout:
            self.console.print(
                Panel(
                    Syntax(output.stdout, "diff", theme="monokai", line_numbers=True),
                    title=f"git diff · {target.relative_to(self.project_path)}",
                    border_style=THEME["accent"],
                    padding=(0, 1),
                )
            )
            return
        self.console.print(
            f"[yellow]Sem alterações em git; usa `diff` externo entre {target} e {base}.[/yellow]"
        )

    def _git_diff(self, extra: list[str]) -> None:
        try:
            result = subprocess.run(
                ["git", "diff", "--no-color", *extra],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.console.print(f"[red]git indisponível:[/red] {exc}")
            return
        if not result.stdout:
            self.console.print("[dim]Sem diferenças.[/dim]")
            return
        self.console.print(
            Panel(
                Syntax(result.stdout, "diff", theme="monokai", line_numbers=True),
                title="git diff",
                border_style=THEME["accent"],
                padding=(0, 1),
            )
        )

    async def _apply_patch(self, args: str) -> None:
        # delegates to the agent — patches come back as tool calls on the
        # server.  We just ask NEXUS to apply a patch from a file or
        # text in the prompt.
        if not args.strip():
            self.console.print(
                "[yellow]Usa: /patch <descrição>  ou  /patch file:<caminho>[/yellow]"
            )
            return
        if args.strip().startswith("file:"):
            path = args.strip()[5:].strip()
            full = self._resolve_project_path(path)
            if full is None or not full.exists():
                return
            try:
                content = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self.console.print(f"[red]Não consegui ler o patch:[/red] {exc}")
                return
            prompt = (
                "Aplica este patch/alteração no projeto. Lê o ficheiro, "
                "identifica onde aplicar e usa as ferramentas para fazer as "
                "mudanças. Se o patch for unificado (--- a/ +++ b/), aplica-o "
                "diretamente. Se for texto livre, converte para alterações "
                "cirúrgicas. Devolve um resumo do que fizeste:\n\n"
                f"{content}"
            )
        else:
            prompt = (
                "Aplica a seguinte alteração no projeto. Faz mudanças "
                "cirúrgicas, mantém o estilo do código e não toques em "
                "ficheiros não relacionados. Devolve um resumo do que "
                "fizeste:\n\n"
                f"{args}"
            )
        await self._chat(prompt)

    def _run_shell(self, args: str) -> None:
        if not args.strip():
            self.console.print(
                "[yellow]Usa: /run <comando>  (executa na pasta do projeto, "
                "captura stdout/stderr)[/yellow]"
            )
            return
        try:
            result = subprocess.run(
                args,
                cwd=self.project_path,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            self.console.print("[red]Timeout (60s) a executar.[/red]")
            return
        except (OSError, subprocess.SubprocessError) as exc:
            self.console.print(f"[red]Erro a executar:[/red] {exc}")
            return
        body: list[RenderableType] = []
        if result.stdout:
            body.append(
                Panel(
                    Syntax(result.stdout, "bash", theme="monokai", line_numbers=True),
                    title="stdout",
                    border_style="green",
                    padding=(0, 1),
                )
            )
        if result.stderr:
            body.append(
                Panel(
                    Syntax(result.stderr, "bash", theme="monokai", line_numbers=True),
                    title="stderr",
                    border_style="red",
                    padding=(0, 1),
                )
            )
        if not body:
            body.append(Text("(sem output)", style=THEME["muted"]))
        body.append(
            Text.assemble(
                ("exit code ", THEME["muted"]),
                (str(result.returncode), "white"),
            )
        )
        self.console.print(Group(*body))

    # ── project / worker commands ───────────────────────────────────────
    async def _change_project(self, value: str) -> None:
        if not value.strip():
            self.console.print(f"Projeto atual: {self.project_path}")
            return
        path = Path(value.strip().strip('"')).expanduser().resolve()
        if not path.is_dir():
            self.console.print(f"[red]Pasta não encontrada:[/red] {path}")
            return
        self.project_path = str(path)
        self.project_index = None
        self.console.print(f"[cyan]Projeto ativo:[/cyan] {self.project_path}")
        await self._scan_project()

    def _spawn_worker(self, arguments: str) -> None:
        try:
            tier, name, prompt = parse_spawn(arguments)
        except ValueError as exc:
            self.console.print(f"[yellow]{exc}[/yellow]")
            return
        active = [
            item
            for item in self.director.list_workers()
            if item.get("state") != WorkerState.DEAD.value
        ]
        if len(active) >= self.max_agents:
            self.console.print(
                f"[yellow]Limite desta sessão atingido ({self.max_agents}). "
                "Usa /kill ou inicia com --max-agents maior (máx. 20).[/yellow]"
            )
            return
        self.director.spawn(tier=tier, name=name, prompt=prompt)

    def _send_worker(self, arguments: str) -> None:
        try:
            worker_id, message = parse_target(arguments)
            result = self.director.send(worker_id, message)
        except (ValueError, KeyError, RuntimeError) as exc:
            self.console.print(f"[yellow]{exc}[/yellow]")
            return
        self.console.print(
            Text.assemble(
                ("→ ", THEME["primary"]),
                (f"{result['worker']} · {result['action']}", "white"),
            )
        )

    async def _wait_workers(self, arguments: str) -> None:
        try:
            target, timeout = parse_wait(arguments)
        except ValueError as exc:
            self.console.print(f"[yellow]{exc}[/yellow]")
            return
        # Show a spinner while waiting — the user gets feedback even when
        # nothing settles within the timeout.
        started = time.monotonic()
        with self.console.status(
            f"[cyan]⏳ à espera de workers ({timeout:g}s)…[/cyan]",
            spinner="dots",
        ):
            results = await self.director.wait(worker_ids=target, timeout=timeout)
        elapsed = time.monotonic() - started
        self._print_worker_rows(
            results, title=f"workers após wait ({elapsed:.1f}s / {timeout:g}s)"
        )

    def _kill_worker(self, arguments: str) -> None:
        target = arguments.strip()
        if target in {"", "all", "*"}:
            count = self.director.kill_all()
            self.console.print(
                Text.assemble(
                    ("✗ ", "red"),
                    (f"{count} worker(s) terminados", "red"),
                )
            )
            return
        try:
            self.director.kill(target)
        except (KeyError, RuntimeError) as exc:
            self.console.print(f"[yellow]{exc}[/yellow]")

    def _print_worker_result(self, arguments: str) -> None:
        worker_id = arguments.strip()
        if not worker_id:
            self.console.print("[yellow]Usa: /result <worker-id>[/yellow]")
            return
        data = self.director.full_output(worker_id)
        if data is None:
            self.console.print(f"[red]Worker desconhecido:[/red] {worker_id}")
            return
        body: list[RenderableType] = []
        if data.get("error"):
            last_turn_status = "falhou"
        elif data["state"] in {"streaming", "spawning"}:
            last_turn_status = "em execução"
        else:
            last_turn_status = "concluído"
        meta = (
            f"id: {data['id']}\n"
            f"name: {data['name']}\n"
            f"tier: {data['tier']}\n"
            f"state: {data['state']}\n"
            f"turns: {data['turns']}\n"
            f"último turno: {last_turn_status}"
        )
        body.append(Panel(Text(meta, style="white"), title="worker", border_style=THEME["primary"]))
        if data.get("last_result"):
            if data.get("error"):
                title = "última resposta concluída antes da falha"
            elif data["state"] in {"streaming", "spawning"}:
                title = "última resposta concluída; worker ainda ativo"
            else:
                title = "última resposta"
            body.append(
                Panel(
                    Markdown(data["last_result"][:6_000]),
                    title=title,
                    border_style=THEME["accent"],
                    padding=(0, 1),
                )
            )
        elif data.get("error"):
            body.append(
                Panel(
                    Text("O último turno falhou e não há uma resposta anterior para mostrar."),
                    title="resultado indisponível",
                    border_style=THEME["tool_err"],
                )
            )
        self.console.print(Group(*body))

    async def _remember(self, content: str) -> None:
        if not content.strip():
            self.console.print("[yellow]Usa: /remember <facto ou decisão do projeto>[/yellow]")
            return
        try:
            result = await remember_project_fact(content, self.project_path)
        except (OSError, RuntimeError, ValueError) as exc:
            self.console.print(f"[red]Memória não guardada:[/red] {exc}")
            return
        self.console.print(
            Text.assemble(
                ("✓ memória persistida", "green"),
                (" · id=", THEME["muted"]),
                (result["memory_id"], "white"),
                (" · projeto=", THEME["muted"]),
                (result["project_path"], "white"),
            )
        )

    def _set_model(self, selector: str) -> None:
        value = selector.strip()
        if not value:
            self.console.print(
                Text.assemble(
                    ("modelo atual: ", THEME["muted"]),
                    (self.requested_model or "auto", "white"),
                    (" · fast=", THEME["muted"]),
                    (resolve_role("smol").model_id or "NOT_RESOLVED", "white"),
                    (" · good=", THEME["muted"]),
                    (resolve_role("slow").model_id or "NOT_RESOLVED", "white"),
                )
            )
            return
        if value.startswith("@"):
            value = value[1:]
        if value in {"fast", "smol", "good", "slow", "deep", "coder", "reasoning"}:
            role = (
                "smol"
                if value in {"fast", "smol"}
                else "slow"
                if value in {"good", "slow", "deep"}
                else "task"
            )
            self.requested_model = resolve_role(role).model_id
        else:
            self.requested_model = value
        self.console.print(
            Text.assemble(
                ("modelo da conversa: ", THEME["muted"]),
                (self.requested_model or "auto", "white"),
            )
        )

    def _print_status(self) -> None:
        indexed = self.project_index or {}
        workers = self.director.list_workers()
        uptime_s = int(time.time() - self._session_started_at)
        body: list[RenderableType] = []
        body.append(
            Text.from_markup(
                "\n".join(
                    [
                        f"[{THEME['muted']}]sessão    [/][white]{self.session_id}[/]",
                        f"[{THEME['muted']}]backend   [/][white]{self.api_url or 'offline'}[/]",
                        f"[{THEME['muted']}]projeto   [/][white]{self.project_path}[/]",
                        f"[{THEME['muted']}]modelo    [/][white]{self.requested_model or 'auto'}[/]",
                        f"[{THEME['muted']}]scan      [/][white]{indexed.get('status', 'NOT_RUN')}[/]",
                        f"[{THEME['muted']}]busy      [/][white]{'sim' if self._busy else 'não'}[/]",
                        f"[{THEME['muted']}]uptime    [/][white]{uptime_s}s[/]",
                        f"[{THEME['muted']}]turnos    [/][white]{self._turns}[/]",
                        f"[{THEME['muted']}]tokens~   [/][white]{self._total_tokens}[/]",
                    ]
                )
            )
        )
        if self._last_turn:
            lt = self._last_turn
            body.append(
                Text.from_markup(
                    "\n".join(
                        [
                            "",
                            f"[bold {THEME['primary']}]último turno[/bold]",
                            f"  {THEME['muted']}há {int(time.time() - lt['ts'])}s · "
                            f"~{lt['tokens']} tokens · {lt['elapsed_ms'] / 1000:.1f}s · "
                            f"{lt['tools']} tools · {lt['advisors']} advisor note(s)[/]",
                            f"  {THEME['muted']}resposta: {lt['answer_chars']:,} chars[/]",
                        ]
                    )
                )
            )
        if self._last_routing:
            r = self._last_routing
            body.append(
                Text.from_markup(
                    "\n".join(
                        [
                            "",
                            f"[bold {THEME['primary']}]último routing[/bold]",
                            f"  {THEME['muted']}agente:[/] "
                            f"[white]{r.get('primary_agent', '?')}[/]"
                            f"  ·  {THEME['muted']}thinking:[/] "
                            f"[white]{r.get('thinking_mode', '?')}[/]",
                            f"  {THEME['muted']}razão:[/] [white]"
                            f"{r.get('routing_reason', '?')}[/]",
                        ]
                    )
                )
            )
        if self._last_error:
            body.append(
                Text.from_markup(
                    f"\n[{THEME['advisor_blocker']}]último erro:[/] "
                    f"[red]{_shorten(self._last_error, 200)}[/]"
                )
            )
        body.append(self._build_workers_table(workers, title="workers"))
        self.console.print(
            Panel(
                Group(*body),
                title="NEXUS status",
                border_style=THEME["primary"],
                padding=(0, 1),
            )
        )

    def _print_history(self, args: str) -> None:
        try:
            limit = max(1, min(int(args.strip() or "30"), 500))
        except ValueError:
            limit = 30
        if not self._history:
            self.console.print("[dim]Histórico vazio.[/dim]")
            return
        recent = self._history[-limit:]
        table = Table(
            title=f"histórico · últimos {len(recent)}/{len(self._history)}",
            box=box.SIMPLE_HEAVY,
            border_style=THEME["accent"],
        )
        table.add_column("#", justify="right", style="cyan", width=4)
        table.add_column("linha", style="white")
        for index, entry in enumerate(recent, start=1):
            display = entry if len(entry) <= 200 else entry[:197] + "…"
            table.add_row(str(index), display)
        self.console.print(table)

    def _print_metrics(self) -> None:
        body = Table(
            title="métricas da sessão",
            box=box.SIMPLE_HEAVY,
            border_style=THEME["accent"],
        )
        body.add_column("métrica", style="white")
        body.add_column("valor", justify="right", style="cyan")
        uptime_s = int(time.time() - self._session_started_at)
        body.add_row("uptime (s)", str(uptime_s))
        body.add_row("turnos do utilizador", str(self._turns))
        body.add_row("tokens~ (soma)", str(self._total_tokens))
        body.add_row("workers ativos", str(
            sum(1 for w in self.director.list_workers()
                if w.get("state") != WorkerState.DEAD.value)
        ))
        body.add_row("workers totais", str(len(self.director.list_workers())))
        body.add_row("histórico (linhas)", str(len(self._history)))
        if self._last_turn:
            body.add_row("último · tokens", str(self._last_turn["tokens"]))
            body.add_row("último · tools", str(self._last_turn["tools"]))
            body.add_row("último · advisor notes", str(self._last_turn["advisors"]))
            body.add_row("último · duração (ms)", str(self._last_turn["elapsed_ms"]))
        self.console.print(body)

    async def _retry_last(self) -> None:
        if self._last_error is None and self._last_turn is None:
            self.console.print(
                "[yellow]Nada para repetir — ainda não houve turnos.[/yellow]"
            )
            return
        # Find the most recent user message in history (skipping commands).
        for candidate in reversed(self._history):
            stripped = candidate.strip()
            if stripped and not stripped.startswith("/"):
                self.console.print(
                    f"[cyan]A repetir:[/cyan] {stripped[:120]}"
                )
                await self._chat(stripped)
                return
        self.console.print("[yellow]Sem prompts anteriores no histórico.[/yellow]")

    def _show_last_context(self) -> None:
        if self._last_routing:
            r = self._last_routing
            body = Text.from_markup(
                "\n".join(
                    [
                        f"[bold {THEME['primary']}]último routing decision[/bold]",
                        f"  primary_agent: [white]{r.get('primary_agent', '?')}[/]",
                        f"  thinking_mode: [white]{r.get('thinking_mode', '?')}[/]",
                        f"  context_needed: [white]{r.get('context_needed', '?')}[/]",
                        f"  task_type: [white]{r.get('task_type', '?')}[/]",
                        f"  confidence: [white]{r.get('routing_confidence', '?')}[/]",
                        f"  reason: [white]{r.get('routing_reason', '?')}[/]",
                    ]
                )
            )
            self.console.print(
                Panel(body, title="contexto do último turno",
                      border_style=THEME["primary"], padding=(0, 1))
            )
        else:
            self.console.print("[dim]Sem routing anterior.[/dim]")

    def _print_logs(self, args: str) -> None:
        """Mostra as últimas advisor notes persistidas em .nexus/trajectories."""
        try:
            limit = max(1, min(int(args.strip() or "20"), 200))
        except ValueError:
            limit = 20
        traj_dir = Path(self.project_path) / ".nexus" / "trajectories"
        if not traj_dir.is_dir():
            self.console.print(
                f"[dim]Sem diretório de trajectories em {traj_dir}[/dim]"
            )
            return
        # match advisor + session if known; fallback to all advisor files
        candidates = sorted(traj_dir.glob("advisor-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            self.console.print("[dim]Sem advisor notes persistidas.[/dim]")
            return
        rows: list[dict[str, Any]] = []
        for path in candidates:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for raw in handle:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            record = json.loads(raw)
                        except ValueError:
                            continue
                        if not isinstance(record, dict):
                            continue
                        rows.append(record)
            except OSError:
                continue
            if len(rows) >= limit * 2:
                break
        if not rows:
            self.console.print("[dim]Sem advisor notes.[/dim]")
            return
        rows.sort(key=lambda r: r.get("ts", ""), reverse=True)
        rows = rows[:limit]
        table = Table(
            title=f"advisor notes · últimas {len(rows)}",
            box=box.SIMPLE_HEAVY,
            border_style=THEME["advisor_concern"],
        )
        table.add_column("ts", style="cyan", width=24)
        table.add_column("sev", style="white", width=10)
        table.add_column("delivered", style="cyan", width=12)
        table.add_column("note", style="white")
        for record in rows:
            severity = str(record.get("severity") or "?").casefold()
            colour = {
                "nit": THEME["advisor_nit"],
                "concern": THEME["advisor_concern"],
                "blocker": THEME["advisor_blocker"],
            }.get(severity, "yellow")
            table.add_row(
                str(record.get("ts", "?")),
                f"[{colour}]{severity}[/]",
                str(record.get("delivered", "?")),
                _shorten(str(record.get("note") or ""), 200),
            )
        self.console.print(table)

    def _print_workers(self) -> None:
        self._print_worker_rows(self.director.list_workers())

    def _build_workers_table(self, rows: list[dict[str, Any]], title: str = "workers") -> Table:
        table = Table(title=title, box=box.SIMPLE_HEAVY, border_style=THEME["primary"])
        for column in ("id", "name", "tier", "state", "turns", "queued", "model", "preview"):
            table.add_column(column)
        for row in rows:
            state = str(row.get("state") or "unknown")
            settlement = row.get("settlement")
            settlement_outcome = (
                str(settlement.get("outcome") or "")
                if isinstance(settlement, dict)
                else ""
            )
            has_error = bool(row.get("error")) or settlement_outcome == "failed"
            if has_error:
                state_label = f"{state} (último turno falhou)"
                preview = str(row.get("preview") or "")
                preview_label = (
                    f"falhou; última resposta concluída: {preview}"
                    if preview
                    else "último turno falhou"
                )
            elif settlement_outcome == "cancelled":
                state_label = f"{state} (turno cancelado)"
                preview_label = "turno cancelado"
            elif settlement_outcome == "completed":
                state_label = f"{state} (turno concluído)"
                preview_label = str(settlement.get("result") or row.get("preview") or "")
            else:
                state_label = state
                preview = str(row.get("preview") or "")
                preview_label = (
                    f"em execução; última resposta concluída: {preview}"
                    if preview and state in {"streaming", "spawning"}
                    else preview
                )
            color = (
                "green"
                if state == "idle"
                else "yellow"
                if state == "streaming"
                else "cyan"
                if state == "spawning"
                else "red"
            )
            tier = str(row.get("tier") or "")
            tier_color = THEME["worker_fast"] if tier == "fast" else THEME["worker_good"]
            table.add_row(
                str(row.get("id") or ""),
                str(row.get("name") or ""),
                f"[{tier_color}]{tier}[/]",
                f"[{color}]{state_label}[/]",
                str(row.get("turns") or 0),
                str(row.get("queued") or 0),
                str(row.get("model") or "auto"),
                _shorten(preview_label, 80),
            )
        return table

    def _print_worker_rows(self, rows: list[dict[str, Any]], title: str = "Workers") -> None:
        table = self._build_workers_table(rows, title=title)
        if rows:
            self.console.print(table)
        else:
            self.console.print("[dim]Nenhum worker nesta sessão.[/dim]")

    def _print_help(self) -> None:
        table = Table(title="NEXUS Terminal — comandos", box=box.SIMPLE_HEAVY, border_style=THEME["primary"])
        table.add_column("Comando", style=f"bold {THEME['primary']}")
        table.add_column("Função", style="white")
        table.add_column("Categoria", style=THEME["muted"])
        rows = [
            ("texto normal", "conversa com o agente PRIMARY", "chat"),
            ("/help", "mostra esta ajuda", "meta"),
            ("/clear", "limpa o ecrã", "meta"),
            ("/exit", "sai e termina workers", "meta"),
            ("", "", ""),
            ("/project <pasta>", "muda o projeto e atualiza contexto", "projeto"),
            ("/scan", "analisa projeto e indexa alterações", "projeto"),
            ("/index", "reanalisa o perfil e atualiza o índice", "projeto"),
            ("/find <pergunta>", "procura na memória e no índice de código", "projeto"),
            ("/tree [depth] [path]", "mostra a árvore de pastas", "projeto"),
            ("/open <ficheiro>", "abre um ficheiro com syntax highlight", "projeto"),
            ("/grep <padrão> [--ext py,ts] [--path sub]", "procura texto em ficheiros", "projeto"),
            ("/diff <ficheiro|base>", "mostra diff git", "projeto"),
            ("/patch <descrição|file:path>", "pede ao agente para aplicar uma alteração", "projeto"),
            ("/run <cmd>", "executa um comando shell na pasta do projeto", "projeto"),
            ("", "", ""),
            ("/spawn fast|good \"nome\" :: tarefa", "cria worker em background", "agentes"),
            ("/agents", "lista workers ativos e estado", "agentes"),
            ("/result <id>", "mostra a última resposta completa de um worker", "agentes"),
            ("/send <id> <mensagem>", "envia continuação a um worker", "agentes"),
            ("/wait [--timeout=NN] [id]", "espera resultados dos workers", "agentes"),
            ("/kill <id|all>", "termina um ou todos os workers", "agentes"),
            ("", "", ""),
            ("/remember <facto>", "guarda uma decisão/facto do projeto", "memória"),
            ("/model [tier|id]", "seleciona modelo para a conversa", "memória"),
            ("/status", "mostra sessão, projeto, scan, último turno, workers", "memória"),
            ("/history [N]", "mostra os últimos N prompts (até 500)", "memória"),
            ("/metrics", "métricas agregadas da sessão", "memória"),
            ("/ctx", "último routing decision + reasoning", "memória"),
            ("/retry", "repete o último prompt do histórico", "memória"),
            ("/logs [N]", "mostra as últimas N advisor notes persistidas", "memória"),
        ]
        for command, description, category in rows:
            if not command and not description:
                table.add_row("", "", "")
            else:
                table.add_row(command, description, category)
        self.console.print(table)
        self.console.print(
            Panel(
                Text.from_markup(
                    "Atalhos:\n"
                    "  • [bold]↑/↓[/bold] no input — histórico (readline)\n"
                    "  • [bold]Ctrl+C[/bold] durante um chat cancela o turno e liberta o input\n"
                    "  • [bold]/retry[/bold] repete o último prompt se algo correu mal\n\n"
                    "Diferenças face ao NEXUS Dashboard:\n"
                    "  • o dashboard é a UI visual no browser (localhost:3000)\n"
                    "  • o terminal é este REPL — partilha o mesmo backend, modelos e memória\n"
                    "  • podes correr os dois ao mesmo tempo: sessão diferente, mesmo cérebro\n\n"
                    "Sinais visuais durante o chat:\n"
                    "  • [magenta]router → NEXUS · deep[/magenta] — quem trata do turno\n"
                    "  • [grey58]⠋ thinking…[/grey58] — raciocínio do modelo em tempo real\n"
                    "  • [cyan]tool #N · nome[/cyan] — chamada a ferramenta (cyan=run, ✓=ok, ✗=err)\n"
                    "  • [blue]advisor · nit[/blue] — nota do advisor (azul=nit, amarelo=concern, vermelho=blocker)\n"
                    "  • [violet]NEXUS[/violet] — resposta em streaming com tokens contados"
                ),
                title="sobre o terminal",
                border_style=THEME["accent"],
                padding=(0, 1),
            )
        )

    # ── small utilities ────────────────────────────────────────────────
    def _resolve_project_path(self, value: str) -> Path | None:
        cleaned = value.strip().strip('"').strip("'")
        if not cleaned:
            self.console.print("[yellow]Indica um caminho.[/yellow]")
            return None
        path = Path(cleaned).expanduser()
        if not path.is_absolute():
            path = (Path(self.project_path) / path).resolve()
        return path

    def _parse_depth_and_path(self, args: str, default_depth: int) -> tuple[int, str | None]:
        depth = default_depth
        subpath: str | None = None
        for token in args.split():
            if token.startswith("--depth="):
                try:
                    depth = max(1, min(int(token.split("=", 1)[1]), 8))
                except ValueError:
                    pass
            elif subpath is None and not token.startswith("-"):
                subpath = token
        return depth, subpath


# ─────────────────────────────────────────────────────────────────────────
# regex helper (kept here to avoid a top-level import if readline missing)
# ─────────────────────────────────────────────────────────────────────────


def re_compile(pattern: str, ignore_case: bool) -> "re.Pattern[str] | None":  # type: ignore[name-defined]
    import re  # local import keeps the module import surface clean

    try:
        flags = re.IGNORECASE if ignore_case else 0
        return re.compile(pattern, flags=flags)
    except re.error as exc:
        # surface a clear error using the console of the caller
        print(f"padrão inválido: {exc}", file=sys.stderr)
        return None


# ─────────────────────────────────────────────────────────────────────────
# entry point
# ─────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="NEXUS Terminal — agentic CLI for NEXUS IDE (Claude-Code style)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            exemplos:
              .venv\\Scripts\\python.exe scripts\\nexus_terminal.py --project .
              .venv\\Scripts\\python.exe scripts\\nexus_terminal.py --project ../outro
              .venv\\Scripts\\python.exe scripts\\nexus_terminal.py --offline --no-scan
              .venv\\Scripts\\python.exe scripts\\nexus_terminal.py --session minha-sessao
            """
        ),
    )
    parser.add_argument("--project", default=os.getcwd(), help="pasta do projeto ativo")
    parser.add_argument(
        "--session",
        default="",
        help="session_id NEXUS (continua uma sessão existente)",
    )
    parser.add_argument(
        "--api-url",
        default="",
        help="URL do backend; por defeito testa as portas 8001 e 8000",
    )
    parser.add_argument("--token", default="", help="JWT; preferível a NEXUS_ACCESS_TOKEN")
    parser.add_argument("--model", default="", help="modelo ou tier para a conversa principal")
    parser.add_argument("--max-agents", type=int, default=8, help="workers ativos nesta sessão (1-20)")
    parser.add_argument("--no-scan", action="store_true", help="não indexar automaticamente no arranque")
    parser.add_argument("--offline", action="store_true", help="apenas scan/memória, sem backend")
    parser.add_argument("--verbose", action="store_true", help="mostrar thinking completo e estados idle")
    return parser


async def _async_main(args: argparse.Namespace) -> int:
    terminal = NexusTerminal(args)
    return await terminal.run()


def main() -> int:
    try:
        return asyncio.run(_async_main(build_parser().parse_args()))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
