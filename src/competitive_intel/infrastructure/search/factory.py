"""Configured search-provider construction."""

from pathlib import Path

from .base import SearchProvider
from .providers.fixture import FixtureSearchProvider
from .providers.serper import DEFAULT_SERPER_ENDPOINT, SerperSearchProvider


def create_search_provider(
    provider: str,
    *,
    fixture_path: str | Path | None = None,
    api_key: str | None = None,
    endpoint: str | None = None,
) -> SearchProvider:
    normalized = provider.strip().lower()
    if normalized == "fixture":
        return FixtureSearchProvider(fixture_path)
    if normalized == "serper":
        return SerperSearchProvider(
            api_key, endpoint=endpoint or DEFAULT_SERPER_ENDPOINT
        )
    raise ValueError(
        f"Search provider {provider!r} is not implemented. "
        "Use fixture or add an adapter implementing SearchProvider."
    )
