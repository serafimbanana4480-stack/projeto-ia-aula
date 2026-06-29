"""Tests for project path resolution defaults."""

from __future__ import annotations

from backend.config.settings import REPO_ROOT, resolve_project_path


def test_empty_project_path_defaults_to_repo_root() -> None:
    resolved, defaulted = resolve_project_path("")
    assert defaulted is True
    assert resolved == str(REPO_ROOT)


def test_dot_project_path_defaults_to_repo_root() -> None:
    resolved, defaulted = resolve_project_path(".")
    assert defaulted is True
    assert resolved == str(REPO_ROOT)


def test_explicit_project_path_is_preserved() -> None:
    explicit = r"C:\Projects\my-app"
    resolved, defaulted = resolve_project_path(explicit)
    assert defaulted is False
    assert resolved == explicit
