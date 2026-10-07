"""AI-facing quality guard: no machine-specific or personal data in any prompt.

A system prompt is shipped verbatim to a third-party model provider. Anything
that identifies the machine or the person who happens to be running the IDE —
an absolute home directory, an email address, a credential-looking literal —
leaks on every single request and tells the model about an environment it is
not in. It also hardcodes an assumption that silently rots: the tool contract
used to hardcode ``Windows with PowerShell`` and one developer's real path
(``C:\\Users\\<name>\\Desktop\\...``) in a Python literal recompiled for every
agent on every call.

This module is the cheap, permanent guard. It fails loudly and names the file
and the line so the offending text can be replaced with a placeholder
(``C:\\Users\\<username>\\...``) or derived from the platform.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = REPO_ROOT / "config" / "prompts"
AGENT_BASE = REPO_ROOT / "backend" / "agents" / "base.py"
AGENT_PACKAGE = REPO_ROOT / "backend" / "agents"

#: ``C:\Users\<name>`` / ``C:/Users/<name>`` where ``<name>`` contains at least
#: one alphanumeric character. A pure-punctuation segment (``...``, ``***``) and
#: an angle-bracket placeholder (``<username>``) are the two accepted ways to
#: write "somebody's home directory" without naming somebody.
_WINDOWS_USER_PATH = re.compile(
    r"[Cc]:[\\/]{1,2}[Uu]sers[\\/]{1,2}(?P<segment>[^\s\"'`<>|:*?/\\]+)"
)

#: Local-part @ domain. Deliberately strict: prompts may legitimately mention
#: ``user@example.com`` as an *example* address, so the domain must not be a
#: real-looking one.
_EMAIL = re.compile(
    r"(?<![\w.+-])[A-Za-z0-9._%+-]+@(?P<domain>[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)"
)

#: Domains that are safe to appear in an example.
_EXAMPLE_EMAIL_DOMAINS = frozenset(
    {
        "example.com",
        "example.org",
        "example.net",
        "example",
        "test",
        "localhost",
        "invalid",
        "email.com",
        "domain.com",
        "yourdomain.com",
        "company.com",
    }
)

#: Literal fragments of anything that looks like a credential. Each pattern
#: demands the fixed length/entropy of the real token format, so ordinary
#: English words ending in "sk-" (risk-, task-, disk-) cannot trip it.
_SECRET_PATTERNS = (
    re.compile(r"\bsk-(?:live|test|proj)?-?[A-Za-z0-9]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{12,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |PGP )?PRIVATE KEY-----"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),
    re.compile(r"\bBearer\s+eyJ[A-Za-z0-9_-]{10,}"),
)

#: Files scanned for inline prompt text. ``base.py`` holds every prompt block
#: that is still a Python literal; the other agents hold a handful more.
_AGENT_MODULES = (
    AGENT_BASE,
    AGENT_PACKAGE / "micro.py",
    AGENT_PACKAGE / "debate_system.py",
    AGENT_PACKAGE / "enhanced_debate" / "logical_judge.py",
)


def _prompt_files() -> list[Path]:
    return sorted(PROMPTS_DIR.glob("*.md"))


def _scan(text: str, label: str) -> list[str]:
    """Return every finding in *text*, formatted for an assertion message."""
    findings: list[str] = []

    for match in _WINDOWS_USER_PATH.finditer(text):
        segment = match.group("segment")
        if not any(char.isalnum() for char in segment):
            continue  # "..." / "***" — a placeholder, not a person
        line = text.count("\n", 0, match.start()) + 1
        findings.append(
            f"{label}:{line}: absolute Windows user path {match.group(0)!r} "
            "(use C:\\Users\\<username>\\... instead)"
        )

    for match in _EMAIL.finditer(text):
        domain = match.group("domain").lower()
        if domain in _EXAMPLE_EMAIL_DOMAINS or domain.endswith(".example"):
            continue
        line = text.count("\n", 0, match.start()) + 1
        findings.append(f"{label}:{line}: email address {match.group(0)!r}")

    for pattern in _SECRET_PATTERNS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            findings.append(
                f"{label}:{line}: secret-looking literal {match.group(0)[:24]!r}"
            )

    return findings


# ---------------------------------------------------------------------------
# The scanned surface must exist — a guard that scans nothing is not a guard
# ---------------------------------------------------------------------------
class TestScanSurfaceIsReal:
    def test_prompt_files_are_found(self) -> None:
        found = _prompt_files()
        assert len(found) >= 30, f"only found {len(found)} prompt files under {PROMPTS_DIR}"
        assert (PROMPTS_DIR / "tool_usage_contract.md").is_file()

    def test_every_agent_module_scanned_exists(self) -> None:
        for path in _AGENT_MODULES:
            assert path.is_file(), f"guard would silently skip a missing file: {path}"


# ---------------------------------------------------------------------------
# config/prompts/**
# ---------------------------------------------------------------------------
class TestPromptFilesAreClean:
    def test_no_prompt_file_carries_machine_specific_or_personal_data(self) -> None:
        findings: list[str] = []
        for path in _prompt_files():
            findings.extend(_scan(path.read_text(encoding="utf-8"), str(path)))
        assert not findings, "prompt hygiene violations:\n" + "\n".join(findings)

    @pytest.mark.parametrize("name", ["advisor.md", "preflight_validator.md"])
    def test_the_newly_written_prompts_are_clean(self, name: str) -> None:
        path = PROMPTS_DIR / name
        assert path.is_file(), path
        assert not _scan(path.read_text(encoding="utf-8"), str(path))


# ---------------------------------------------------------------------------
# Inline prompt literals in backend/agents/**
# ---------------------------------------------------------------------------
def _string_literals(path: Path) -> list[tuple[int, str]]:
    """Return ``(lineno, value)`` for every string constant in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    literals: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.append((node.lineno, node.value))
    return literals


