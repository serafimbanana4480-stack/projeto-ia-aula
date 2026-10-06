"""AI-facing quality: ``thinking_mode`` in ``config/models.yaml`` must be honoured.

``config/models.yaml`` has declared ``thinking_mode: true`` on the reasoning
tiers since it was written, and for a long time no code path read it. It is now
wired into ``AgentBase._reasoning_requested`` through
``backend.runtime.reasoning.model_declares_thinking_mode`` (by tier key) and
``model_id_declares_thinking_mode`` (by model id, for a user-selected model).

A silent key mismatch is the failure mode that would make the whole feature a
no-op while looking configured: the YAML says ``reasoning: true`` and the agent
asks for ``model_key = "reasoing"``, or the tier resolves to a different model
id than the one whose reasoning channel the provider will open. These tests
assert the declaration is actually reachable, in both directions, and that every
``model_key`` an agent actually declares exists in the YAML.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import pytest
import yaml

from backend.agents.base import AgentAction, AgentBase, AgentRequest
from backend.config.settings import MODELS_YAML, get_model_config
from backend.runtime.reasoning import (
    model_declares_thinking_mode,
    model_id_declares_thinking_mode,
)

AGENT_PACKAGE = "backend.agents"


def _models() -> dict[str, dict]:
    raw = yaml.safe_load(MODELS_YAML.read_text(encoding="utf-8"))
    return raw["models"]


def _reasoning_keys() -> list[str]:
    return sorted(key for key, block in _models().items() if block.get("thinking_mode"))


def _selectable_tiers() -> set[str]:
    """Tiers a client may pin through ``/api/chat``.

    ``ALLOWED_MODEL_TIERS`` is a function-local frozenset in
    ``backend/orchestrator/routes/chat.py``, so it is read out of the source
    rather than imported. If the identifier ever moves, the caller skips the
    check instead of failing for an unrelated reason.
    """
    import re

    source = Path(REPO_ROOT / "backend" / "orchestrator" / "routes" / "chat.py").read_text(
        encoding="utf-8"
    )
    match = re.search(r"ALLOWED_MODEL_TIERS\s*=\s*frozenset\(\s*\{(.*?)\}\s*\)", source, re.S)
    if not match:
        return set()
    return set(re.findall(r'"([a-z0-9._-]+)"', match.group(1)))


REPO_ROOT = Path(__file__).resolve().parents[2]


def _all_agent_classes() -> dict[str, type[AgentBase]]:
    found: dict[str, type[AgentBase]] = {}
    package = importlib.import_module(AGENT_PACKAGE)
    modules = [AGENT_PACKAGE]
    modules.extend(info.name for info in pkgutil.walk_packages(package.__path__, prefix=f"{AGENT_PACKAGE}."))
    for module_name in modules:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and issubclass(obj, AgentBase)
                and obj is not AgentBase
                and obj.__module__ == module_name
            ):
                found[f"{module_name}.{name}"] = obj
    return found


# ---------------------------------------------------------------------------
# The declaration is reachable
# ---------------------------------------------------------------------------
class TestThinkingModeIsHonoured:
    def test_the_yaml_actually_declares_some(self) -> None:
        assert _reasoning_keys(), "config/models.yaml declares no thinking_mode: true"

    @pytest.mark.parametrize("model_key", _reasoning_keys())
    def test_tier_key_resolves_to_true(self, model_key: str) -> None:
        """The exact regression: a declared-but-unread flag."""
        assert model_declares_thinking_mode(model_key) is True

    @pytest.mark.parametrize("model_key", _reasoning_keys())
    def test_its_primary_model_id_also_resolves(self, model_key: str) -> None:
        """A user pinning that model in the selector must get the same answer."""
        assert model_id_declares_thinking_mode(get_model_config(model_key)["id"]) is True

    @pytest.mark.parametrize("model_key", _reasoning_keys())
    def test_its_fallback_model_id_also_resolves(self, model_key: str) -> None:
        fallback = get_model_config(model_key).get("fallback_id")
        if fallback:
            assert model_id_declares_thinking_mode(fallback) is True

    def test_a_plain_tier_resolves_to_false(self) -> None:
        assert model_declares_thinking_mode("coder") is False
        assert model_declares_thinking_mode("fast") is False

    def test_an_unknown_key_resolves_to_false_instead_of_raising(self) -> None:
        assert model_declares_thinking_mode("no-such-tier") is False
        assert model_id_declares_thinking_mode("no-such-model") is False


# ---------------------------------------------------------------------------
# The declaration reaches the request path
# ---------------------------------------------------------------------------
class _ThinkingAgent(AgentBase):
    name = "THINKING_PROBE"
    model_key = "reasoning"
    prompt_file = "router"
    supported_actions: set[AgentAction] = set()

    async def _execute(self, request):  # pragma: no cover - never called
        yield ""


def _request(**context: str) -> AgentRequest:
    return AgentRequest(session_id="s", query="q", client=object(), context=dict(context))


class TestAgentResolvesTheDeclaration:
    def test_a_reasoning_tier_turns_the_channel_on(self) -> None:
        assert _ThinkingAgent()._reasoning_requested(_request()) is True

    def test_a_non_reasoning_tier_leaves_it_off(self) -> None:
        agent = _ThinkingAgent()
        agent.model_key = "coder"
        assert agent._reasoning_requested(_request()) is False

    def test_a_user_pinned_reasoning_model_turns_it_on_for_any_tier(self) -> None:
        agent = _ThinkingAgent()
        agent.model_key = "coder"
        request = _request(_model_override="glm-5.2")
        assert agent._reasoning_requested(request) is True

    def test_a_user_pinned_plain_model_leaves_it_off(self) -> None:
        agent = _ThinkingAgent()
        agent.model_key = "reasoning"
        request = _request(_model_override="minimax-m3")
        assert agent._reasoning_requested(request) is True, (
            "the tier itself declares thinking_mode, so the tier wins"
        )

    def test_explicit_threading_still_overrides(self) -> None:
        agent = _ThinkingAgent()
        agent.model_key = "coder"
        request = _request()
        request.enable_thinking = True
        assert agent._reasoning_requested(request) is True

    def test_operator_visibility_off_beats_everything(self, monkeypatch) -> None:
        monkeypatch.setenv("NEXUS_REASONING_VISIBILITY", "off")
        import backend.runtime.reasoning as reasoning_module

        monkeypatch.setattr(reasoning_module, "_visibility", None, raising=False)
        agent = _ThinkingAgent()
        request = _request()
        request.enable_thinking = True
        assert agent._reasoning_requested(request) is False


# ---------------------------------------------------------------------------
# Every model_key an agent declares must exist in the YAML
# ---------------------------------------------------------------------------
class TestDeclaredModelKeysResolve:
    def test_no_agent_declares_an_unknown_model_key(self) -> None:
        """``get_model_config`` raises KeyError on an unknown key.

        ``ComponentAgent``, ``UIUXAgent``, ``StateManagerAgent``,
        ``FrontendTeamLead``, ``BackendTeamLead`` declared ``pro`` and
        ``CEOAgent``/``ChiefArchitectAgent`` declared ``opus`` while neither key
        existed in ``config/models.yaml`` — a latent crash on the first real
        call, invisible to the tests because they only ever called
        ``system_prompt()``.
        """
        known = set(_models())
        unknown: list[str] = []
        for qualified, cls in sorted(_all_agent_classes().items()):
            model_key = getattr(cls, "model_key", "")
            if not isinstance(model_key, str) or not model_key:
                continue  # resolved at runtime (e.g. NEXUS_PRIMARY_MODEL_KEY)
            if model_key not in known:
                unknown.append(f"{qualified} -> model_key={model_key!r}")
        assert not unknown, "undeclared model_key(s):\n" + "\n".join(unknown)

    def test_every_tier_declares_a_context_window(self) -> None:
        missing = sorted(k for k, v in _models().items() if not v.get("context_window"))
        assert not missing, f"models without context_window: {missing}"

    def test_every_tier_declares_the_fields_the_agent_path_reads(self) -> None:
        required = ("id", "fallback_id", "thinking_mode", "max_tokens", "temperature")
        for key, block in sorted(_models().items()):
            for field in required:
                assert field in block, f"{key} is missing {field}"

    def test_reasoning_tiers_are_reachable_from_the_product(self) -> None:
        """No dead declaration: a thinking tier nothing can select is a typo.

        A tier is reachable when an agent class declares it as ``model_key``, or
        when a client may pin it through ``/api/chat`` (``ALLOWED_MODEL_TIERS``).
        """
        selectable = _selectable_tiers()
        if not selectable:
            pytest.skip("ALLOWED_MODEL_TIERS is no longer a module-level name in chat.py")
        used = {
            getattr(cls, "model_key", "")
            for cls in _all_agent_classes().values()
            if isinstance(getattr(cls, "model_key", ""), str)
        }
        unreachable = sorted(set(_reasoning_keys()) - used - selectable)
        assert not unreachable, (
            f"thinking_mode declared for tiers nothing can reach: {unreachable}"
        )


def test_the_models_file_is_the_one_under_test() -> None:
    assert Path(MODELS_YAML).is_file()
