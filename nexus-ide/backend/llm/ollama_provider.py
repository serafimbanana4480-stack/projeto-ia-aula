"""Backwards-compatible Ollama provider export."""

from __future__ import annotations

from backend.tools.ollama_client import OllamaClient as OllamaProvider

__all__ = ["OllamaProvider"]
