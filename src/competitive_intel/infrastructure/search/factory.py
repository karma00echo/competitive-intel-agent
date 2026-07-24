"""Configured search-provider construction."""

from pathlib import Path

from .base import SearchProvider
from .providers.fixture import FixtureSearchProvider


def create_search_provider(
    provider: str, *, fixture_path: str | Path | None = None
) -> SearchProvider:
    normalized = provider.strip().lower()
    if normalized == "fixture":
        return FixtureSearchProvider(fixture_path)
    raise ValueError(
        f"Search provider {provider!r} is not implemented. "
        "Use fixture or add an adapter implementing SearchProvider."
    )
