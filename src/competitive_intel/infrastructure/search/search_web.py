"""Search-only entrypoint; it performs no validation, fetching, or persistence."""

from competitive_intel.domain.search import SearchRequest, SearchResponse

from .base import SearchProvider


def search_web(
    provider: SearchProvider, request: SearchRequest
) -> SearchResponse:
    return provider.search(request)
