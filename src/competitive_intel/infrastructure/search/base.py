"""Search provider protocol."""

from typing import Protocol

from competitive_intel.domain.search import SearchRequest, SearchResponse


class SearchProvider(Protocol):
    @property
    def name(self) -> str: ...

    def search(self, request: SearchRequest) -> SearchResponse: ...
