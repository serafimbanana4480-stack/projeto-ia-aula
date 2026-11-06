"""Tests for core module."""

from demo.core import greet, AppConfig

def test_greet() -> None:
    assert greet("Alice") == "Hello, Alice!"

def test_greet_default() -> None:
    assert greet() == "Hello, World!"

def test_app_config() -> None:
    config = AppConfig(debug=True)
    assert config.debug is True
