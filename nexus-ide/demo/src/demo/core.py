"""Core module for demo."""

from typing import Any

class AppConfig:
    """Application configuration."""
    
    def __init__(self, debug: bool = False) -> None:
        self.debug = debug

def greet(name: str = "World") -> str:
    """Return a greeting message."""
    return f"Hello, {name}!"
