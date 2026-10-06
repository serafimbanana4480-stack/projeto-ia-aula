"""Small, deterministic command grammar for the NEXUS Terminal REPL."""

from __future__ import annotations

import math
import shlex
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TerminalCommand:
    name: str
    arguments: str
    raw: str


VIBE_CONTROL_COMMANDS = frozenset(
    {"agents", "workers", "spawn", "send", "wait", "kill", "result"}
)


def parse_command(line: str) -> TerminalCommand | None:
    """Parse a slash command; normal language returns ``None``."""
    raw = line.strip()
    if not raw.startswith("/"):
        return None
    body = raw[1:].lstrip()
    if not body:
        return TerminalCommand(name="help", arguments="", raw=raw)
    parts = body.split(None, 1)
    name = parts[0]
    arguments = parts[1] if len(parts) > 1 else ""
    return TerminalCommand(name=name.casefold(), arguments=arguments.strip(), raw=raw)


def parse_vibe_control(line: str) -> TerminalCommand | None:
    """Return only commands handled by a session's Vibe worker director."""
    command = parse_command(line)
    if command is not None and command.name in VIBE_CONTROL_COMMANDS:
        return command
    return None


def parse_spawn(arguments: str) -> tuple[str, str, str]:
    """Parse ``/spawn fast \"API reviewer\" :: review the project``."""
    left, separator, prompt = arguments.partition("::")
    if not separator:
        raise ValueError("usa: /spawn <fast|good> <nome> :: <tarefa>")
    try:
        parts = shlex.split(left.strip(), posix=True)
    except ValueError as exc:
        raise ValueError(f"nome do agente inválido: {exc}") from exc
    if len(parts) < 2:
        raise ValueError("usa: /spawn <fast|good> <nome> :: <tarefa>")
    tier = parts[0].casefold()
    if tier not in {"fast", "good"}:
        raise ValueError("o tier tem de ser 'fast' ou 'good'")
    task = prompt.strip()
    if not task:
        raise ValueError("a tarefa do agente não pode ficar vazia")
    return tier, " ".join(parts[1:]), task


def parse_target(arguments: str) -> tuple[str, str]:
    """Split an agent id from the message used by ``/send``."""
    parts = arguments.split(None, 1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise ValueError("usa: /send <worker-id> <mensagem>")
    return parts[0].strip(), parts[1].strip()


def parse_wait(arguments: str) -> tuple[list[str] | None, float]:
    """Parse ``/wait [--timeout=SECONDS] [worker-id]`` with bounded time."""
    try:
        parts = shlex.split(arguments, posix=True)
    except ValueError as exc:
        raise ValueError(f"argumentos de /wait inválidos: {exc}") from exc

    timeout = 30.0
    timeout_seen = False
    target: str | None = None
    index = 0
    while index < len(parts):
        token = parts[index]
        if token == "--timeout" or token.startswith("--timeout="):
            if timeout_seen:
                raise ValueError("usa apenas um argumento --timeout")
            timeout_seen = True
            if token == "--timeout":
                index += 1
                if index >= len(parts):
                    raise ValueError("falta o valor de --timeout")
                raw_timeout = parts[index]
            else:
                raw_timeout = token.split("=", 1)[1]
            try:
                timeout = float(raw_timeout)
            except ValueError as exc:
                raise ValueError("--timeout tem de ser um número entre 0.1 e 600") from exc
            if not math.isfinite(timeout) or not 0.1 <= timeout <= 600:
                raise ValueError("--timeout tem de ser um número entre 0.1 e 600")
        elif token.startswith("-"):
            raise ValueError(f"opção de /wait desconhecida: {token}")
        elif target is None:
            target = token
        else:
            raise ValueError("usa: /wait [--timeout=SEGUNDOS] [worker-id]")
        index += 1

    return ([target] if target else None), timeout


__all__ = [
    "VIBE_CONTROL_COMMANDS",
    "TerminalCommand",
    "parse_command",
    "parse_spawn",
    "parse_target",
    "parse_vibe_control",
    "parse_wait",
]
