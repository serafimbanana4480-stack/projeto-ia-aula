"""Safety contract for the global and per-service background switches."""

from backend.orchestrator.main import _background_service_enabled


def test_global_background_switch_disables_service_even_when_explicitly_enabled(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NEXUS_BACKGROUND_SERVICES", "off")
    monkeypatch.setenv("NEXUS_ENABLE_CATALOG_REFRESH", "true")
    monkeypatch.setenv("NEXUS_ENABLE_LOG_PRUNE", "true")

    assert not _background_service_enabled("CATALOG_REFRESH")
    assert not _background_service_enabled("LOG_PRUNE")


def test_per_service_switch_can_disable_service_when_global_switch_is_on(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NEXUS_BACKGROUND_SERVICES", "on")
    monkeypatch.setenv("NEXUS_ENABLE_CATALOG_REFRESH", "false")

    assert not _background_service_enabled("CATALOG_REFRESH")


def test_background_services_are_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("NEXUS_BACKGROUND_SERVICES", raising=False)
    monkeypatch.delenv("NEXUS_ENABLE_CATALOG_REFRESH", raising=False)

    assert _background_service_enabled("CATALOG_REFRESH")
