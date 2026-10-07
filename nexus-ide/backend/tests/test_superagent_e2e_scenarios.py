"""Run the scripted end-to-end audit scenarios against an isolated app lifespan."""

from __future__ import annotations


def test_scripted_primary_chat_scenarios_pass_in_isolation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "scripted-e2e")
    monkeypatch.setenv("NEXUS_FREE_ONLY", "false")
    monkeypatch.setenv("NEXUS_BACKGROUND_SERVICES", "off")
    monkeypatch.setenv("NEXUS_ENABLE_BACKGROUND_WORKERS", "false")
    monkeypatch.setenv("NEXUS_ENABLE_DASHBOARD_AGENT", "false")
    monkeypatch.setenv("NEXUS_ENABLE_GUARDIAN_AGENT", "false")
    monkeypatch.setenv("NEXUS_ENABLE_AUTO_CORRECTION", "false")
    monkeypatch.setenv("NEXUS_ENABLE_EXEC_ENGINE", "false")
    monkeypatch.setenv("NEXUS_ENABLE_CONTINUOUS_IMPROVEMENT", "false")
    monkeypatch.setenv("NEXUS_ENABLE_SELF_IMPROVEMENT", "false")
    monkeypatch.setenv("NEXUS_ENABLE_SELF_HEALING", "false")
    monkeypatch.setenv("NEXUS_ENABLE_AI_ORCHESTRATOR", "false")
    monkeypatch.setenv("NEXUS_ENABLE_AUTO_TRIGGER", "false")
    monkeypatch.setenv("NEXUS_ENABLE_SESSION_GC", "false")
    monkeypatch.setenv("NEXUS_EVENT_JOURNAL", "1")
    monkeypatch.setenv("NEXUS_EXPERIENCE_OFF", "1")

    import backend.config.settings as settings_module

    previous_settings = settings_module._settings_instance
    settings_module._settings_instance = None
    settings_module.get_settings.cache_clear()

    import backend.llm as llm_package
    from backend.observability import logging_config
    from backend.orchestrator import main as main_module
    from backend.runtime import events as runtime_events
    from backend.tools.ollama_client import OllamaClient

    previous_ollama_init = OllamaClient.__init__
    previous_factory = llm_package.create_llm_client
    previous_setup_logging = logging_config.setup_logging
    monkeypatch.setattr(logging_config, "setup_logging", lambda **_kwargs: None)
    journal_root = tmp_path / "run-journals"
    journal_root.mkdir(parents=True, exist_ok=True)
    # Patch the single owner of the helper. It used to also patch
    # chat_primary.run_event_journal_path, but that attribute has not existed
    # since the helper moved to backend/runtime/events.py:42 -- chat_primary
    # calls it through the module (chat_primary.py:619,
    # `runtime_events.run_event_journal_path(run_id)`), so patching the name on
    # chat_primary raised AttributeError from monkeypatch.setattr and took the
    # whole scenario down. Patch the definition site, not the call site.
    monkeypatch.setattr(
        runtime_events,
        "run_event_journal_path",
        lambda run_id: journal_root / f"{run_id}.jsonl",
    )
    state_attrs = {
        name: (hasattr(main_module.app.state, name), getattr(main_module.app.state, name, None))
        for name in ("ollama", "llm_client")
    }

    from backend.tests import e2e_audit_scenarios

    e2e_audit_scenarios.RESULTS.clear()
    try:
        result = e2e_audit_scenarios.main(results_path=tmp_path / "e2e_audit_results.json")
        assert result == 0
        assert len(e2e_audit_scenarios.RESULTS) == 16
        assert all(scenario["ok"] for scenario in e2e_audit_scenarios.RESULTS)
    finally:
        OllamaClient.__init__ = previous_ollama_init
        llm_package.create_llm_client = previous_factory
        logging_config.setup_logging = previous_setup_logging
        for name, (existed, value) in state_attrs.items():
            if existed:
                setattr(main_module.app.state, name, value)
            elif hasattr(main_module.app.state, name):
                delattr(main_module.app.state, name)
        settings_module.get_settings.cache_clear()
        settings_module._settings_instance = previous_settings
