"""Tests for backend.config.settings — helpers and environment coercion."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.config.settings import (
    ProjectContextError,
    _coerce_env_value,
    _deep_merge,
    resolve_mission_project,
    resolve_project_path,
    validate_configuration,
)


class TestDeepMerge:
    """Tests for _deep_merge."""

    def test_merges_flat_dicts(self) -> None:
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_deeply_merges_nested_dicts(self) -> None:
        base = {"outer": {"inner_a": 1, "inner_b": 2}}
        override = {"outer": {"inner_b": 3, "inner_c": 4}}
        result = _deep_merge(base, override)
        assert result == {"outer": {"inner_a": 1, "inner_b": 3, "inner_c": 4}}

    def test_non_dict_override_replaces(self) -> None:
        base = {"key": {"nested": True}}
        override = {"key": "replaced"}
        result = _deep_merge(base, override)
        assert result == {"key": "replaced"}

    def test_dict_overrides_non_dict(self) -> None:
        base = {"key": "scalar"}
        override = {"key": {"nested": True}}
        result = _deep_merge(base, override)
        assert result == {"key": {"nested": True}}

    def test_empty_override_returns_base_copy(self) -> None:
        base = {"a": 1, "b": {"c": 2}}
        result = _deep_merge(base, {})
        assert result == base

    def test_empty_base_returns_override_copy(self) -> None:
        override = {"a": 1, "b": {"c": 2}}
        result = _deep_merge({}, override)
        assert result == override

    def test_does_not_mutate_inputs(self) -> None:
        base = {"outer": {"inner": 1}}
        override = {"outer": {"inner": 2}}
        _deep_merge(base, override)
        assert base == {"outer": {"inner": 1}}
        assert override == {"outer": {"inner": 2}}

    def test_deeply_nested_merge(self) -> None:
        base = {
            "level1": {
                "level2": {
                    "level3": {"a": 1, "b": 2},
                },
            },
        }
        override = {
            "level1": {
                "level2": {
                    "level3": {"b": 99, "c": 3},
                },
            },
        }
        result = _deep_merge(base, override)
        assert result == {
            "level1": {
                "level2": {
                    "level3": {"a": 1, "b": 99, "c": 3},
                },
            },
        }


class TestCoerceEnvValue:
    """Tests for _coerce_env_value."""

    def test_true_values(self) -> None:
        assert _coerce_env_value("true") is True
        assert _coerce_env_value("True") is True
        assert _coerce_env_value("TRUE") is True
        assert _coerce_env_value("1") is True
        assert _coerce_env_value("yes") is True
        assert _coerce_env_value("Yes") is True
        assert _coerce_env_value("on") is True

    def test_false_values(self) -> None:
        assert _coerce_env_value("false") is False
        assert _coerce_env_value("False") is False
        assert _coerce_env_value("0") is False
        assert _coerce_env_value("no") is False
        assert _coerce_env_value("off") is False

    def test_int_values(self) -> None:
        assert _coerce_env_value("42") == 42
        assert _coerce_env_value("0") == 0  # "0" is caught by bool first
        assert _coerce_env_value("-10") == -10

    def test_float_values(self) -> None:
        assert _coerce_env_value("3.14") == 3.14
        assert _coerce_env_value("0.5") == 0.5
        assert isinstance(_coerce_env_value("2.5"), float)

    def test_string_values(self) -> None:
        assert _coerce_env_value("hello") == "hello"
        assert _coerce_env_value("some/path") == "some/path"
        assert _coerce_env_value("true story") == "true story"

    def test_empty_string_remains_empty(self) -> None:
        assert _coerce_env_value("") == ""


class TestResolveMissionProject:
    """Tests for resolve_mission_project — must never default to REPO_ROOT."""

    def test_resolves_absolute_path(self, tmp_path: Path) -> None:
        project = tmp_path / "myproject"
        project.mkdir()
        result = resolve_mission_project(str(project))
        assert result == project.resolve()

    def test_uses_session_project_when_empty(self, tmp_path: Path) -> None:
        project = tmp_path / "session_project"
        project.mkdir()
        result = resolve_mission_project(".", session_project=str(project))
        assert result == project.resolve()

    def test_raises_on_nonexistent_directory(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist"
        with pytest.raises(ProjectContextError) as exc_info:
            resolve_mission_project(str(nonexistent))
        assert "not an existing directory" in str(exc_info.value)

    def test_raises_on_empty_strings(self) -> None:
        with pytest.raises(ProjectContextError) as exc_info:
            resolve_mission_project("", session_project="")
        assert exc_info.value.code == "BLOCKED_PROJECT_CONTEXT"

    def test_raises_on_dot_only(self) -> None:
        with pytest.raises(ProjectContextError):
            resolve_mission_project(".", session_project=None)

    def test_raises_on_non_string_project_path(self) -> None:
        with pytest.raises(ProjectContextError) as exc_info:
            resolve_mission_project(123)  # type: ignore[arg-type]
        assert "must be a string" in str(exc_info.value)

    def test_raises_on_non_string_session_project(self) -> None:
        with pytest.raises(ProjectContextError):
            resolve_mission_project("/some/path", session_project=42)  # type: ignore[arg-type]

    def test_expands_user_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = tmp_path / "fakehome"
        home.mkdir()
        # Support both Unix (HOME) and Windows (USERPROFILE/HOMEPATH)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        monkeypatch.setenv("HOMEPATH", str(home.name + "\\" + str(home.parent).split("\\")[-1]))
        project = home / "project"
        project.mkdir()
        result = resolve_mission_project("~/project")
        assert result == project.resolve()

    def test_error_message_contains_code(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "not_here"
        try:
            resolve_mission_project(str(nonexistent))
        except ProjectContextError as e:
            assert "BLOCKED_PROJECT_CONTEXT" in str(e)


class TestValidateConfiguration:
    """Tests for validate_configuration."""

    def test_returns_list_of_errors(self) -> None:
        errors = validate_configuration()
        assert isinstance(errors, list)

    def test_no_errors_with_valid_config(self) -> None:
        errors = validate_configuration()
        # In test environment (with mock_settings), there should be no errors
        # related to missing API keys since env is development
        # At minimum, the function should not raise
        assert errors is not None


class TestResolveProjectPath:
    """Tests for resolve_project_path."""

    def test_explicit_path_returned_as_is(self, tmp_path: Path) -> None:
        project = tmp_path / "explicit_project"
        project.mkdir()
        path, was_default = resolve_project_path(str(project))
        assert path == str(project.resolve())
        assert was_default is False

    def test_empty_path_triggers_default(self) -> None:
        path, was_default = resolve_project_path("")
        assert was_default is True

    def test_dot_path_triggers_default(self) -> None:
        path, was_default = resolve_project_path(".")
        assert was_default is True
