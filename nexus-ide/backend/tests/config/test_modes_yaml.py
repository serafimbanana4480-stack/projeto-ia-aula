"""Tests for config/modes.yaml — structural validation."""

from __future__ import annotations

import pytest
import yaml


class TestModesYamlStructure:
    @pytest.fixture
    def modes_yaml(self) -> dict:
        from backend.config.settings import CONFIG_DIR

        path = CONFIG_DIR / "modes.yaml"
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    def test_top_level_keys(self, modes_yaml: dict) -> None:
        assert "modes" in modes_yaml
        assert "tool_aliases" in modes_yaml
        assert "all" in modes_yaml["tool_aliases"]

    def test_required_modes(self, modes_yaml: dict) -> None:
        required_modes = {
            "auto",
            "coder",
            "analyst",
            "fast",
            "deep",
            "plan",
            "debug",
            "ask",
            "swarm",
            "dashboard",
        }
        assert required_modes.issubset(modes_yaml["modes"].keys())

    def test_mode_fields(self, modes_yaml: dict) -> None:
        for mode_name, spec in modes_yaml["modes"].items():
            assert "description" in spec, f"Mode {mode_name} missing description"
            assert "default_agent" in spec, f"Mode {mode_name} missing default_agent"
            assert "default_model" in spec, f"Mode {mode_name} missing default_model"
            assert "router" in spec, f"Mode {mode_name} missing router"
            assert "tools_enabled" in spec, f"Mode {mode_name} missing tools_enabled"
            assert "system_prompt_addon" in spec, f"Mode {mode_name} missing system_prompt_addon"

    def test_auto_mode_capabilities(self, modes_yaml: dict) -> None:
        auto = modes_yaml["modes"]["auto"]
        assert auto["router"] == "smart"
        assert auto["supports_subagents"] is True
        assert auto["max_iterations"] >= 7
        assert auto["enable_thinking"] is True

    def test_swarm_mode_capabilities(self, modes_yaml: dict) -> None:
        swarm = modes_yaml["modes"]["swarm"]
        assert swarm["supports_subagents"] is True
        assert "consult_agent" in modes_yaml["tool_aliases"]["all"]
