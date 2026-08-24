"""Harness end-to-end com provider instrumentado.

Corre a stack real (FastAPI + rota /api/chat + NEXUS PRIMARY + loop ReAct +
ferramentas reais) contra um provider OpenAI-compatible *guionado*, que:

* regista o prompt exato enviado em cada chamada;
* devolve respostas escolhidas por nós.

Ao controlar o "modelo", separa-se a qualidade do modelo da qualidade do
sistema e responde-se à pergunta que interessa: **se o modelo for competente,
o NEXUS entrega o resultado dele ao utilizador?**

Executar:  python -m backend.tests.e2e_audit_harness
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

os.environ.setdefault("OPENROUTER_API_KEY", "harness")
os.environ.setdefault("NEXUS_FREE_ONLY", "false")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


class ScriptedProvider:
    """An OpenAI-compatible endpoint that records prompts and replays answers."""

    def __init__(self) -> None:
        self.prompts: list[list[dict[str, Any]]] = []
        self.script: list[str] = []
        self.calls = 0

    def load(self, answers: list[str]) -> None:
        self.script = list(answers)
        self.prompts.clear()
        self.calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions") or request.url.path == "/api/chat":
            body = json.loads(request.content or b"{}")
            self.prompts.append(body.get("messages", []))
            index = min(self.calls, len(self.script) - 1) if self.script else 0
            answer = self.script[index] if self.script else "sem guião"
            self.calls += 1
            if request.url.path == "/api/chat":
                frames = [
                    json.dumps({"message": {"content": answer}, "done": False}),
                    json.dumps(
                        {
                            "done": True,
                            "done_reason": "stop",
                            "prompt_eval_count": 100,
                            "eval_count": 50,
                        }
                    ),
                ]
                return httpx.Response(200, content=("\n".join(frames) + "\n").encode())
            chunks = [
                "data: "
                + json.dumps(
                    {"choices": [{"delta": {"content": answer}, "finish_reason": None}]}
                ),
                "data: "
                + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                "data: [DONE]",
            ]
            return httpx.Response(200, content=("\n\n".join(chunks) + "\n\n").encode())
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "scripted/model"}]})
        return httpx.Response(404)

    # -- introspection helpers --------------------------------------
    def last_prompt_text(self) -> str:
        if not self.prompts:
            return ""
        return "\n".join(str(m.get("content", "")) for m in self.prompts[-1])

    def prompt_chars(self) -> list[int]:
        return [
            sum(len(str(m.get("content", ""))) for m in messages) for messages in self.prompts
        ]

    def has_assistant_turn(self, index: int = -1) -> bool:
        if not self.prompts:
            return False
        return any(m.get("role") == "assistant" for m in self.prompts[index])


PROVIDER = ScriptedProvider()


def build_client(project_dir: Path):
    from fastapi.testclient import TestClient

    from backend.middleware.auth import create_access_token
    from backend.orchestrator import main as main_module
    from backend.tools.ollama_client import OllamaClient

    transport = httpx.MockTransport(PROVIDER.handler)
    original_init = OllamaClient.__init__

    def patched_init(self, base_url: str = "", *, transport_=None, timeout=None, limits=None, **kw):
        kwargs: dict[str, Any] = {"transport": transport}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if limits is not None:
            kwargs["limits"] = limits
        return original_init(self, base_url, **kwargs)

    OllamaClient.__init__ = patched_init  # type: ignore[method-assign]
    for attr in ("ollama", "llm_client"):
        if hasattr(main_module.app.state, attr):
            delattr(main_module.app.state, attr)

    import backend.llm as llm_pkg
    from backend.llm.factory import create_llm_client

    llm_pkg.create_llm_client = lambda: create_llm_client(  # type: ignore[assignment]
        multi_llm_enabled=False,
        llm_provider="ollama",
        ollama_host="http://ollama.test",
        free_only=False,
    )

    token = create_access_token({"sub": "harness", "email": "harness@test"})
    return TestClient(main_module.app, headers={"Authorization": f"Bearer {token}"})


def sse(body: bytes) -> list[dict]:
    return [
        json.loads(line[6:])
        for line in body.decode().splitlines()
        if line.startswith("data: ")
    ]


def visible_text(events: list[dict]) -> str:
    return "".join(e.get("content") or "" for e in events if e.get("type") == "token")
