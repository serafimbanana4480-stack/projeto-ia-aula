from __future__ import annotations

from backend.orchestrator.advanced_modes import (
    get_advanced_mode,
    get_command_aliases,
    resolve_command,
)


def test_command_catalog_has_valid_modes_and_aliases() -> None:
    commands = get_command_aliases()

    assert commands
    for command_name, command in commands.items():
        assert command["aliases"], command_name
        assert get_advanced_mode(command["mode"]) is not None
        for alias in command["aliases"]:
            assert alias.startswith("/")
            assert resolve_command(alias)["mode"] == command["mode"]


def test_command_resolution_is_case_insensitive_and_accepts_canonical_name() -> None:
    assert resolve_command("/FORGE")["mode"] == "forge"
    assert resolve_command("forge")["mode"] == "forge"


def test_unknown_command_is_not_activated() -> None:
    assert resolve_command("/not-a-nexus-command") is None