class TestInlineAgentPromptsAreClean:
    def test_inline_prompt_literals_carry_no_personal_data(self) -> None:
        findings: list[str] = []
        for path in _AGENT_MODULES:
            for lineno, value in _string_literals(path):
                findings.extend(_scan(value, f"{path}:{lineno}"))
        assert not findings, "prompt hygiene violations:\n" + "\n".join(findings)

    def test_the_known_personal_path_is_gone(self) -> None:
        """The literal that started this: a real home directory in a prompt."""
        source = AGENT_BASE.read_text(encoding="utf-8")
        for banned in ("rodri", "desligar", "Desktop\\nexus", "Desktop/nexus"):
            assert banned not in source, f"base.py still contains {banned!r}"

    def test_the_tool_contract_prompt_carries_no_personal_data(self) -> None:
        text = (PROMPTS_DIR / "tool_usage_contract.md").read_text(encoding="utf-8")
        assert "rodri" not in text
        assert "{{ABSOLUTE_PATH_EXAMPLE}}" in text, (
            "the absolute-path example must be a placeholder substituted from "
            "the platform, never literal text in the shared prompt file"
        )
        from backend.agents.nexus_primary import NexusPrimaryAgent

        assert "<username>" in NexusPrimaryAgent()._build_tool_instructions()


# ---------------------------------------------------------------------------
# The guard itself: a scanner that cannot fail is not a guard
# ---------------------------------------------------------------------------
class TestScannerDetectsViolations:
    @pytest.mark.parametrize(
        "text,expected",
        [
            (r"see C:\Users\rodri\Desktop\x.txt", "absolute Windows user path"),
            ("see C:/Users/rodri/Desktop/x.txt", "absolute Windows user path"),
            ("mail me at joao.silva@empresa.pt", "email address"),
            ("token sk-abcdefghijklmnopqrstuvwxyz0123", "secret-looking literal"),
            ("AKIAIOSFODNN7EXAMPLE", "secret-looking literal"),
            ("-----BEGIN RSA PRIVATE KEY-----", "secret-looking literal"),
        ],
        ids=["backslash", "slash", "email", "openai", "aws", "pem"],
    )
    def test_it_flags_a_planted_violation(self, text: str, expected: str) -> None:
        findings = _scan(text, "planted")
        assert findings, f"the scanner missed {text!r}"
        assert any(expected in finding for finding in findings), findings

    @pytest.mark.parametrize(
        "text",
        [
            r"use C:\Users\<username>\Desktop\notes.txt",
            r"use C:\Users\... as an example",
            "write to user@example.com",
            "the risk-based and task-based split",
            "a disk-backed store",
            "no credentials are configured",
        ],
        ids=["placeholder", "ellipsis", "example-email", "risk-word", "disk-word", "prose"],
    )
    def test_it_accepts_placeholders_and_ordinary_prose(self, text: str) -> None:
        assert _scan(text, "clean") == []

    def test_the_scan_finds_the_line_number(self) -> None:
        findings = _scan("first line\nsecond C:\\Users\\rodri\\x\n", "f")
        assert findings and ":2:" in findings[0]


# ---------------------------------------------------------------------------
# The host-OS statement must be derived, not baked in
# ---------------------------------------------------------------------------
class TestHostStatementIsDerived:
    def test_the_contract_prompt_has_a_placeholder_not_a_hardcoded_host(self) -> None:
        text = (PROMPTS_DIR / "tool_usage_contract.md").read_text(encoding="utf-8")
        assert "{{HOST_ENVIRONMENT}}" in text
        assert "{{TOOL_LIST}}" in text
        assert "Windows with PowerShell" not in text, (
            "the host OS belongs in base.py._host_environment(), derived from "
            "platform.system() — not in the shared prompt file"
        )

    def test_the_placeholder_is_always_substituted(self) -> None:
        from backend.agents.nexus_primary import NexusPrimaryAgent

        rendered = NexusPrimaryAgent()._build_tool_instructions()
        assert "{{" not in rendered, "an unsubstituted placeholder reached the model"
        assert "HOST ENVIRONMENT" in rendered
        assert "CRITICAL RULES" in rendered
        assert "Available tools:" in rendered

    def test_the_rendered_example_path_is_valid_json(self) -> None:
        import json
        import re

        from backend.agents.nexus_primary import NexusPrimaryAgent

        rendered = NexusPrimaryAgent()._build_tool_instructions()
        match = re.search(
            r"EXAMPLE - create a file with an absolute path:\n```tool\n(.+)\n```",
            rendered,
        )
        assert match, "the absolute-path example disappeared from the prompt"
        payload = json.loads(match.group(1))
        assert payload["name"] == "write_file_absolute"
        assert "<username>" in payload["arguments"]["path"]

    def test_the_host_sentence_follows_the_actual_platform(self) -> None:
        import platform

        from backend.agents.base import AgentBase

        host, example = AgentBase._host_environment()
        if platform.system() == "Windows":
            assert "Windows" in host
            assert "PowerShell" in host
            assert example.startswith("C:\\")
        else:
            assert "Get-ChildItem" not in host
            assert example.startswith("/")
