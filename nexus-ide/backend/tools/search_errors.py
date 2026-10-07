"""Errors that let search callers distinguish provider outages from no hits."""

from __future__ import annotations


class SearchProviderError(RuntimeError):
    """A configured search provider failed before returning usable results."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"{provider} search provider failed")
        self.provider = provider


class SearchProvidersUnavailable(RuntimeError):
    """No usable search result could be obtained from the available providers."""

    def __init__(self, providers: list[str]) -> None:
        self.providers = tuple(providers)
        super().__init__("Search providers unavailable: " + ", ".join(providers))
